"""Load and check board profiles and project configuration files.

A project configuration names a board profile and lists the devices that are
connected to the board. The loader checks each device against the chip and
board facts, and returns typed dataclasses. Refer to docs/board_profiles.md and
docs/project_config.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_DIR = Path(__file__).resolve().parents[2]
BOARDS_DIR = REPO_DIR / "boards"
CHIPS_DIR = BOARDS_DIR / "chips"

MODES = ("agent", "log")
GENERIC_PREFIX = "generic_"
DEFAULT_CHIP = "esp32"
LINKS = ("uart0", "usb_serial_jtag")
DEVICE_TYPES = (
    "digital_in",
    "digital_out",
    "adc",
    "pwm",
    "servo",
    "button",
    "led",
    "counter",
    "i2c",
    "uart",
    "ds18b20",
    "dht11",
    "dht22",
    "hx711",
)
OUTPUT_TYPES = ("digital_out", "pwm", "servo", "led")
SENSOR_TYPES = ("ds18b20", "dht11", "dht22")
# Two-GPIO types and the YAML keys of their GPIOs: the first goes to gpio, the
# second to gpio2.
TWO_GPIO_KEYS = {"i2c": ("sda", "scl"), "uart": ("tx", "rx"), "hx711": ("clock", "data")}
# The optional third GPIO of an HX711: the data line of a second HX711 on the
# same clock.
HX711_SECOND_KEY = "data2"
HX711_GAINS = (128, 64, 32)
ONBOARD_TYPES = ("led", "button", "adc")
PULLS = ("none", "up", "down")
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,22}$")
MAX_DEVICES = 48
DEFAULT_REPORT_PERIOD_MS = 100
DEFAULT_BAUD = 115200
DEFAULT_PWM_FREQ_HZ = 1000
DEFAULT_SERVO_MIN_US = 500
DEFAULT_SERVO_MAX_US = 2500
DEFAULT_SERVO_ANGLE = 90.0
DEFAULT_I2C_FREQ_HZ = 100_000
DEFAULT_UNITS = {"adc": "mV", "ds18b20": "°C", "dht11": "°C", "dht22": "°C", "counter": "Hz"}
DEFAULT_UART_BAUD = 9600


class ConfigError(Exception):
    """A configuration file has one or more errors."""

    def __init__(self, source: str, errors: list[str]) -> None:
        self.source = source
        self.errors = errors
        super().__init__(f"{source}: " + "; ".join(errors))


@dataclass(frozen=True)
class Chip:
    chip: str
    title: str
    gpios: frozenset[int]
    uart0_tx: int
    uart0_rx: int
    input_only: frozenset[int]
    reserved: dict[int, str]
    strapping: dict[int, str]
    adc1: frozenset[int]
    adc2: frozenset[int]
    adc2_conflicts_with_wifi: bool
    touch: frozenset[int]
    dac: frozenset[int]
    notes: dict[int, str]

    def has_adc(self, gpio: int) -> bool:
        return gpio in self.adc1 or gpio in self.adc2


@dataclass(frozen=True)
class OnboardPart:
    id: str
    gpio: int
    type: str
    active_low: bool
    notes: str


@dataclass(frozen=True)
class Board:
    name: str
    title: str
    chip: Chip
    flash_mb: int
    psram_mb: int
    link: str
    usb: str
    verified: bool
    sources: tuple[str, ...]
    pins: frozenset[int]
    labels: dict[int, str]
    reserved: dict[int, str]
    notes: dict[int, str]
    onboard: tuple[OnboardPart, ...]
    # The header pins in physical order, from the antenna end to the USB end,
    # with the board in portrait. A GPIO number or a label such as GND.
    header_left: tuple[int | str, ...] = ()
    header_right: tuple[int | str, ...] = ()

    def never_usable(self) -> dict[int, str]:
        """GPIOs that no device can use, with the reason."""
        blocked = dict(self.chip.reserved)
        if self.link == "uart0":
            blocked[self.chip.uart0_tx] = "UART0 TX, the bench agent link"
            blocked[self.chip.uart0_rx] = "UART0 RX, the bench agent link"
        return blocked

    def label(self, gpio: int) -> str:
        return self.labels.get(gpio, f"GPIO{gpio}")

    def pin_info(self, gpio: int) -> list[str]:
        """All facts about one GPIO, for display."""
        info = []
        blocked = self.never_usable()
        if gpio in blocked:
            info.append(f"reserved: {blocked[gpio]}")
        if gpio in self.reserved:
            info.append(f"board: {self.reserved[gpio]}")
        if gpio in self.chip.strapping:
            info.append(f"strapping: {self.chip.strapping[gpio]}")
        if gpio in self.chip.input_only:
            info.append("input only")
        if gpio in self.chip.adc1:
            info.append("ADC1")
        if gpio in self.chip.adc2:
            info.append("ADC2")
        if gpio in self.chip.touch:
            info.append("touch")
        if gpio in self.chip.dac:
            info.append("DAC")
        for notes in (self.chip.notes, self.notes):
            if gpio in notes:
                info.append(notes[gpio])
        for part in self.onboard:
            if part.gpio == gpio:
                info.append(f"on-board {part.type} '{part.id}'")
        return info


@dataclass(frozen=True)
class Device:
    name: str
    type: str
    gpio: int
    pull: str = "none"
    invert: bool = False
    initial: float = 0.0
    freq_hz: int = DEFAULT_PWM_FREQ_HZ
    min_us: int = DEFAULT_SERVO_MIN_US
    max_us: int = DEFAULT_SERVO_MAX_US
    gpio2: int = -1
    gpio3: int = -1
    gain: int = 128
    baud: int = DEFAULT_UART_BAUD
    scale: float = 1.0
    offset: float = 0.0
    units: str = ""
    allow_reserved: bool = False

    @property
    def mode(self) -> str:
        """The firmware pin mode for this device type."""
        if self.type == "button":
            return "digital_in"
        if self.type == "led":
            return "digital_out"
        if self.type == "counter":
            return "digital_in"
        return self.type

    @property
    def is_output(self) -> bool:
        return self.type in OUTPUT_TYPES

    def gpio_roles(self) -> list[tuple[int, str, bool]]:
        """Each GPIO of the device: (gpio, role, needs an output driver)."""
        if self.type in TWO_GPIO_KEYS:
            first, second = TWO_GPIO_KEYS[self.type]
            roles = [(self.gpio, first, True), (self.gpio2, second, self.type == "i2c")]
            if self.type == "hx711" and self.gpio3 >= 0:
                roles.append((self.gpio3, HX711_SECOND_KEY, False))
            return roles
        needs_output = self.is_output or self.type in SENSOR_TYPES
        return [(self.gpio, "gpio", needs_output)]

    @property
    def gpios(self) -> list[int]:
        return [gpio for gpio, _role, _output in self.gpio_roles()]

    def gpio_text(self) -> str:
        if self.type in TWO_GPIO_KEYS:
            return " ".join(f"{role} {gpio}" for gpio, role, _output in self.gpio_roles())
        return str(self.gpio)

    def display_value(self, raw: float) -> float:
        """Convert a value from the agent into the configured units."""
        return raw * self.scale + self.offset

    def wire_pin(self) -> dict[str, Any]:
        """The pin entry of a protocol config message."""
        pin: dict[str, Any] = {"id": self.name, "mode": self.mode}
        if self.type in TWO_GPIO_KEYS:
            first, second = TWO_GPIO_KEYS[self.type]
            pin[first] = self.gpio
            pin[second] = self.gpio2
        else:
            pin["gpio"] = self.gpio
        if self.mode == "hx711":
            if self.gpio3 >= 0:
                pin[HX711_SECOND_KEY] = self.gpio3
            pin["gain"] = self.gain
        elif self.mode == "i2c":
            pin["freq_hz"] = self.freq_hz
        elif self.mode == "uart":
            pin["baud"] = self.baud
        elif self.mode == "digital_in":
            pin["pull"] = self.pull
            pin["invert"] = self.invert
        elif self.mode == "digital_out":
            pin["invert"] = self.invert
            pin["initial"] = int(self.initial)
        elif self.mode == "pwm":
            pin["freq_hz"] = self.freq_hz
            pin["initial"] = self.initial
        elif self.mode == "servo":
            pin["min_us"] = self.min_us
            pin["max_us"] = self.max_us
            pin["initial"] = self.initial
        return pin


@dataclass(frozen=True)
class LogValue:
    name: str
    pattern: re.Pattern[str]
    units: str = ""
    scale: float = 1.0
    offset: float = 0.0


@dataclass(frozen=True)
class ProjectConfig:
    path: Path
    board: Board
    mode: str
    port: str | None
    baud: int
    report_period_ms: int
    devices: tuple[Device, ...]
    log_values: tuple[LogValue, ...]
    warnings: tuple[str, ...] = field(default=())

    def device(self, name: str) -> Device | None:
        for device in self.devices:
            if device.name == name:
                return device
        return None

    def wire_config(self) -> dict[str, Any]:
        """The body of a protocol config message, without type and seq."""
        return {
            "report_period_ms": self.report_period_ms,
            "pins": [device.wire_pin() for device in self.devices],
        }


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text())
    except OSError as error:
        raise ConfigError(str(path), [f"cannot read the file: {error.strerror}"]) from error
    except yaml.YAMLError as error:
        raise ConfigError(str(path), [f"YAML syntax error: {error}"]) from error
    if not isinstance(data, dict):
        raise ConfigError(str(path), ["the file must hold a YAML mapping"])
    return data


def _int_set(value: Any) -> frozenset[int]:
    return frozenset(int(item) for item in (value or []))


def _int_map(value: Any) -> dict[int, str]:
    return {int(key): str(text) for key, text in (value or {}).items()}


def load_chip(chip: str, chips_dir: Path = CHIPS_DIR) -> Chip:
    path = chips_dir / f"{chip}.yaml"
    if not path.exists():
        raise ConfigError(str(path), [f"no chip file for chip '{chip}'"])
    data = _read_yaml(path)
    uart0 = data.get("uart0") or {}
    return Chip(
        chip=str(data["chip"]),
        title=str(data.get("title", chip)),
        gpios=_int_set(data.get("gpios")),
        uart0_tx=int(uart0.get("tx", -1)),
        uart0_rx=int(uart0.get("rx", -1)),
        input_only=_int_set(data.get("input_only")),
        reserved=_int_map(data.get("reserved")),
        strapping=_int_map(data.get("strapping")),
        adc1=_int_set(data.get("adc1")),
        adc2=_int_set(data.get("adc2")),
        adc2_conflicts_with_wifi=bool(data.get("adc2_conflicts_with_wifi", False)),
        touch=_int_set(data.get("touch")),
        dac=_int_set(data.get("dac")),
        notes=_int_map(data.get("notes")),
    )


def list_boards(boards_dir: Path = BOARDS_DIR) -> list[str]:
    return sorted(path.stem for path in boards_dir.glob("*.yaml"))


def list_chips(boards_dir: Path = BOARDS_DIR) -> list[str]:
    return sorted(path.stem for path in (boards_dir / "chips").glob("*.yaml"))


def generic_board(chip_name: str, boards_dir: Path = BOARDS_DIR) -> Board:
    """A board with every usable GPIO of a chip and no board facts. Use it for
    a board that has no profile. Its name is generic_<chip>."""
    if chip_name not in list_chips(boards_dir):
        known = ", ".join(list_chips(boards_dir))
        raise ConfigError(f"{GENERIC_PREFIX}{chip_name}", [f"no chip file for '{chip_name}'. Known chips: {known}"])
    chip = load_chip(chip_name, boards_dir / "chips")
    blocked = dict(chip.reserved)
    blocked[chip.uart0_tx] = "UART0"
    blocked[chip.uart0_rx] = "UART0"
    return Board(
        name=f"{GENERIC_PREFIX}{chip_name}",
        title=f"Generic {chip.title} board",
        chip=chip,
        flash_mb=0,
        psram_mb=0,
        link="uart0",
        usb="",
        verified=False,
        sources=(),
        pins=frozenset(gpio for gpio in chip.gpios if gpio not in blocked),
        labels={},
        reserved={},
        notes={},
        onboard=(),
    )


def load_board(name: str, boards_dir: Path = BOARDS_DIR) -> Board:
    if name.startswith(GENERIC_PREFIX):
        return generic_board(name.removeprefix(GENERIC_PREFIX), boards_dir)
    path = boards_dir / f"{name}.yaml"
    if not path.exists():
        known = ", ".join(list_boards(boards_dir))
        raise ConfigError(str(path), [f"no board profile '{name}'. Known boards: {known}"])
    data = _read_yaml(path)
    errors = []
    chip = load_chip(str(data.get("chip")), boards_dir / "chips")
    link = str(data.get("link", "uart0"))
    if link not in LINKS:
        errors.append(f"link must be one of {', '.join(LINKS)}")

    board_reserved = _int_map(data.get("reserved"))
    blocked = dict(chip.reserved)
    if link == "uart0":
        blocked[chip.uart0_tx] = "UART0"
        blocked[chip.uart0_rx] = "UART0"
    pins_value = data.get("pins", "all")
    if pins_value == "all":
        pins = frozenset(gpio for gpio in chip.gpios if gpio not in blocked)
    else:
        pins = _int_set(pins_value)
    unknown = sorted(pins - chip.gpios)
    if unknown:
        errors.append(f"pins {unknown} are not GPIOs of {chip.chip}")

    onboard = []
    for entry in data.get("onboard") or []:
        part = OnboardPart(
            id=str(entry["id"]),
            gpio=int(entry["gpio"]),
            type=str(entry["type"]),
            active_low=bool(entry.get("active_low", False)),
            notes=str(entry.get("notes", "")),
        )
        if part.type not in ONBOARD_TYPES:
            errors.append(f"onboard '{part.id}': type must be one of {', '.join(ONBOARD_TYPES)}")
        if part.gpio not in chip.gpios:
            errors.append(f"onboard '{part.id}': GPIO {part.gpio} is not a GPIO of {chip.chip}")
        onboard.append(part)

    headers = {}
    for key in ("header_left", "header_right"):
        entries: list[int | str] = []
        for item in data.get(key) or []:
            if isinstance(item, int):
                if item not in chip.gpios:
                    errors.append(f"{key}: GPIO {item} is not a GPIO of {chip.chip}")
                entries.append(item)
            else:
                entries.append(str(item))
        headers[key] = tuple(entries)

    if errors:
        raise ConfigError(str(path), errors)
    return Board(
        header_left=headers["header_left"],
        header_right=headers["header_right"],
        name=str(data.get("name", name)),
        title=str(data.get("title", name)),
        chip=chip,
        flash_mb=int(data.get("flash_mb", 0)),
        psram_mb=int(data.get("psram_mb", 0)),
        link=link,
        usb=str(data.get("usb", "")),
        verified=bool(data.get("verified", False)),
        sources=tuple(str(source) for source in data.get("sources") or []),
        pins=pins,
        labels=_int_map(data.get("labels")),
        reserved=board_reserved,
        notes=_int_map(data.get("notes")),
        onboard=tuple(onboard),
    )


def _device_defaults(entry: dict[str, Any], part: OnboardPart | None) -> dict[str, Any]:
    """Fill in the type and options that come from the device type or an on-board part."""
    values = dict(entry)
    if part is not None:
        values.setdefault("gpio", part.gpio)
        values.setdefault("type", part.type)
        if part.type in ("button", "led"):
            values.setdefault("invert", part.active_low)
    device_type = values.get("type")
    if device_type == "button":
        values.setdefault("pull", "up")
        values.setdefault("invert", True)
    if device_type == "servo":
        values.setdefault("initial", DEFAULT_SERVO_ANGLE)
    if device_type == "i2c":
        values.setdefault("freq_hz", DEFAULT_I2C_FREQ_HZ)
    if device_type in TWO_GPIO_KEYS:
        first, second = TWO_GPIO_KEYS[device_type]
        if first in values:
            values["gpio"] = values.pop(first)
        if second in values:
            values["gpio2"] = values.pop(second)
    if device_type == "hx711" and HX711_SECOND_KEY in values:
        values["gpio3"] = values.pop(HX711_SECOND_KEY)
    return values


def _check_gpio(device: Device, gpio: int, role: str, needs_output: bool, board: Board, errors: list[str], warnings: list[str]) -> None:
    where = f"device '{device.name}'" + ("" if role == "gpio" else f" {role}")
    chip = board.chip
    if gpio not in chip.gpios:
        errors.append(f"{where}: GPIO {gpio} is not a GPIO of {chip.title}")
        return
    blocked = board.never_usable()
    if gpio in blocked:
        errors.append(f"{where}: GPIO {gpio} is reserved ({blocked[gpio]})")
        return
    onboard_gpios = {part.gpio for part in board.onboard}
    if gpio not in board.pins and gpio not in onboard_gpios:
        errors.append(f"{where}: GPIO {gpio} is not on the headers of {board.title}")
    if gpio in board.reserved and not device.allow_reserved:
        errors.append(
            f"{where}: GPIO {gpio} is used by the board ({board.reserved[gpio]}). "
            "Set allow_reserved: true if that part is not in use"
        )
    if needs_output and gpio in chip.input_only:
        errors.append(f"{where}: GPIO {gpio} is input-only")
    if device.mode == "adc" and not chip.has_adc(gpio):
        errors.append(f"{where}: GPIO {gpio} has no ADC channel")
    if device.mode == "digital_in" and device.pull != "none" and gpio in chip.input_only:
        warnings.append(f"{where}: GPIO {gpio} has no internal pull resistor. Use an external one")
    if gpio in chip.strapping:
        warnings.append(f"{where}: GPIO {gpio} is a strapping pin. {chip.strapping[gpio]}")
    if device.mode == "adc" and gpio in chip.adc2 and chip.adc2_conflicts_with_wifi:
        warnings.append(f"{where}: GPIO {gpio} is on ADC2, which cannot read while Wi-Fi is on")


def _check_device(device: Device, board: Board, errors: list[str], warnings: list[str]) -> None:
    where = f"device '{device.name}'"
    for gpio, role, needs_output in device.gpio_roles():
        _check_gpio(device, gpio, role, needs_output, board, errors, warnings)
    if device.type in TWO_GPIO_KEYS and device.gpio == device.gpio2:
        errors.append(f"{where}: the two GPIOs must differ")
    if device.mode == "i2c" and not 1000 <= device.freq_hz <= 1_000_000:
        errors.append(f"{where}: I2C freq_hz must be 1000 to 1000000")
    if device.mode == "uart" and not 300 <= device.baud <= 2_000_000:
        errors.append(f"{where}: baud must be 300 to 2000000")
    if device.mode == "hx711":
        if device.gain not in HX711_GAINS:
            errors.append(f"{where}: gain must be 128, 64 or 32")
        if device.gpio3 >= 0 and device.gpio3 in (device.gpio, device.gpio2):
            errors.append(f"{where}: data2 must be another GPIO")
        warnings.append(
            f"{where}: power the HX711 from 3.3 V. At 5 V its data lines put 5 V on the ESP32 inputs"
        )
    if device.type in SENSOR_TYPES:
        warnings.append(f"{where}: needs a 4.7 kOhm pull-up resistor to 3.3 V on GPIO {device.gpio}")
    if device.pull not in PULLS:
        errors.append(f"{where}: pull must be one of {', '.join(PULLS)}")
    if device.mode == "pwm" and not 1 <= device.freq_hz <= 40_000_000:
        errors.append(f"{where}: freq_hz must be 1 to 40000000")
    if device.mode == "pwm" and not 0.0 <= device.initial <= 1.0:
        errors.append(f"{where}: initial duty must be 0.0 to 1.0")
    if device.mode == "servo":
        if not 100 <= device.min_us < device.max_us <= 3000:
            errors.append(f"{where}: servo pulse must satisfy 100 <= min_us < max_us <= 3000")
        if not 0.0 <= device.initial <= 180.0:
            errors.append(f"{where}: initial angle must be 0 to 180")
    if device.mode == "digital_out" and device.initial not in (0, 1):
        errors.append(f"{where}: initial level must be 0 or 1")


def _build_device(entry: Any, board: Board, errors: list[str]) -> Device | None:
    if not isinstance(entry, dict):
        errors.append("each device must be a mapping")
        return None
    name = str(entry.get("name", ""))
    if not NAME_PATTERN.match(name):
        errors.append(
            f"device name '{name}' must start with a lower-case letter, use only a-z, 0-9 and _, "
            "and have at most 23 characters"
        )
        return None
    part = None
    onboard_id = entry.get("onboard")
    if onboard_id is not None:
        part = next((item for item in board.onboard if item.id == onboard_id), None)
        if part is None:
            known = ", ".join(item.id for item in board.onboard) or "none"
            errors.append(f"device '{name}': board has no onboard part '{onboard_id}'. Known: {known}")
            return None
    values = _device_defaults(entry, part)
    device_type = values.get("type")
    if device_type not in DEVICE_TYPES:
        errors.append(f"device '{name}': type must be one of {', '.join(DEVICE_TYPES)}")
        return None
    if device_type in TWO_GPIO_KEYS and ("gpio" not in values or "gpio2" not in values):
        first, second = TWO_GPIO_KEYS[device_type]
        errors.append(f"device '{name}': {first} and {second} are required")
        return None
    if "gpio" not in values:
        errors.append(f"device '{name}': gpio or onboard is required")
        return None
    known_keys = set(Device.__dataclass_fields__) | {"onboard"}
    unknown_keys = sorted(set(values) - known_keys)
    if unknown_keys:
        errors.append(f"device '{name}': unknown keys {', '.join(unknown_keys)}")
        return None
    try:
        return Device(
            name=name,
            type=str(device_type),
            gpio=int(values["gpio"]),
            pull=str(values.get("pull", "none")),
            invert=bool(values.get("invert", False)),
            initial=float(values.get("initial", 0.0)),
            freq_hz=int(values.get("freq_hz", DEFAULT_PWM_FREQ_HZ)),
            min_us=int(values.get("min_us", DEFAULT_SERVO_MIN_US)),
            max_us=int(values.get("max_us", DEFAULT_SERVO_MAX_US)),
            gpio2=int(values.get("gpio2", -1)),
            gpio3=int(values.get("gpio3", -1)),
            gain=int(values.get("gain", 128)),
            baud=int(values.get("baud", DEFAULT_UART_BAUD)),
            scale=float(values.get("scale", 1.0)),
            offset=float(values.get("offset", 0.0)),
            units=str(values.get("units", DEFAULT_UNITS.get(str(device_type), ""))),
            allow_reserved=bool(values.get("allow_reserved", False)),
        )
    except (TypeError, ValueError) as error:
        errors.append(f"device '{name}': {error}")
        return None


def _build_log_value(entry: Any, errors: list[str]) -> LogValue | None:
    if not isinstance(entry, dict):
        errors.append("each log value must be a mapping")
        return None
    name = str(entry.get("name", ""))
    if not NAME_PATTERN.match(name):
        errors.append(f"log value name '{name}' is not valid")
        return None
    try:
        pattern = re.compile(str(entry.get("pattern", "")))
    except re.error as error:
        errors.append(f"log value '{name}': bad regex: {error}")
        return None
    if pattern.groups < 1:
        errors.append(f"log value '{name}': the regex needs one capture group for the value")
        return None
    return LogValue(
        name=name,
        pattern=pattern,
        units=str(entry.get("units", "")),
        scale=float(entry.get("scale", 1.0)),
        offset=float(entry.get("offset", 0.0)),
    )


def load_project(path: Path, boards_dir: Path = BOARDS_DIR) -> ProjectConfig:
    """Load a project configuration. Raises ConfigError with every error found."""
    path = Path(path)
    return project_from_data(_read_yaml(path), path, boards_dir)


def empty_project(
    board_name: str, path: Path, boards_dir: Path = BOARDS_DIR, mode: str = "agent", baud: int = DEFAULT_BAUD
) -> ProjectConfig:
    """A configuration with no devices, for open use of any pin, or for
    listening to the log of any firmware (mode "log"). path is where the TUI
    saves it. The file does not need to exist."""
    return project_from_data({"board": board_name, "mode": mode, "baud": baud}, Path(path), boards_dir)


def project_from_data(data: dict[str, Any], path: Path, boards_dir: Path = BOARDS_DIR) -> ProjectConfig:
    """Check the data of a project configuration file."""
    errors: list[str] = []
    warnings: list[str] = []

    if "board" not in data:
        raise ConfigError(str(path), ["board is required"])
    board = load_board(str(data["board"]), boards_dir)
    if board.name.startswith(GENERIC_PREFIX):
        warnings.append(f"generic board: only the facts of the {board.chip.title} chip are checked")
    elif not board.verified:
        warnings.append(f"board profile '{board.name}' is not verified against the hardware yet")

    mode = str(data.get("mode", "agent"))
    if mode not in MODES:
        errors.append(f"mode must be one of {', '.join(MODES)}")
    report_period_ms = int(data.get("report_period_ms", DEFAULT_REPORT_PERIOD_MS))
    if not 20 <= report_period_ms <= 10000:
        errors.append("report_period_ms must be 20 to 10000")

    devices: list[Device] = []
    for entry in data.get("devices") or []:
        device = _build_device(entry, board, errors)
        if device is not None:
            _check_device(device, board, errors, warnings)
            devices.append(device)
    if len(devices) > MAX_DEVICES:
        errors.append(f"at most {MAX_DEVICES} devices are allowed")
    seen_names: set[str] = set()
    seen_gpios: dict[int, str] = {}
    for device in devices:
        if device.name in seen_names:
            errors.append(f"device name '{device.name}' is used more than once")
        seen_names.add(device.name)
        for gpio in device.gpios:
            if gpio in seen_gpios:
                errors.append(f"devices '{seen_gpios[gpio]}' and '{device.name}' both use GPIO {gpio}")
            seen_gpios.setdefault(gpio, device.name)

    log_values: list[LogValue] = []
    for entry in data.get("log_values") or []:
        value = _build_log_value(entry, errors)
        if value is not None:
            log_values.append(value)
    if mode == "log" and devices:
        warnings.append("devices are ignored in log mode. Only log_values are shown")
    if mode == "log" and not log_values:
        warnings.append("log mode has no log_values. Only the Log page has data")

    if errors:
        raise ConfigError(str(path), errors)
    return ProjectConfig(
        path=path,
        board=board,
        mode=mode,
        port=data.get("port"),
        baud=int(data.get("baud", DEFAULT_BAUD)),
        report_period_ms=report_period_ms,
        devices=tuple(devices),
        log_values=tuple(log_values),
        warnings=tuple(warnings),
    )


def device_entry(device: Device) -> dict[str, Any]:
    """The YAML entry of a device, with the fields that matter for its type."""
    entry: dict[str, Any] = {"name": device.name, "type": device.type}
    if device.type in TWO_GPIO_KEYS:
        first, second = TWO_GPIO_KEYS[device.type]
        entry[first] = device.gpio
        entry[second] = device.gpio2
    else:
        entry["gpio"] = device.gpio
    mode = device.mode
    if mode == "digital_in":
        entry["pull"] = device.pull
        entry["invert"] = device.invert
    elif mode == "digital_out":
        entry["invert"] = device.invert
        entry["initial"] = int(device.initial)
    elif mode == "pwm":
        entry["freq_hz"] = device.freq_hz
        entry["initial"] = device.initial
    elif mode == "servo":
        entry["min_us"] = device.min_us
        entry["max_us"] = device.max_us
        entry["initial"] = device.initial
    elif mode == "i2c":
        entry["freq_hz"] = device.freq_hz
    elif mode == "uart":
        entry["baud"] = device.baud
    elif mode == "hx711":
        if device.gpio3 >= 0:
            entry[HX711_SECOND_KEY] = device.gpio3
        if device.gain != 128:
            entry["gain"] = device.gain
    if not device.is_output and mode not in ("i2c", "uart", "hx711"):
        if device.scale != 1.0:
            entry["scale"] = device.scale
        if device.offset != 0.0:
            entry["offset"] = device.offset
        if device.units != DEFAULT_UNITS.get(device.type, ""):
            entry["units"] = device.units
    if device.allow_reserved:
        entry["allow_reserved"] = True
    return entry


def project_data(config: ProjectConfig) -> dict[str, Any]:
    """The data of a configuration file for config."""
    data: dict[str, Any] = {"board": config.board.name, "mode": config.mode}
    if config.port:
        data["port"] = config.port
    if config.baud != DEFAULT_BAUD:
        data["baud"] = config.baud
    if config.report_period_ms != DEFAULT_REPORT_PERIOD_MS:
        data["report_period_ms"] = config.report_period_ms
    data["devices"] = [device_entry(device) for device in config.devices]
    if config.log_values:
        data["log_values"] = [
            {"name": value.name, "pattern": value.pattern.pattern, "units": value.units, "scale": value.scale, "offset": value.offset}
            for value in config.log_values
        ]
    return data


def with_device_entries(config: ProjectConfig, entries: list[dict[str, Any]], boards_dir: Path = BOARDS_DIR) -> ProjectConfig:
    """config with a new device list. Raises ConfigError if a device is not valid."""
    data = project_data(config)
    data["devices"] = entries
    return project_from_data(data, config.path, boards_dir)


def with_board(config: ProjectConfig, board_name: str, boards_dir: Path = BOARDS_DIR) -> ProjectConfig:
    data = project_data(config)
    data["board"] = board_name
    return project_from_data(data, config.path, boards_dir)


def dump_project(config: ProjectConfig) -> str:
    """The YAML text of config."""
    header = "# Saved by the bench TUI. Refer to docs/project_config.md.\n"
    return header + yaml.safe_dump(project_data(config), sort_keys=False, allow_unicode=True)


def watch_all_entries(board: Board, existing: tuple[Device, ...] = ()) -> list[dict[str, Any]]:
    """An input for each usable GPIO that no device uses yet: adc on an ADC1
    pin, digital_in on the others. Inputs only read, so this is safe whatever
    is connected. Board-reserved pins are left out."""
    used = {gpio for device in existing for gpio in device.gpios}
    blocked = board.never_usable()
    entries = []
    for gpio in sorted(board.pins):
        if gpio in used or gpio in blocked or gpio in board.reserved:
            continue
        device_type = "adc" if gpio in board.chip.adc1 else "digital_in"
        entries.append({"name": f"gpio{gpio}", "type": device_type, "gpio": gpio})
    return entries


def with_all_inputs(config: ProjectConfig, boards_dir: Path = BOARDS_DIR) -> ProjectConfig:
    """config with an input on each free GPIO."""
    entries = [device_entry(device) for device in config.devices]
    entries += watch_all_entries(config.board, config.devices)
    return with_device_entries(config, entries, boards_dir)


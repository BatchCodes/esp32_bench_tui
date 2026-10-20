"""The layout of the Board page: the header pins on the left and right of a
portrait board, and the order in which the cursor moves through them. No
terminal code here, so the tests need no Textual."""

from __future__ import annotations

import math
from dataclasses import dataclass

from bench import display
from bench.config import Board, Device

LEFT = "left"
RIGHT = "right"


@dataclass(frozen=True)
class Slot:
    """One header pin: a GPIO, or a power or control pin such as GND."""

    label: str
    gpio: int | None


@dataclass(frozen=True)
class Layout:
    left: tuple[Slot, ...]
    right: tuple[Slot, ...]
    # False when the board profile has no header data and the GPIOs are only
    # split into two columns.
    physical: bool

    @property
    def rows(self) -> int:
        return max(len(self.left), len(self.right))

    def side(self, name: str) -> tuple[Slot, ...]:
        return self.left if name == LEFT else self.right


@dataclass(frozen=True)
class Cursor:
    side: str
    row: int


def gpio_label(board: Board, gpio: int) -> str:
    label = board.labels.get(gpio)
    return f"IO{gpio}" if label is None else f"{label}/IO{gpio}"


def _slots(board: Board, items: tuple[int | str, ...]) -> tuple[Slot, ...]:
    return tuple(Slot(gpio_label(board, item), item) if isinstance(item, int) else Slot(str(item), None) for item in items)


def board_layout(board: Board) -> Layout:
    if board.header_left or board.header_right:
        return Layout(_slots(board, board.header_left), _slots(board, board.header_right), physical=True)
    gpios = sorted(board.pins)
    half = math.ceil(len(gpios) / 2)
    return Layout(_slots(board, tuple(gpios[:half])), _slots(board, tuple(gpios[half:])), physical=False)


def is_selectable(board: Board, slot: Slot) -> bool:
    """A GPIO that a device can use: on the headers and not reserved for the
    flash or the link. Board-reserved pins stay selectable, because
    allow_reserved can free them."""
    return slot.gpio is not None and slot.gpio in board.pins and slot.gpio not in board.never_usable()


def cursor_order(layout: Layout, board: Board) -> list[Cursor]:
    """The cursor stops, down the left side, then down the right side."""
    order = []
    for side in (LEFT, RIGHT):
        for row, slot in enumerate(layout.side(side)):
            if is_selectable(board, slot):
                order.append(Cursor(side, row))
    return order


def move(order: list[Cursor], cursor: Cursor | None, step: int) -> Cursor | None:
    """The next or previous stop, with wrap-around."""
    if not order:
        return None
    if cursor not in order:
        return order[0]
    return order[(order.index(cursor) + step) % len(order)]


def devices_by_gpio(devices: tuple[Device, ...]) -> dict[int, tuple[Device, str]]:
    """The device and the role (gpio, sda, scl, tx, rx) of each used GPIO."""
    used = {}
    for device in devices:
        for gpio, role, _output in device.gpio_roles():
            used[gpio] = (device, role)
    return used


MODE_CODES = {
    "digital_in": "DI",
    "button": "DI",
    "digital_out": "DO",
    "led": "DO",
    "adc": "ADC",
    "pwm": "PWM",
    "servo": "SRV",
    "counter": "CNT",
    "i2c": "I2C",
    "uart": "UART",
    "ds18b20": "1W",
    "dht11": "DHT",
    "dht22": "DHT",
    "hx711": "HX",
}


def mode_code(device: Device) -> str:
    """The short mode code of a device on the Board page, for example DI or PWM."""
    return MODE_CODES.get(device.type, device.type[:4].upper())


def pin_value_text(
    device: Device,
    role: str,
    value: float | str | None,
    humidity: float | None = None,
    rate: float | None = None,
) -> str:
    """The value text on the Board page: 1 or 0 for digital pins, the value
    in its units for the others."""
    if device.type == "hx711":
        return "CLK" if role == "clock" else ""
    if device.type in ("i2c", "uart"):
        return role
    if device.type == "counter":
        return display.format_rate(rate)
    if device.mode in ("digital_in", "digital_out"):
        if not isinstance(value, float) or math.isnan(value):
            return "—"
        return "1" if value >= 0.5 else "0"
    if device.mode in ("dht11", "dht22"):
        return display.format_sensor(device, value, humidity)
    return display.format_value(device, value)


def pin_command_for(board: Board, gpio: int, device: Device | None) -> str:
    """The text that the pin prompt starts with for a GPIO."""
    if device is not None and device.type not in ("i2c", "uart", "hx711"):
        type_word = {"digital_in": "in", "digital_out": "out"}.get(device.type, device.type)
        return f"{type_word} {gpio} name={device.name}"
    if gpio in board.chip.input_only:
        return f"in {gpio}"
    return f"out {gpio}"


class SwitchError(ValueError):
    """The pin cannot change its mode with the tab key."""


MODE_NAMES = {
    "adc": "analog in",
    "pwm": "analog out (PWM)",
    "digital_in": "digital in",
    "digital_out": "digital out",
}
# The tab cycle of a device type that is not in MODE_NAMES continues from the
# mode that it is closest to.
NEAREST_MODE = {"led": "digital_out", "button": "digital_in", "counter": "digital_in", "servo": "pwm"}


def pin_modes(board: Board, gpio: int) -> list[str]:
    """The modes that the tab key cycles through on a GPIO, in order. An ADC
    pin that can output: analog in, analog out, digital in, digital out.
    Another output pin: digital in, digital out. An input-only ADC pin:
    analog in, digital in."""
    adc = gpio in board.chip.adc1
    output = gpio not in board.chip.input_only
    if adc and output:
        return ["adc", "pwm", "digital_in", "digital_out"]
    if adc:
        return ["adc", "digital_in"]
    if output:
        return ["digital_in", "digital_out"]
    return ["digital_in"]


def input_entry(board: Board, gpio: int, name: str) -> dict:
    """An input on a GPIO: adc on an ADC1 pin, digital_in on the others."""
    return {"name": name, "type": "adc" if gpio in board.chip.adc1 else "digital_in", "gpio": gpio}


def next_mode_entry(board: Board, gpio: int, device: Device | None) -> dict:
    """The device entry for the next mode in the tab cycle of the GPIO. A free
    pin starts at the first mode. An output starts at 0."""
    modes = pin_modes(board, gpio)
    if device is None:
        mode = modes[0]
        name = f"gpio{gpio}"
    else:
        if device.type in ("i2c", "uart", "hx711") or device.mode in ("ds18b20", "dht11", "dht22"):
            raise SwitchError(f"{device.name} is a {device.type} device. Tab changes only GPIO inputs and outputs")
        current = NEAREST_MODE.get(device.type, device.type)
        if current in modes:
            mode = modes[(modes.index(current) + 1) % len(modes)]
        else:
            mode = modes[0]
        name = device.name
    if len(modes) == 1 and device is not None:
        raise SwitchError(f"GPIO {gpio} can only be a digital input")
    entry: dict = {"name": name, "type": mode, "gpio": gpio}
    if mode in ("digital_out", "pwm"):
        entry["initial"] = 0
    return entry

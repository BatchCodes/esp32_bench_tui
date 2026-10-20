"""Bus page helpers that need no terminal: the command line parser and the
names of common I2C chips."""

from __future__ import annotations

from dataclasses import dataclass

# Common chips at each 7-bit address. Several chips share an address, so the
# name is a hint, not an identification. Read the chip ID register to be sure.
I2C_CHIPS: dict[int, str] = {
    0x0D: "QMC5883L compass",
    0x1E: "HMC5883L compass",
    0x20: "PCF8574 / MCP23017 I/O expander",
    0x21: "PCF8574 / MCP23017 I/O expander",
    0x22: "PCF8574 / MCP23017 I/O expander",
    0x23: "BH1750 light / PCF8574",
    0x24: "PCF8574 / MCP23017 I/O expander",
    0x25: "PCF8574 / MCP23017 I/O expander",
    0x26: "PCF8574 / MCP23017 I/O expander",
    0x27: "PCF8574 LCD backpack / MCP23017",
    0x29: "VL53L0X distance / TSL2591 light",
    0x38: "AHT10 / AHT20 humidity",
    0x39: "APDS-9960 gesture / TSL2561 light",
    0x3C: "SSD1306 / SH1106 OLED",
    0x3D: "SSD1306 / SH1106 OLED",
    0x40: "INA219 / HTU21D / SHT21 / PCA9685",
    0x41: "INA219 / PCA9685",
    0x44: "SHT3x humidity",
    0x45: "SHT3x humidity",
    0x48: "ADS1115 ADC / TMP102",
    0x49: "ADS1115 ADC / TMP102",
    0x4A: "ADS1115 ADC",
    0x4B: "ADS1115 ADC",
    0x50: "AT24C EEPROM",
    0x51: "AT24C EEPROM / PCF8563 RTC",
    0x53: "ADXL345 accelerometer",
    0x57: "MAX30102 pulse / AT24C EEPROM",
    0x5A: "MLX90614 IR / CCS811",
    0x5B: "CCS811 air quality",
    0x5C: "AM2320 humidity / BH1750",
    0x60: "MPL3115A2 / Si1145 / ATECC508",
    0x61: "SCD30 CO2",
    0x62: "SCD40 / SCD41 CO2",
    0x68: "MPU6050 IMU / DS3231 / DS1307 RTC",
    0x69: "MPU6050 IMU (AD0 high)",
    0x76: "BME280 / BMP280 / BME680",
    0x77: "BME280 / BMP280 / BME680 / BMP180",
}

DEFAULT_READ_LENGTH = 1
MAX_I2C_TRANSFER = 32
MAX_UART_SEND = 256

HELP = (
    "scan [bus] · read <addr> [reg] [len] · write <addr> <reg|-> <hex> · "
    "send [uart] <text>  (numbers: 0x76 or 118)"
)


class CommandError(ValueError):
    """A Bus page command cannot be read."""


@dataclass(frozen=True)
class BusCommand:
    action: str
    target: str
    address: int | None = None
    register: int | None = None
    length: int = DEFAULT_READ_LENGTH
    data: bytes = b""


def chip_name(address: int) -> str:
    return I2C_CHIPS.get(address, "unknown")


def _number(text: str, low: int, high: int, what: str) -> int:
    try:
        value = int(text, 0)
    except ValueError as error:
        raise CommandError(f"{what} '{text}' is not a number") from error
    if not low <= value <= high:
        raise CommandError(f"{what} must be {low:#04x} to {high:#04x}")
    return value


def _pick_target(words: list[str], names: list[str], kind: str) -> str:
    """Takes a bus or UART name from the front of words, or the only one."""
    if words and words[0] in names:
        return words.pop(0)
    if not names:
        raise CommandError(f"the configuration has no {kind} device")
    if len(names) > 1:
        raise CommandError(f"give the {kind} name: {', '.join(names)}")
    return names[0]


def parse_command(text: str, i2c_names: list[str], uart_names: list[str]) -> BusCommand:
    """Reads one command line of the Bus page."""
    words = text.split()
    if not words:
        raise CommandError("enter a command. " + HELP)
    action = words.pop(0).lower()
    if action == "send":
        target = _pick_target(words, uart_names, "uart")
        message = " ".join(words)
        data = (message + "\r\n").encode()
        if len(data) > MAX_UART_SEND:
            raise CommandError(f"at most {MAX_UART_SEND} bytes")
        return BusCommand(action="send", target=target, data=data)
    if action not in ("scan", "read", "write"):
        raise CommandError(f"unknown command '{action}'. " + HELP)
    target = _pick_target(words, i2c_names, "i2c")
    if action == "scan":
        return BusCommand(action="scan", target=target)
    if not words:
        raise CommandError(f"{action} needs an address")
    address = _number(words.pop(0), 0x08, 0x77, "address")
    if action == "read":
        register = _number(words.pop(0), 0, 0xFF, "register") if words else None
        length = _number(words.pop(0), 1, MAX_I2C_TRANSFER, "length") if words else DEFAULT_READ_LENGTH
        return BusCommand(action="read", target=target, address=address, register=register, length=length)
    if len(words) < 2:
        raise CommandError("write needs <addr> <reg|-> <hex>")
    register_text = words.pop(0)
    register = None if register_text == "-" else _number(register_text, 0, 0xFF, "register")
    hex_text = "".join(words).removeprefix("0x")
    try:
        data = bytes.fromhex(hex_text)
    except ValueError as error:
        raise CommandError(f"'{hex_text}' is not hex bytes") from error
    if not data or len(data) > MAX_I2C_TRANSFER:
        raise CommandError(f"write 1 to {MAX_I2C_TRANSFER} bytes")
    return BusCommand(action="write", target=target, address=address, register=register, data=data)

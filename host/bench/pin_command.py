"""The pin command of the TUI: add a device to any free GPIO while the TUI runs.

Syntax: <type> <gpio> [<gpio2>] [key=value ...]

Examples: "out 4", "in 34", "in 15 pull=up", "adc 32", "pwm 13 freq=5000",
"servo 18", "i2c 21 22", "uart 17 16 baud=115200", "dht22 5 name=room".
"""

from __future__ import annotations

from typing import Any

from bench.config import DEVICE_TYPES, TWO_GPIO_KEYS

ALIASES = {
    "in": "digital_in",
    "input": "digital_in",
    "out": "digital_out",
    "output": "digital_out",
    "dht": "dht22",
}
KEY_ALIASES = {"freq": "freq_hz", "min": "min_us", "max": "max_us"}
INT_KEYS = ("freq_hz", "min_us", "max_us", "baud", "gain")
FLOAT_KEYS = ("initial", "scale", "offset")
BOOL_KEYS = ("invert", "allow_reserved")
TEXT_KEYS = ("name", "pull", "units")
SIMPLE_TYPES = ("digital_in", "digital_out", "adc", "pwm", "servo", "led", "button", "counter")

HELP = (
    "<type> <gpio> [gpio2] [key=value]. Types: in, out, adc, pwm, servo, led, button, counter, "
    "i2c (sda scl), uart (tx rx), hx711 (clock data [data2]), ds18b20, dht11, dht22. "
    "Keys: name, pull, invert, initial, freq, baud, gain, scale, units"
)


class PinCommandError(ValueError):
    """A pin command cannot be read."""


def _gpio(text: str) -> int:
    try:
        gpio = int(text, 0)
    except ValueError as error:
        raise PinCommandError(f"'{text}' is not a GPIO number") from error
    if not 0 <= gpio <= 63:
        raise PinCommandError(f"GPIO {gpio} is out of range")
    return gpio


def _value(key: str, text: str) -> Any:
    try:
        if key in INT_KEYS:
            return int(text, 0)
        if key in FLOAT_KEYS:
            return float(text)
    except ValueError as error:
        raise PinCommandError(f"{key} '{text}' is not a number") from error
    if key in BOOL_KEYS:
        lowered = text.lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
        raise PinCommandError(f"{key} must be true or false")
    return text


def default_name(device_type: str, gpio: int) -> str:
    if device_type in SIMPLE_TYPES:
        return f"gpio{gpio}"
    return f"{device_type}_{gpio}"


def parse_pin_command(text: str) -> dict[str, Any]:
    """The device entry for one pin command, in the form of a YAML device."""
    words = text.split()
    if len(words) < 2:
        raise PinCommandError("enter a type and a GPIO. " + HELP)
    device_type = ALIASES.get(words[0].lower(), words[0].lower())
    if device_type not in DEVICE_TYPES:
        raise PinCommandError(f"unknown type '{words[0]}'. " + HELP)
    rest = words[1:]
    entry: dict[str, Any] = {"type": device_type}
    if device_type in TWO_GPIO_KEYS:
        first, second = TWO_GPIO_KEYS[device_type]
        if len(rest) < 2 or "=" in rest[1]:
            raise PinCommandError(f"{device_type} needs two GPIOs: {first} {second}")
        entry[first] = _gpio(rest[0])
        entry[second] = _gpio(rest[1])
        rest = rest[2:]
        if device_type == "hx711" and rest and "=" not in rest[0]:
            entry["data2"] = _gpio(rest[0])
            rest = rest[1:]
    else:
        entry["gpio"] = _gpio(rest[0])
        rest = rest[1:]
    for word in rest:
        if "=" not in word:
            raise PinCommandError(f"'{word}' is not key=value")
        key, value = word.split("=", 1)
        key = KEY_ALIASES.get(key.lower(), key.lower())
        if key not in INT_KEYS + FLOAT_KEYS + BOOL_KEYS + TEXT_KEYS:
            raise PinCommandError(f"unknown key '{key}'")
        entry[key] = _value(key, value)
    first_gpio = entry.get("gpio", entry.get(TWO_GPIO_KEYS.get(device_type, ("gpio",))[0]))
    entry.setdefault("name", default_name(device_type, first_gpio))
    return entry


def entry_gpios(entry: dict[str, Any]) -> set[int]:
    """The GPIOs of a device entry."""
    keys = TWO_GPIO_KEYS.get(entry["type"], ("gpio",)) + ("data2",)
    return {int(entry[key]) for key in keys if key in entry}


def replace_entry(entries: list[dict[str, Any]], entry: dict[str, Any]) -> list[dict[str, Any]]:
    """entries with entry in the place of the first entry that has the same
    name or shares a GPIO with it. Other such entries are removed. A new entry
    goes at the end. So a changed pin keeps its place in the list."""
    gpios = entry_gpios(entry)
    result: list[dict[str, Any]] = []
    placed = False
    for item in entries:
        if item["name"] == entry["name"] or entry_gpios(item) & gpios:
            if not placed:
                result.append(entry)
                placed = True
            continue
        result.append(item)
    if not placed:
        result.append(entry)
    return result


"""Wi-Fi and Bluetooth page helpers that need no terminal."""

from __future__ import annotations

# Bluetooth SIG company identifiers of common devices. Source: Bluetooth SIG
# "Assigned Numbers", company identifiers.
COMPANIES: dict[int, str] = {
    0x0006: "Microsoft",
    0x004C: "Apple",
    0x0059: "Nordic Semiconductor",
    0x0075: "Samsung",
    0x0087: "Garmin",
    0x00E0: "Google",
    0x0157: "Huami",
    0x0171: "Amazon",
    0x02E5: "Espressif",
    0x038F: "Xiaomi",
    0x0499: "Ruuvi Innovations",
}

RSSI_FLOOR = -100
RSSI_CEILING = -30
BAR_CHARS = " ▏▎▍▌▋▊▉█"
WIFI_SCAN_PERIOD_MS = 5000


def company_name(company_id: int) -> str:
    if company_id < 0:
        return ""
    return COMPANIES.get(company_id, f"0x{company_id:04x}")


def bar(fraction: float, width: int) -> str:
    """A horizontal bar of width characters, filled to fraction (0 to 1)."""
    fraction = min(1.0, max(0.0, fraction))
    eighths = round(fraction * width * 8)
    full, rest = divmod(eighths, 8)
    text = "█" * full
    if full < width and rest:
        text += BAR_CHARS[rest]
    return text.ljust(width)


def rssi_fraction(rssi: int) -> float:
    return (rssi - RSSI_FLOOR) / (RSSI_CEILING - RSSI_FLOOR)


def rssi_style(rssi: int) -> str:
    if rssi >= -60:
        return "green"
    if rssi >= -75:
        return "yellow"
    return "red"


def matches(name: str, address: str, text: str) -> bool:
    """True when the filter text is empty, or is part of the name or address."""
    text = text.strip().lower()
    return not text or text in name.lower() or text in address.lower()


# 16-bit service UUIDs. Source: Bluetooth SIG "Assigned Numbers", GATT
# services and member service UUIDs.
SERVICES: dict[int, str] = {
    0x1800: "Generic Access",
    0x180A: "Device Information",
    0x180D: "Heart Rate",
    0x180F: "Battery",
    0x1809: "Health Thermometer",
    0x1812: "Human Interface Device",
    0x1816: "Cycling Speed and Cadence",
    0x1818: "Cycling Power",
    0x181A: "Environmental Sensing",
    0x1826: "Fitness Machine",
    0xFCF1: "Google",
    0xFD5A: "Samsung",
    0xFD6F: "Exposure Notification",
    0xFE03: "Amazon",
    0xFE07: "Sonos",
    0xFE2C: "Google Fast Pair",
    0xFE50: "Google",
    0xFE95: "Xiaomi",
    0xFE9F: "Google",
    0xFEAA: "Eddystone beacon",
    0xFEAF: "Nest",
    0xFEE0: "Huami (Amazfit, Mi Band)",
    0xFEED: "Tile tracker",
}

# GAP appearance categories (value >> 6). Source: Bluetooth SIG "Assigned
# Numbers", appearance values.
APPEARANCE_CATEGORIES: dict[int, str] = {
    1: "phone",
    2: "computer",
    3: "watch",
    4: "clock",
    5: "display",
    6: "remote control",
    7: "eye glasses",
    8: "tag",
    9: "keyring",
    10: "media player",
    11: "barcode scanner",
    12: "thermometer",
    13: "heart rate sensor",
    14: "blood pressure",
    15: "human interface device",
    16: "glucose meter",
    17: "running and walking sensor",
    18: "cycling sensor",
    21: "light source",
    26: "audio sink",
    37: "earbud",
}

# Apple continuity message types: the third byte of Apple manufacturer data.
APPLE_TYPES: dict[int, str] = {
    0x02: "iBeacon",
    0x05: "AirDrop",
    0x07: "AirPods",
    0x09: "AirPlay target",
    0x0C: "Handoff",
    0x0F: "Nearby Action",
    0x10: "Nearby Info (iPhone, iPad, Mac)",
    0x12: "Find My (AirTag, offline finding)",
}

ADDRESS_TYPES = {0: "public", 1: "random", 2: "public identity", 3: "random identity"}
APPLE = 0x004C
MICROSOFT = 0x0006


def service_name(uuid: int) -> str:
    return SERVICES.get(uuid, f"0x{uuid:04x}")


def appearance_name(value: int | None) -> str:
    if value is None:
        return ""
    return APPEARANCE_CATEGORIES.get(value >> 6, f"0x{value:04x}")


def address_kind(address: str, address_type: int) -> str:
    """The kind of a BLE address. A random address of a phone changes every
    few minutes, so the same phone can show as more than one device."""
    kind = ADDRESS_TYPES.get(address_type, str(address_type))
    if address_type != 1:
        return kind
    try:
        top_bits = int(address.split(":")[0], 16) >> 6
    except (ValueError, IndexError):
        return kind
    return {0b11: "random static", 0b01: "random private, changes", 0b00: "random, not resolvable"}.get(top_bits, kind)


def manufacturer_hint(company_id: int, data: bytes) -> str:
    """What the manufacturer data says, for the common formats."""
    if company_id == APPLE and len(data) >= 3:
        hint = APPLE_TYPES.get(data[2], f"Apple type 0x{data[2]:02x}")
        if data[2] == 0x02 and len(data) >= 24:
            uuid = data[4:20].hex()
            major = int.from_bytes(data[20:22], "big")
            minor = int.from_bytes(data[22:24], "big")
            hint += f" {uuid[:8]}-{uuid[8:12]}-{uuid[12:16]}-{uuid[16:20]}-{uuid[20:]} major {major} minor {minor}"
        return hint
    if company_id == MICROSOFT and len(data) >= 3 and data[2] == 0x01:
        return "Microsoft beacon (Windows device, Swift Pair)"
    return ""


def device_hint(device) -> str:
    """A short description for a device with no name: what its advertisement
    says, or the company."""
    hint = manufacturer_hint(device.company_id, device.manufacturer)
    if hint:
        return hint.split(" ", 2)[0] if hint.startswith("iBeacon") else hint
    if device.services:
        return service_name(device.services[0])
    appearance = appearance_name(device.appearance)
    if appearance:
        return appearance
    return company_name(device.company_id)


def phy_text(phy: str) -> str:
    """The 802.11 modes as text, for example b/g/n/ax."""
    names = {"b": "b", "g": "g", "n": "n", "x": "ax", "l": "LR"}
    return "/".join(names.get(letter, letter) for letter in phy)


def ap_width(second: str) -> str:
    return "20 MHz" if second == "none" else f"40 MHz (second channel {second})"


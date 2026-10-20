"""Messages of the bench agent wire protocol. Refer to docs/protocol.md."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = 6
MESSAGE_PREFIX = '{"type":"'
MAX_LINE_LENGTH = 6144


@dataclass(frozen=True)
class Hello:
    seq: int
    protocol: int
    agent: str
    chip: str
    revision: int
    cores: int
    mac: str
    flash_mb: int
    free_heap: int


@dataclass(frozen=True)
class ConfigAck:
    seq: int
    ok: bool
    errors: dict[str, str]


@dataclass(frozen=True)
class Hx711State:
    """The state of an HX711 device. The raw value of channel 1 is in
    State.values."""

    raw2: float | None
    ready: tuple[bool, ...]
    timeouts: tuple[int, ...]
    reads: int


@dataclass(frozen=True)
class State:
    uptime_ms: int
    values: dict[str, float]
    edges: dict[str, int]
    humidity: dict[str, float] = field(default_factory=dict)
    hx711: dict[str, Hx711State] = field(default_factory=dict)


@dataclass(frozen=True)
class I2cScanResult:
    seq: int
    id: str
    addresses: tuple[int, ...]


@dataclass(frozen=True)
class I2cData:
    seq: int
    id: str
    address: int
    register: int | None
    data: bytes


@dataclass(frozen=True)
class UartData:
    id: str
    data: bytes


@dataclass(frozen=True)
class WifiAp:
    ssid: str
    bssid: str
    channel: int
    rssi: int
    auth: str
    # The 802.11 modes as letters: b, g, n, x (ax) and l (long range).
    phy: str = ""
    wps: bool = False
    second: str = "none"


@dataclass(frozen=True)
class WifiScanResult:
    aps: tuple[WifiAp, ...]


@dataclass(frozen=True)
class WifiStatus:
    state: str
    ssid: str
    ip: str
    rssi: int
    channel: int
    reason: str


@dataclass(frozen=True)
class WifiChannels:
    period_ms: int
    counts: tuple[int, ...]


@dataclass(frozen=True)
class BleDevice:
    address: str
    name: str
    rssi: int
    company_id: int
    age_ms: int
    address_type: int = 0
    connectable: bool = False
    adv_count: int = 0
    tx_power: int | None = None
    appearance: int | None = None
    services: tuple[int, ...] = ()
    manufacturer: bytes = b""


@dataclass(frozen=True)
class BleDevices:
    devices: tuple[BleDevice, ...]


@dataclass(frozen=True)
class Ack:
    seq: int


@dataclass(frozen=True)
class Error:
    seq: int
    error: str


@dataclass(frozen=True)
class Pong:
    seq: int
    uptime_ms: int
    free_heap: int


@dataclass(frozen=True)
class Event:
    event: str


@dataclass(frozen=True)
class LogLine:
    text: str


@dataclass(frozen=True)
class BadMessage:
    """A line that starts like a message but cannot be read."""

    text: str
    reason: str


AgentMessage = (
    Hello
    | ConfigAck
    | State
    | Ack
    | Error
    | Pong
    | Event
    | I2cScanResult
    | I2cData
    | UartData
    | WifiScanResult
    | WifiStatus
    | WifiChannels
    | BleDevices
)


@dataclass
class SeqCounter:
    value: int = field(default=0)

    def next(self) -> int:
        self.value = self.value + 1 if self.value < 0x7FFFFFFF else 1
        return self.value


def is_message_line(text: str) -> bool:
    return text.startswith(MESSAGE_PREFIX)


def encode(message_type: str, seq: int, **fields: Any) -> bytes:
    """One host message line. The type is always the first key."""
    body: dict[str, Any] = {"type": message_type, "seq": seq}
    body.update(fields)
    return (json.dumps(body, separators=(",", ":")) + "\n").encode()


def _number(value: Any) -> float:
    """A JSON number, or NaN for null (a failed sensor read)."""
    return float("nan") if value is None else float(value)


def _parse_body(body: dict[str, Any]) -> AgentMessage:
    message_type = body["type"]
    seq = int(body.get("seq", 0))
    if message_type == "hello":
        return Hello(
            seq=seq,
            protocol=int(body["protocol"]),
            agent=str(body.get("agent", "")),
            chip=str(body.get("chip", "")),
            revision=int(body.get("revision", 0)),
            cores=int(body.get("cores", 0)),
            mac=str(body.get("mac", "")),
            flash_mb=int(body.get("flash_mb", 0)),
            free_heap=int(body.get("free_heap", 0)),
        )
    if message_type == "config_ack":
        errors = {str(entry.get("id", "")): str(entry.get("error", "")) for entry in body.get("errors", [])}
        return ConfigAck(seq=seq, ok=bool(body.get("ok", not errors)), errors=errors)
    if message_type == "state":
        return State(
            uptime_ms=int(body.get("uptime_ms", 0)),
            values={str(key): _number(value) for key, value in body.get("values", {}).items()},
            edges={str(key): int(value) for key, value in body.get("edges", {}).items()},
            humidity={str(key): _number(value) for key, value in body.get("humidity", {}).items()},
            hx711={
                str(key): Hx711State(
                    raw2=None if "raw2" not in item else _number(item["raw2"]),
                    ready=tuple(bool(flag) for flag in item.get("ready", [])),
                    timeouts=tuple(int(count) for count in item.get("timeouts", [])),
                    reads=int(item.get("reads", 0)),
                )
                for key, item in body.get("hx711", {}).items()
            },
        )
    if message_type == "i2c_scan_result":
        return I2cScanResult(seq=seq, id=str(body["id"]), addresses=tuple(int(item) for item in body.get("addresses", [])))
    if message_type == "i2c_data":
        register = body.get("register")
        return I2cData(
            seq=seq,
            id=str(body["id"]),
            address=int(body["address"]),
            register=None if register is None else int(register),
            data=bytes.fromhex(str(body.get("data", ""))),
        )
    if message_type == "uart_data":
        return UartData(id=str(body["id"]), data=bytes.fromhex(str(body.get("data", ""))))
    if message_type == "wifi_scan_result":
        return WifiScanResult(
            aps=tuple(
                WifiAp(
                    ssid=str(item.get("ssid", "")),
                    bssid=str(item.get("bssid", "")),
                    channel=int(item.get("channel", 0)),
                    rssi=int(item.get("rssi", 0)),
                    auth=str(item.get("auth", "")),
                    phy=str(item.get("phy", "")),
                    wps=bool(item.get("wps", False)),
                    second=str(item.get("second", "none")),
                )
                for item in body.get("aps", [])
            )
        )
    if message_type == "wifi_status":
        return WifiStatus(
            state=str(body.get("state", "off")),
            ssid=str(body.get("ssid", "")),
            ip=str(body.get("ip", "")),
            rssi=int(body.get("rssi", 0)),
            channel=int(body.get("channel", 0)),
            reason=str(body.get("reason", "")),
        )
    if message_type == "wifi_channels":
        return WifiChannels(period_ms=int(body.get("period_ms", 0)), counts=tuple(int(item) for item in body.get("counts", [])))
    if message_type == "ble_devices":
        return BleDevices(
            devices=tuple(
                BleDevice(
                    address=str(item.get("address", "")),
                    name=str(item.get("name", "")),
                    rssi=int(item.get("rssi", 0)),
                    company_id=int(item.get("company_id", -1)),
                    age_ms=int(item.get("age_ms", 0)),
                    address_type=int(item.get("address_type", 0)),
                    connectable=bool(item.get("connectable", False)),
                    adv_count=int(item.get("adv_count", 0)),
                    tx_power=None if item.get("tx_power") is None else int(item["tx_power"]),
                    appearance=None if item.get("appearance") is None else int(item["appearance"]),
                    services=tuple(int(uuid) for uuid in item.get("services", [])),
                    manufacturer=bytes.fromhex(str(item.get("manufacturer", ""))),
                )
                for item in body.get("devices", [])
            )
        )
    if message_type == "ack":
        return Ack(seq=seq)
    if message_type == "error":
        return Error(seq=seq, error=str(body.get("error", "")))
    if message_type == "pong":
        return Pong(seq=seq, uptime_ms=int(body.get("uptime_ms", 0)), free_heap=int(body.get("free_heap", 0)))
    if message_type == "event":
        return Event(event=str(body.get("event", "")))
    raise ValueError(f"unknown message type '{message_type}'")


def parse_line(text: str) -> AgentMessage | LogLine | BadMessage:
    """Turns one line from the board into a message or a log line."""
    text = text.rstrip("\r\n")
    if not is_message_line(text):
        return LogLine(text)
    try:
        body = json.loads(text)
        if not isinstance(body, dict):
            raise ValueError("not an object")
        return _parse_body(body)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        return BadMessage(text=text, reason=str(error))

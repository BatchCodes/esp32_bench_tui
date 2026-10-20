"""Links between the host tool and a board.

A link owns a transport (a serial port, or a simulated agent) and a worker
thread. The worker reads lines from the board and keeps a LinkState. The TUI
takes a copy of the state with snapshot() at each render tick, so it never
waits for the board.

- AgentLink talks to the bench agent firmware: handshake, config, set, ping.
- LogLink only reads the log output of any firmware and applies regex rules.
"""

from __future__ import annotations

import copy
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from bench import protocol
from bench.config import LogValue, ProjectConfig

SERIAL_BY_ID_DIR = Path("/dev/serial/by-id")
READ_TIMEOUT_S = 0.05
PING_PERIOD_S = 0.5
HELLO_RETRY_S = 1.0
REOPEN_DELAY_S = 1.0
RESET_PULSE_S = 0.1
LOG_LINES = 500
HISTORY_SAMPLES = 600
RATE_WINDOW_S = 2.0
EDGE_RATE_WINDOW_S = 2.0
UART_LINES = 200
I2C_RESULTS = 20
RSSI_SAMPLES = 120
# How long the host keeps an access point or a BLE device after the last
# scan that saw it.
FORGET_AFTER_S = 60.0


@dataclass
class Seen:
    """An access point or a BLE device, with its RSSI history."""

    item: object
    first_seen: float
    last_seen: float
    rssi: list[float] = field(default_factory=list)


class LinkError(Exception):
    """The link cannot open its transport."""


class Transport(Protocol):
    name: str

    def open(self) -> None: ...

    def close(self) -> None: ...

    def read_line(self, timeout: float) -> str | None: ...

    def write(self, data: bytes) -> None: ...

    def reset_board(self) -> None: ...


def resolve_port(port: str | None) -> str:
    """The given port, or the only device in /dev/serial/by-id."""
    if port:
        return port
    if not SERIAL_BY_ID_DIR.is_dir():
        raise LinkError(f"no serial device in {SERIAL_BY_ID_DIR}. Connect the board, or give --port")
    devices = sorted(SERIAL_BY_ID_DIR.iterdir())
    if len(devices) != 1:
        raise LinkError(f"found {len(devices)} serial devices in {SERIAL_BY_ID_DIR}. Give --port")
    return str(devices[0].resolve())


class SerialTransport:
    """A serial port, read as text lines."""

    def __init__(self, port: str, baud: int) -> None:
        self.name = port
        self.baud = baud
        self._serial = None
        self._buffer = bytearray()

    def open(self) -> None:
        import serial

        port = serial.Serial()
        port.port = self.name
        port.baudrate = self.baud
        port.timeout = 0
        # Both lines released before open, so the USB-UART auto-reset circuit
        # of most ESP32 boards does not reset the board.
        port.dtr = False
        port.rts = False
        # Two programs that read one port each get part of the data, and
        # pyserial then reports "readiness to read but returned no data".
        # An exclusive open makes the second program fail at once instead.
        port.exclusive = True
        try:
            port.open()
        except serial.SerialException as error:
            if "lock" in str(error).lower() or getattr(error, "errno", None) == 11:
                raise LinkError(f"{self.name} is in use by another program, for example idf.py monitor or another bench") from error
            raise LinkError(str(error)) from error
        self._serial = port
        self._buffer.clear()

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def read_line(self, timeout: float) -> str | None:
        import serial

        if self._serial is None:
            raise LinkError("port is not open")
        deadline = time.monotonic() + timeout
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                line = bytes(self._buffer[:newline])
                del self._buffer[: newline + 1]
                return line.decode("utf-8", errors="replace").rstrip("\r")
            try:
                waiting = self._serial.in_waiting
                if waiting:
                    self._buffer.extend(self._serial.read(waiting))
                    continue
            except (serial.SerialException, OSError) as error:
                raise LinkError(str(error)) from error
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.005)

    def write(self, data: bytes) -> None:
        import serial

        if self._serial is None:
            raise LinkError("port is not open")
        try:
            self._serial.write(data)
        except (serial.SerialException, OSError) as error:
            raise LinkError(str(error)) from error

    def reset_board(self) -> None:
        """Pulses EN low through RTS, the same as esptool."""
        if self._serial is None:
            return
        self._serial.dtr = False
        self._serial.rts = True
        time.sleep(RESET_PULSE_S)
        self._serial.rts = False


@dataclass(frozen=True)
class RadioSettings:
    wifi_scan_ms: int = 0
    sniffer: bool = False
    ble_scan: bool = False
    # An active scan asks each device for its scan response, which often has
    # the name. A passive scan only listens.
    ble_active: bool = True

    @property
    def any_on(self) -> bool:
        return self.wifi_scan_ms > 0 or self.sniffer or self.ble_scan


@dataclass
class LinkState:
    mode: str = "agent"
    port: str = ""
    connected: bool = False
    status: str = "starting"
    hello: protocol.Hello | None = None
    configured: bool = False
    config_errors: dict[str, str] = field(default_factory=dict)
    values: dict[str, float | str] = field(default_factory=dict)
    edges: dict[str, int] = field(default_factory=dict)
    edge_rates: dict[str, float] = field(default_factory=dict)
    humidity: dict[str, float] = field(default_factory=dict)
    hx711: dict[str, protocol.Hx711State] = field(default_factory=dict)
    i2c_scans: dict[str, tuple[int, ...]] = field(default_factory=dict)
    i2c_results: list[str] = field(default_factory=list)
    uart_lines: dict[str, list[str]] = field(default_factory=dict)
    uart_total: dict[str, int] = field(default_factory=dict)
    radio: RadioSettings = field(default_factory=RadioSettings)
    wifi_aps: tuple[protocol.WifiAp, ...] = ()
    wifi_scan_time: float = 0.0
    wifi_status: protocol.WifiStatus | None = None
    wifi_rssi: list[float] = field(default_factory=list)
    wifi_channels: tuple[int, ...] = ()
    wifi_channels_time: float = 0.0
    ble_devices: tuple[protocol.BleDevice, ...] = ()
    ble_time: float = 0.0
    # By BSSID and by address: everything seen in the last 60 s.
    wifi_seen: dict[str, Seen] = field(default_factory=dict)
    ble_seen: dict[str, Seen] = field(default_factory=dict)
    updated: dict[str, float] = field(default_factory=dict)
    history: dict[str, list[float]] = field(default_factory=dict)
    uptime_ms: int = 0
    free_heap: int = 0
    log: list[str] = field(default_factory=list)
    log_total: int = 0
    results: dict[int, str | None] = field(default_factory=dict)
    last_rx: float = 0.0
    rx_messages: int = 0
    rx_log_lines: int = 0
    bad_lines: int = 0
    errors: int = 0
    watchdog_events: int = 0
    message_rate: float = 0.0


class BaseLink:
    """The worker thread and the shared state of a link."""

    can_control = False

    def __init__(self, transport: Transport, config: ProjectConfig) -> None:
        self.transport = transport
        self.config = config
        self._state = LinkState(mode=config.mode, port=transport.name)
        self._history: dict[str, deque[float]] = {}
        self._log: deque[str] = deque(maxlen=LOG_LINES)
        self._edge_samples: dict[str, deque[tuple[float, int]]] = {}
        self._i2c_results: deque[str] = deque(maxlen=I2C_RESULTS)
        self._uart_lines: dict[str, deque[str]] = {}
        self._uart_partial: dict[str, str] = {}
        self._wifi_rssi: deque[float] = deque(maxlen=RSSI_SAMPLES)
        self._message_times: deque[float] = deque()
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"{type(self).__name__}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.transport.close()

    def snapshot(self) -> LinkState:
        with self._lock:
            state = copy.copy(self._state)
            state.config_errors = dict(self._state.config_errors)
            state.values = dict(self._state.values)
            state.edges = dict(self._state.edges)
            state.edge_rates = dict(self._state.edge_rates)
            state.humidity = dict(self._state.humidity)
            state.hx711 = dict(self._state.hx711)
            state.i2c_scans = dict(self._state.i2c_scans)
            state.i2c_results = list(self._i2c_results)
            state.uart_lines = {
                name: list(lines) + ([self._uart_partial[name]] if self._uart_partial.get(name) else [])
                for name, lines in self._uart_lines.items()
            }
            state.uart_total = dict(self._state.uart_total)
            state.wifi_rssi = list(self._wifi_rssi)
            state.wifi_seen = {key: copy.copy(seen) for key, seen in self._state.wifi_seen.items()}
            state.ble_seen = {key: copy.copy(seen) for key, seen in self._state.ble_seen.items()}
            for seen in list(state.wifi_seen.values()) + list(state.ble_seen.values()):
                seen.rssi = list(seen.rssi)
            state.updated = dict(self._state.updated)
            state.results = dict(self._state.results)
            state.history = {name: list(samples) for name, samples in self._history.items()}
            state.log = list(self._log)
            now = time.monotonic()
            while self._message_times and now - self._message_times[0] > RATE_WINDOW_S:
                self._message_times.popleft()
            state.message_rate = len(self._message_times) / RATE_WINDOW_S
        return state

    def update_config(self, config: ProjectConfig) -> None:
        with self._lock:
            self.config = config
            self._state.mode = config.mode

    def set_output(self, name: str, value: float) -> int | None:
        return None

    def request(self, message_type: str, name: str, **fields: object) -> int | None:
        """Sends an I2C or UART request for one pin. Returns its seq, or None."""
        return None

    def set_radio(self, settings: RadioSettings) -> int | None:
        return None

    def radio_settings(self) -> RadioSettings:
        """The radio settings that the host asked for last."""
        with self._lock:
            return self._state.radio

    def wifi_connect(self, ssid: str, password: str) -> int | None:
        return None

    def wifi_disconnect(self) -> int | None:
        return None

    def reset_board(self) -> None:
        with self._write_lock:
            self.transport.reset_board()

    def _set_status(self, status: str, connected: bool | None = None) -> None:
        with self._lock:
            self._state.status = status
            if connected is not None:
                self._state.connected = connected

    def _record_value(self, name: str, value: float | str, now: float) -> None:
        """Stores one value. The caller holds the lock."""
        self._state.values[name] = value
        self._state.updated[name] = now
        if isinstance(value, float) and not math.isnan(value):
            self._history.setdefault(name, deque(maxlen=HISTORY_SAMPLES)).append(value)

    def _append_log(self, text: str) -> None:
        """Adds one line to the log. The caller holds the lock."""
        self._log.append(text)
        self._state.log_total += 1

    def _record_log(self, text: str) -> None:
        with self._lock:
            self._append_log(text)
            self._state.rx_log_lines += 1
            self._state.last_rx = time.monotonic()

    def _write(self, data: bytes) -> None:
        with self._write_lock:
            self.transport.write(data)

    def _open(self) -> bool:
        try:
            self.transport.open()
        except LinkError as error:
            self._set_status(f"cannot open {self.transport.name}: {error}", connected=False)
            return False
        self._set_status("connected", connected=True)
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._open():
                self._stop.wait(REOPEN_DELAY_S)
                continue
            try:
                self._session()
            except LinkError as error:
                self._set_status(f"link lost: {error}", connected=False)
            finally:
                self.transport.close()
            self._stop.wait(REOPEN_DELAY_S)

    def _session(self) -> None:
        raise NotImplementedError


class AgentLink(BaseLink):
    """A board that runs the bench agent firmware."""

    can_control = True

    def __init__(self, transport: Transport, config: ProjectConfig) -> None:
        super().__init__(transport, config)
        self._seq = protocol.SeqCounter()
        self._config_dirty = threading.Event()
        self._config_seq = 0

    def update_config(self, config: ProjectConfig) -> None:
        super().update_config(config)
        with self._lock:
            names = {device.name for device in config.devices}
            for table in (self._state.values, self._state.edges, self._state.updated):
                for name in [name for name in table if name not in names]:
                    del table[name]
        self._config_dirty.set()

    def set_output(self, name: str, value: float) -> int | None:
        return self.request("set", name, value=value)

    def request(self, message_type: str, name: str, **fields: object) -> int | None:
        return self._send(message_type, id=name, **fields)

    def _send(self, message_type: str, **fields: object) -> int | None:
        with self._lock:
            ready = self._state.connected and self._state.configured
        if not ready:
            return None
        seq = self._seq.next()
        try:
            self._write(protocol.encode(message_type, seq, **fields))
        except LinkError:
            return None
        return seq

    def set_radio(self, settings: RadioSettings) -> int | None:
        """Stores the radio settings and sends them. The link sends them again
        after each new configuration, for example after a board restart."""
        with self._lock:
            self._state.radio = settings
        return self._send_radio(settings)

    def _send_radio(self, settings: RadioSettings) -> int | None:
        return self._send(
            "radio",
            wifi_scan_ms=settings.wifi_scan_ms,
            sniffer=settings.sniffer,
            ble_scan=settings.ble_scan,
            ble_active=settings.ble_active,
        )

    def wifi_connect(self, ssid: str, password: str) -> int | None:
        return self._send("wifi_connect", ssid=ssid, password=password)

    def wifi_disconnect(self) -> int | None:
        return self._send("wifi_disconnect")

    def i2c_scan(self, name: str) -> int | None:
        return self.request("i2c_scan", name)

    def i2c_read(self, name: str, address: int, register: int | None, length: int) -> int | None:
        fields: dict[str, object] = {"address": address, "length": length}
        if register is not None:
            fields["register"] = register
        return self.request("i2c_read", name, **fields)

    def i2c_write(self, name: str, address: int, register: int | None, data: bytes) -> int | None:
        fields: dict[str, object] = {"address": address, "data": data.hex()}
        if register is not None:
            fields["register"] = register
        return self.request("i2c_write", name, **fields)

    def uart_send(self, name: str, data: bytes) -> int | None:
        return self.request("uart_send", name, data=data.hex())

    def _send_config(self) -> None:
        with self._lock:
            body = self.config.wire_config()
            self._state.configured = False
        self._config_seq = self._seq.next()
        self._config_dirty.clear()
        self._write(protocol.encode("config", self._config_seq, **body))
        self._set_status("configuring")

    def _session(self) -> None:
        with self._lock:
            self._state.hello = None
            self._state.configured = False
        self._set_status("waiting for the bench agent")
        hello_sent = 0.0
        ping_sent = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            with self._lock:
                have_hello = self._state.hello is not None
            if not have_hello and now - hello_sent >= HELLO_RETRY_S:
                self._write(protocol.encode("hello", self._seq.next()))
                hello_sent = now
            if have_hello and self._config_dirty.is_set():
                self._send_config()
            if have_hello and now - ping_sent >= PING_PERIOD_S:
                self._write(protocol.encode("ping", self._seq.next()))
                ping_sent = now
            line = self.transport.read_line(READ_TIMEOUT_S)
            if line is not None:
                self._handle_line(line)

    def _handle_line(self, line: str) -> None:
        message = protocol.parse_line(line)
        if isinstance(message, protocol.LogLine):
            self._record_log(message.text)
            return
        now = time.monotonic()
        if isinstance(message, protocol.BadMessage):
            with self._lock:
                self._state.bad_lines += 1
                self._append_log(f"[bad message: {message.reason}] {message.text}")
            return
        with self._lock:
            self._state.rx_messages += 1
            self._state.last_rx = now
            self._message_times.append(now)
        if isinstance(message, protocol.Hello):
            self._on_hello(message)
        elif isinstance(message, protocol.ConfigAck):
            with self._lock:
                if message.seq == self._config_seq:
                    self._state.config_errors = dict(message.errors)
                    self._state.configured = True
                radio = self._state.radio
            self._set_status("running" if message.ok else "running, with pin errors")
            if radio.any_on:
                self._send_radio(radio)
        elif isinstance(message, protocol.State):
            with self._lock:
                self._state.uptime_ms = message.uptime_ms
                for name, value in message.values.items():
                    self._record_value(name, value, now)
                self._state.edges.update(message.edges)
                self._state.humidity.update(message.humidity)
                self._state.hx711.update(message.hx711)
                for name, info in message.hx711.items():
                    # The second channel keeps its own history under name:2.
                    if info.raw2 is not None:
                        self._record_value(f"{name}:2", info.raw2, now)
                self._update_edge_rates(message.edges, now)
        elif isinstance(message, protocol.I2cScanResult):
            with self._lock:
                self._state.i2c_scans[message.id] = message.addresses
                self._state.results[message.seq] = None
                found = " ".join(f"0x{address:02x}" for address in message.addresses) or "none"
                self._i2c_results.append(f"{message.id}: scan found {found}")
        elif isinstance(message, protocol.I2cData):
            with self._lock:
                self._state.results[message.seq] = None
                register = "" if message.register is None else f" register 0x{message.register:02x}"
                self._i2c_results.append(
                    f"{message.id}: read 0x{message.address:02x}{register}: {message.data.hex(' ')}"
                )
        elif isinstance(message, protocol.UartData):
            with self._lock:
                self._record_uart(message.id, message.data)
        elif isinstance(message, protocol.WifiScanResult):
            with self._lock:
                self._state.wifi_aps = message.aps
                self._state.wifi_scan_time = now
                for ap in message.aps:
                    self._remember(self._state.wifi_seen, ap.bssid, ap, ap.rssi, now)
                self._forget(self._state.wifi_seen, now)
        elif isinstance(message, protocol.WifiStatus):
            with self._lock:
                self._state.wifi_status = message
                if message.state == "connected":
                    self._wifi_rssi.append(float(message.rssi))
        elif isinstance(message, protocol.WifiChannels):
            with self._lock:
                self._state.wifi_channels = message.counts
                self._state.wifi_channels_time = now
        elif isinstance(message, protocol.BleDevices):
            with self._lock:
                self._state.ble_devices = message.devices
                self._state.ble_time = now
                for device in message.devices:
                    self._remember(self._state.ble_seen, device.address, device, device.rssi, now - device.age_ms / 1000.0)
                self._forget(self._state.ble_seen, now)
        elif isinstance(message, protocol.Ack):
            with self._lock:
                self._state.results[message.seq] = None
        elif isinstance(message, protocol.Error):
            with self._lock:
                self._state.errors += 1
                self._state.results[message.seq] = message.error
                self._append_log(f"[agent error, seq {message.seq}] {message.error}")
        elif isinstance(message, protocol.Pong):
            with self._lock:
                self._state.uptime_ms = message.uptime_ms
                self._state.free_heap = message.free_heap
        elif isinstance(message, protocol.Event):
            with self._lock:
                if message.event == "watchdog":
                    self._state.watchdog_events += 1
                self._append_log(f"[agent event] {message.event}")

    @staticmethod
    def _remember(table: dict[str, Seen], key: str, item: object, rssi: int, seen_at: float) -> None:
        """Stores one access point or device. The caller holds the lock."""
        entry = table.get(key)
        if entry is None:
            entry = Seen(item=item, first_seen=seen_at, last_seen=seen_at)
            table[key] = entry
        if seen_at > entry.last_seen or not entry.rssi:
            entry.rssi.append(float(rssi))
            del entry.rssi[:-RSSI_SAMPLES]
        entry.item = item
        entry.last_seen = max(entry.last_seen, seen_at)

    @staticmethod
    def _forget(table: dict[str, Seen], now: float) -> None:
        for key in [key for key, entry in table.items() if now - entry.last_seen > FORGET_AFTER_S]:
            del table[key]

    def _update_edge_rates(self, edges: dict[str, int], now: float) -> None:
        """Level changes per second over the last 2 s. The caller holds the lock."""
        for name, count in edges.items():
            samples = self._edge_samples.setdefault(name, deque())
            samples.append((now, count))
            while samples and now - samples[0][0] > EDGE_RATE_WINDOW_S:
                samples.popleft()
            first_time, first_count = samples[0]
            span = now - first_time
            # A digital input changes level twice for each pulse.
            self._state.edge_rates[name] = (count - first_count) / span / 2.0 if span > 0 else 0.0

    def _record_uart(self, name: str, data: bytes) -> None:
        """Splits received UART bytes into lines. The caller holds the lock."""
        self._state.uart_total[name] = self._state.uart_total.get(name, 0) + len(data)
        text = self._uart_partial.get(name, "") + data.decode("utf-8", errors="replace").replace("\r", "")
        lines = text.split("\n")
        self._uart_partial[name] = lines.pop()
        target = self._uart_lines.setdefault(name, deque(maxlen=UART_LINES))
        target.extend(lines)

    def _on_hello(self, hello: protocol.Hello) -> None:
        with self._lock:
            self._state.free_heap = hello.free_heap
        if hello.protocol != protocol.PROTOCOL_VERSION:
            self._set_status(
                f"agent protocol {hello.protocol}, host protocol {protocol.PROTOCOL_VERSION}. Flash the agent again"
            )
            return
        with self._lock:
            first = self._state.hello is None
            self._state.hello = hello
        # A hello with seq 0 after the first one means that the board restarted
        # and lost its configuration. A reply to a host hello needs nothing.
        if first or hello.seq == 0:
            self._send_config()


class LogLink(BaseLink):
    """A board that runs any firmware. Reads values from its log output."""

    def _session(self) -> None:
        self._set_status("reading the log")
        while not self._stop.is_set():
            line = self.transport.read_line(READ_TIMEOUT_S)
            if line is None:
                continue
            self._record_log(line)
            self._apply_rules(line)

    def _apply_rules(self, line: str) -> None:
        now = time.monotonic()
        with self._lock:
            rules = self.config.log_values
        for rule in rules:
            match = rule.pattern.search(line)
            if match is None:
                continue
            value = log_value(rule, match.group(1))
            with self._lock:
                self._state.rx_messages += 1
                self._message_times.append(now)
                self._record_value(rule.name, value, now)


def log_value(rule: LogValue, text: str) -> float | str:
    """A number with the scale and offset of the rule, or the text."""
    try:
        return float(text) * rule.scale + rule.offset
    except ValueError:
        return text


def create_link(config: ProjectConfig, port: str | None = None, simulate: bool = False) -> BaseLink:
    """The link for a project configuration."""
    if simulate:
        from bench.simulator import SimulatedTransport

        transport: Transport = SimulatedTransport(mode=config.mode)
    else:
        transport = SerialTransport(resolve_port(port or config.port), config.baud)
    if config.mode == "log":
        return LogLink(transport, config)
    return AgentLink(transport, config)

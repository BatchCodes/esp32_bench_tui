"""A simulated bench agent, for the TUI and the tests with no board.

SimulatedTransport acts like a serial port with the bench agent behind it. It
answers hello, config, set and ping, and sends state messages. Inputs change
by themselves: an ADC pin follows a slow sine, and a digital input changes
level every 2 s. In log mode it prints log lines like a normal firmware.
"""

from __future__ import annotations

import json
import math
import time
from collections import deque
from typing import Any

from bench import protocol

AGENT_VERSION = "0.1.0-sim"
HOST_TIMEOUT_S = 2.0
LOG_PERIOD_S = 1.0
INPUT_TOGGLE_S = 2.0
ADC_CENTRE_MV = 1650.0
ADC_SWING_MV = 1400.0
ADC_PERIOD_S = 8.0
UART_PERIOD_S = 1.0
SIM_I2C_DEVICES = {0x3C: b"\x00", 0x76: b"\x60"}
SIM_APS = (
    ("bench-lab", "24:6f:28:aa:bb:01", 6, -48, "wpa2", "bgn", True, "above"),
    ("farm-iot", "24:6f:28:aa:bb:02", 1, -63, "wpa2", "bgn", False, "none"),
    ("guest", "24:6f:28:aa:bb:03", 11, -71, "open", "bgnx", False, "below"),
    ("", "24:6f:28:aa:bb:04", 6, -80, "wpa2_wpa3", "bgnx", False, "none"),
)
# address, name in the advertisement, name in the scan response only, RSSI,
# company ID, connectable, services, manufacturer data (hex).
SIM_BLE = (
    ("c0:01:02:03:04:05", "Tag", "", -62, 0x004C, True, (), "4c0002151122334455667788990011223344556600010002c5"),
    ("d4:11:22:33:44:55", "Ruuvi 1A2B", "", -70, 0x0499, False, (), "990405"),
    ("e8:66:77:88:99:aa", "", "", -84, -1, False, (0xFD6F,), ""),
    ("f1:22:33:44:55:66", "", "Mi Band 6", -77, 0x0157, True, (0xFEE0,), "5701"),
    ("5a:33:44:55:66:77", "", "", -88, 0x0006, False, (), "06000109"),
)
SIM_IP = "192.168.4.23"
CONNECT_DELAY_S = 1.0
CHANNEL_PERIOD_S = 1.3
BLE_PERIOD_S = 1.0
STATUS_PERIOD_S = 1.0
NMEA_SENTENCE = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47\r\n"


class SimulatedTransport:
    """A Transport with a simulated agent behind it."""

    def __init__(self, mode: str = "agent", clock=time.monotonic, sleep=time.sleep) -> None:
        self.name = "simulator"
        self.mode = mode
        self._clock = clock
        self._sleep = sleep
        self._output: deque[str] = deque()
        self._pins: list[dict[str, Any]] = []
        self._values: dict[str, float] = {}
        self._edges: dict[str, int] = {}
        self._report_period_s = 0.0
        self._next_report = 0.0
        self._next_log = 0.0
        self._last_host_message: float | None = None
        self._watchdog_tripped = False
        self._start = 0.0
        self._log_counter = 0
        self._next_uart = 0.0
        self._uart_rx: dict[str, int] = {}
        self._humidity: dict[str, float] = {}
        self._hx711_reads: dict[str, int] = {}
        self._radio: dict[str, Any] = {}
        self._next_wifi_scan = 0.0
        self._next_channels = 0.0
        self._next_ble = 0.0
        self._ble_count = 0
        self._wifi_state = "off"
        self._wifi_ssid = ""
        self._connect_at = 0.0
        self._next_status = 0.0
        self.is_open = False

    def open(self) -> None:
        self._start = self._clock()
        self._next_log = self._start
        self.is_open = True
        self._output.extend(
            [
                "ets Jun  8 2016 00:22:57",
                "rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)",
                "I (312) bench_agent: bench agent 0.1.0-sim on esp32, protocol 1",
            ]
        )
        if self.mode == "agent":
            self._emit(self._hello(0))

    def close(self) -> None:
        self.is_open = False

    def reset_board(self) -> None:
        self._pins = []
        self._values = {}
        self._edges = {}
        self._report_period_s = 0.0
        self._output.clear()
        self.open()

    def write(self, data: bytes) -> None:
        if self.mode != "agent":
            return
        for raw in data.decode().splitlines():
            self._handle(raw)

    def read_line(self, timeout: float) -> str | None:
        deadline = self._clock() + timeout
        while True:
            self._tick()
            if self._output:
                return self._output.popleft()
            now = self._clock()
            if now >= deadline:
                return None
            self._sleep(min(0.005, deadline - now))

    def _uptime_ms(self) -> int:
        return int((self._clock() - self._start) * 1000)

    def _emit(self, body: dict[str, Any]) -> None:
        self._output.append(json.dumps(body, separators=(",", ":")))

    def _hello(self, seq: int) -> dict[str, Any]:
        return {
            "type": "hello",
            "seq": seq,
            "protocol": protocol.PROTOCOL_VERSION,
            "agent": AGENT_VERSION,
            "chip": "esp32",
            "revision": 301,
            "cores": 2,
            "mac": "02:00:00:be:4c:01",
            "flash_mb": 4,
            "free_heap": 281000,
        }

    def _handle(self, raw: str) -> None:
        try:
            body = json.loads(raw)
            message_type = body["type"]
            seq = int(body.get("seq", 0))
        except (ValueError, KeyError, TypeError):
            self._emit({"type": "error", "seq": 0, "error": "line is not a JSON object"})
            return
        self._last_host_message = self._clock()
        self._watchdog_tripped = False
        if message_type == "hello":
            self._emit(self._hello(seq))
        elif message_type == "ping":
            self._emit({"type": "pong", "seq": seq, "uptime_ms": self._uptime_ms(), "free_heap": 280512})
        elif message_type == "config":
            self._configure(seq, body)
        elif message_type == "set":
            self._set(seq, body)
        elif message_type in ("i2c_scan", "i2c_read", "i2c_write"):
            self._i2c(message_type, seq, body)
        elif message_type == "uart_send":
            self._uart_send(seq, body)
        elif message_type == "radio":
            self._set_radio(body)
            self._emit({"type": "ack", "seq": seq})
        elif message_type == "wifi_connect":
            self._wifi_ssid = str(body.get("ssid", ""))
            self._connect_at = self._clock() + CONNECT_DELAY_S
            self._emit({"type": "ack", "seq": seq})
            self._set_wifi_state("connecting")
        elif message_type == "wifi_disconnect":
            self._emit({"type": "ack", "seq": seq})
            self._set_wifi_state("idle")
        else:
            self._emit({"type": "error", "seq": seq, "error": "unknown message type"})

    def _configure(self, seq: int, body: dict[str, Any]) -> None:
        self._pins = list(body.get("pins", []))
        self._report_period_s = int(body.get("report_period_ms", 100)) / 1000.0
        self._next_report = self._clock()
        self._values = {}
        self._edges = {}
        self._humidity = {}
        self._next_uart = self._clock() + UART_PERIOD_S
        for pin in self._pins:
            mode = pin["mode"]
            default = 90.0 if mode == "servo" else 0.0
            self._values[pin["id"]] = float(pin.get("initial", default))
            if mode in ("i2c", "ds18b20", "dht11", "dht22", "hx711"):
                self._values[pin["id"]] = float("nan")
            if mode == "uart":
                self._uart_rx[pin["id"]] = 0
            if mode == "digital_in":
                self._edges[pin["id"]] = 0
        self._output.append(f"I ({self._uptime_ms()}) pins: configured {len(self._pins)} pins, 0 errors")
        self._emit({"type": "config_ack", "seq": seq, "ok": True, "errors": []})

    def _set(self, seq: int, body: dict[str, Any]) -> None:
        name = body.get("id")
        pin = next((item for item in self._pins if item["id"] == name), None)
        if pin is None:
            self._emit({"type": "error", "seq": seq, "error": "pin is not configured"})
            return
        if pin["mode"] not in ("digital_out", "pwm", "servo"):
            self._emit({"type": "error", "seq": seq, "error": "pin is not an output"})
            return
        self._values[name] = float(body.get("value", 0))
        self._emit({"type": "ack", "seq": seq})

    def _set_radio(self, body: dict[str, Any]) -> None:
        self._radio = {
            "wifi_scan_ms": int(body.get("wifi_scan_ms", 0)),
            "sniffer": bool(body.get("sniffer", False)),
            "ble_scan": bool(body.get("ble_scan", False)),
            "ble_active": bool(body.get("ble_active", False)),
        }
        now = self._clock()
        self._next_wifi_scan = now
        self._next_channels = now + CHANNEL_PERIOD_S
        self._next_ble = now
        if (self._radio["wifi_scan_ms"] or self._radio["sniffer"]) and self._wifi_state == "off":
            self._set_wifi_state("idle")

    def _set_wifi_state(self, state: str) -> None:
        self._wifi_state = state
        self._emit_status()

    def _emit_status(self) -> None:
        connected = self._wifi_state == "connected"
        jitter = int(3 * math.sin(self._clock()))
        self._emit(
            {
                "type": "wifi_status",
                "seq": 0,
                "state": self._wifi_state,
                "ssid": self._wifi_ssid if self._wifi_state != "off" else "",
                "ip": SIM_IP if connected else "",
                "rssi": -50 + jitter if connected else 0,
                "channel": 6 if connected else 0,
                "reason": "201" if self._wifi_state == "failed" else "",
            }
        )
        self._next_status = self._clock() + STATUS_PERIOD_S

    def _tick_radio(self, now: float) -> None:
        if self._wifi_state == "connecting" and now >= self._connect_at:
            known = any(ap[0] == self._wifi_ssid for ap in SIM_APS)
            self._set_wifi_state("connected" if known else "failed")
        elif self._wifi_state == "connected" and now >= self._next_status:
            self._emit_status()
        wifi_scan_ms = self._radio.get("wifi_scan_ms", 0)
        if wifi_scan_ms and now >= self._next_wifi_scan:
            jitter = int(4 * math.sin(now))
            aps = [
                {
                    "ssid": ssid,
                    "bssid": bssid,
                    "channel": channel,
                    "rssi": rssi + jitter,
                    "auth": auth,
                    "phy": phy,
                    "wps": wps,
                    "second": second,
                }
                for ssid, bssid, channel, rssi, auth, phy, wps, second in SIM_APS
            ]
            self._emit({"type": "wifi_scan_result", "seq": 0, "aps": aps})
            self._next_wifi_scan = now + wifi_scan_ms / 1000.0
        if self._radio.get("sniffer") and now >= self._next_channels:
            counts = [0] * 13
            for channel, base in ((1, 20), (6, 60), (11, 12)):
                counts[channel - 1] = base + int(10 * abs(math.sin(now + channel)))
            self._emit({"type": "wifi_channels", "seq": 0, "period_ms": int(CHANNEL_PERIOD_S * 1000), "counts": counts})
            self._next_channels = now + CHANNEL_PERIOD_S
        if self._radio.get("ble_scan") and now >= self._next_ble:
            active = self._radio.get("ble_active", False)
            self._ble_count += 1
            devices = [
                {
                    "address": address,
                    "name": name or (response_name if active else ""),
                    "rssi": rssi + int(3 * math.sin(now + index)),
                    "company_id": company,
                    "age_ms": 300 * (index + 1),
                    "address_type": 0 if index == 1 else 1,
                    "connectable": connectable,
                    "adv_count": self._ble_count * (index + 3),
                    "services": list(services),
                    "manufacturer": manufacturer,
                }
                for index, (address, name, response_name, rssi, company, connectable, services, manufacturer) in enumerate(SIM_BLE)
            ]
            self._emit({"type": "ble_devices", "seq": 0, "devices": devices})
            self._next_ble = now + BLE_PERIOD_S

    def _pin(self, seq: int, name: object, mode: str) -> dict[str, Any] | None:
        pin = next((item for item in self._pins if item["id"] == name), None)
        if pin is None:
            self._emit({"type": "error", "seq": seq, "error": "pin is not configured"})
            return None
        if pin["mode"] != mode:
            self._emit({"type": "error", "seq": seq, "error": f"pin is not a {mode} pin"})
            return None
        return pin

    def _i2c(self, message_type: str, seq: int, body: dict[str, Any]) -> None:
        name = body.get("id")
        if self._pin(seq, name, "i2c") is None:
            return
        if message_type == "i2c_scan":
            self._values[name] = float(len(SIM_I2C_DEVICES))
            self._emit({"type": "i2c_scan_result", "seq": seq, "id": name, "addresses": sorted(SIM_I2C_DEVICES)})
            return
        address = int(body.get("address", 0))
        if address not in SIM_I2C_DEVICES:
            self._emit({"type": "error", "seq": seq, "error": "no answer from the I2C device"})
            return
        if message_type == "i2c_write":
            self._emit({"type": "ack", "seq": seq})
            return
        length = int(body.get("length", 1))
        data = (SIM_I2C_DEVICES[address] * length)[:length]
        reply: dict[str, Any] = {"type": "i2c_data", "seq": seq, "id": name, "address": address}
        if "register" in body:
            reply["register"] = body["register"]
        reply["data"] = data.hex()
        self._emit(reply)

    def _uart_send(self, seq: int, body: dict[str, Any]) -> None:
        name = body.get("id")
        if self._pin(seq, name, "uart") is None:
            return
        self._emit({"type": "ack", "seq": seq})
        # The simulated UART is a loopback: it receives what it sends.
        self._emit_uart(name, bytes.fromhex(str(body.get("data", ""))))

    def _emit_uart(self, name: str, data: bytes) -> None:
        self._uart_rx[name] = self._uart_rx.get(name, 0) + len(data)
        self._values[name] = float(self._uart_rx[name])
        self._emit({"type": "uart_data", "seq": 0, "id": name, "data": data.hex()})

    def _update_inputs(self, now: float) -> None:
        elapsed = now - self._start
        for pin in self._pins:
            name = pin["id"]
            if pin["mode"] == "adc":
                self._values[name] = ADC_CENTRE_MV + ADC_SWING_MV * math.sin(2 * math.pi * elapsed / ADC_PERIOD_S)
            elif pin["mode"] == "digital_in":
                level = float(int(elapsed / INPUT_TOGGLE_S) % 2)
                if self._values.get(name) != level:
                    self._edges[name] = self._edges.get(name, 0) + 1
                self._values[name] = level
            elif pin["mode"] == "ds18b20":
                self._values[name] = round(21.5 + 0.5 * math.sin(elapsed / 10.0), 2)
            elif pin["mode"] in ("dht11", "dht22"):
                self._values[name] = round(23.0 + 0.3 * math.sin(elapsed / 7.0), 1)
                self._humidity[name] = round(45.0 + 2.0 * math.sin(elapsed / 9.0), 1)
            elif pin["mode"] == "i2c":
                self._values.setdefault(name, float("nan"))
            elif pin["mode"] == "hx711":
                self._values[name] = round(251000 + 300 * math.sin(elapsed * 3.0))
                self._hx711_reads[name] = self._hx711_reads.get(name, 0) + 8

    def _tick(self) -> None:
        now = self._clock()
        if self.mode == "log":
            if now >= self._next_log:
                self._log_counter += 1
                heap = 280000 - (self._log_counter % 10) * 512
                self._output.append(f"I ({self._uptime_ms()}) app: loop {self._log_counter}, free heap {heap}")
                if self._log_counter % 5 == 0:
                    self._output.append(f"W ({self._uptime_ms()}) app: Event queue full, dropped {self._log_counter // 5} events")
                self._next_log = now + LOG_PERIOD_S
            return
        if (
            self._pins
            and not self._watchdog_tripped
            and self._last_host_message is not None
            and now - self._last_host_message >= HOST_TIMEOUT_S
        ):
            self._watchdog_tripped = True
            for pin in self._pins:
                if pin["mode"] in ("digital_out", "pwm", "servo"):
                    default = 90.0 if pin["mode"] == "servo" else 0.0
                    self._values[pin["id"]] = float(pin.get("initial", default))
            self._radio = {}
            self._emit({"type": "event", "seq": 0, "event": "watchdog"})
        self._tick_radio(now)
        if self._pins and now >= self._next_uart:
            for pin in self._pins:
                if pin["mode"] == "uart":
                    self._emit_uart(pin["id"], NMEA_SENTENCE.encode())
            self._next_uart = now + UART_PERIOD_S
        if self._pins and self._report_period_s > 0 and now >= self._next_report:
            self._update_inputs(now)
            state: dict[str, Any] = {
                "type": "state",
                "seq": 0,
                "uptime_ms": self._uptime_ms(),
                "values": {name: None if math.isnan(value) else round(value, 4) for name, value in self._values.items()},
                "edges": dict(self._edges),
            }
            if self._humidity:
                state["humidity"] = dict(self._humidity)
            hx711 = {}
            for pin in self._pins:
                if pin["mode"] != "hx711":
                    continue
                entry = {"ready": [True], "timeouts": [0], "reads": self._hx711_reads.get(pin["id"], 0)}
                if "data2" in pin:
                    entry["raw2"] = round(-84000 + 250 * math.cos(now - self._start))
                    entry["ready"].append(True)
                    entry["timeouts"].append(0)
                hx711[pin["id"]] = entry
            if hx711:
                state["hx711"] = hx711
            self._emit(state)
            self._next_report = now + self._report_period_s

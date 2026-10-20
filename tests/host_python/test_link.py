"""Tests for the protocol messages, the links and the simulated agent."""

import asyncio
import time
import unittest
from collections import deque
from pathlib import Path
from unittest import mock

from tests.host_python import host_path  # noqa: F401
from bench import protocol
from bench.config import load_project
from bench.link import (
    ASYNCIO_RUNNER,
    REOPEN_DELAY_S,
    AgentLink,
    BufferTransport,
    LinkError,
    LogLink,
    SerialTransport,
    log_value,
)
from bench.simulator import SimulatedTransport

REPO_DIR = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_DIR / "examples"
WAIT_TIMEOUT_S = 5.0


def wait_for(condition, timeout: float = WAIT_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


class ReplayTransport:
    """A Transport that returns fixed lines, then nothing."""

    def __init__(self, lines: list[str]) -> None:
        self.name = "replay"
        self.lines = deque(lines)
        self.written: list[bytes] = []

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def reset_board(self) -> None:
        pass

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def read_line(self, timeout: float) -> str | None:
        if self.lines:
            return self.lines.popleft()
        time.sleep(timeout)
        return None


def no_sleep(seconds: float) -> None:
    raise AssertionError(f"slept for {seconds} s")


async def async_wait_for(condition, timeout: float = WAIT_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.01)
    return False


class FailingTransport(ReplayTransport):
    """A Transport that cannot open."""

    def __init__(self) -> None:
        super().__init__([])
        self.opens = 0

    def open(self) -> None:
        self.opens += 1
        raise LinkError("no such port")


class ProtocolTests(unittest.TestCase):
    def test_encode(self) -> None:
        self.assertEqual(protocol.encode("set", 3, id="led", value=1), b'{"type":"set","seq":3,"id":"led","value":1}\n')

    def test_parse_log_and_messages(self) -> None:
        self.assertEqual(protocol.parse_line("I (12) main: hi\r\n"), protocol.LogLine("I (12) main: hi"))
        state = protocol.parse_line('{"type":"state","seq":0,"uptime_ms":5,"values":{"led":1},"edges":{"b":2}}')
        self.assertEqual(state, protocol.State(uptime_ms=5, values={"led": 1.0}, edges={"b": 2}))
        ack = protocol.parse_line('{"type":"config_ack","seq":2,"ok":false,"errors":[{"id":"pot","error":"no ADC"}]}')
        self.assertEqual(ack, protocol.ConfigAck(seq=2, ok=False, errors={"pot": "no ADC"}))

    def test_parse_bad_messages(self) -> None:
        self.assertIsInstance(protocol.parse_line('{"type":"state", broken'), protocol.BadMessage)
        self.assertIsInstance(protocol.parse_line('{"type":"reboot","seq":1}'), protocol.BadMessage)
        self.assertIsInstance(protocol.parse_line('{"type":"hello","seq":1}'), protocol.BadMessage)

    def test_parse_v2_messages(self) -> None:
        state = protocol.parse_line('{"type":"state","seq":0,"uptime_ms":1,"values":{"w":null,"r":21.5},"edges":{},"humidity":{"r":40}}')
        self.assertTrue(state.values["w"] != state.values["w"])
        self.assertEqual(state.humidity, {"r": 40.0})
        data = protocol.parse_line('{"type":"i2c_data","seq":6,"id":"bus","address":118,"register":208,"data":"600a"}')
        self.assertEqual(data, protocol.I2cData(seq=6, id="bus", address=118, register=208, data=b"\x60\x0a"))
        uart = protocol.parse_line('{"type":"uart_data","seq":0,"id":"gps","data":"4869"}')
        self.assertEqual(uart, protocol.UartData(id="gps", data=b"Hi"))

    def test_seq_counter_wraps(self) -> None:
        counter = protocol.SeqCounter(0x7FFFFFFF)
        self.assertEqual(counter.next(), 1)


class AgentLinkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_project(EXAMPLES_DIR / "pot_servo.yaml")
        self.transport = SimulatedTransport()
        self.link = AgentLink(self.transport, self.config)
        self.link.start()

    def tearDown(self) -> None:
        self.link.stop()

    def test_handshake_and_state(self) -> None:
        self.assertTrue(wait_for(lambda: self.link.snapshot().configured))
        self.assertTrue(wait_for(lambda: "pot" in self.link.snapshot().values))
        state = self.link.snapshot()
        self.assertEqual(state.hello.chip, "esp32")
        self.assertTrue(state.connected)
        self.assertEqual(state.config_errors, {})
        self.assertEqual(state.values["servo"], 90.0)
        self.assertTrue(any("bench agent" in line for line in state.log))

    def test_set_round_trip(self) -> None:
        self.assertTrue(wait_for(lambda: self.link.snapshot().configured))
        seq = self.link.set_output("servo", 45.0)
        self.assertIsNotNone(seq)
        self.assertTrue(wait_for(lambda: seq in self.link.snapshot().results))
        self.assertIsNone(self.link.snapshot().results[seq])
        self.assertTrue(wait_for(lambda: self.link.snapshot().values.get("servo") == 45.0))

    def test_set_error(self) -> None:
        self.assertTrue(wait_for(lambda: self.link.snapshot().configured))
        seq = self.link.set_output("pot", 1.0)
        self.assertTrue(wait_for(lambda: seq in self.link.snapshot().results))
        self.assertEqual(self.link.snapshot().results[seq], "pin is not an output")

    def test_config_update(self) -> None:
        self.assertTrue(wait_for(lambda: self.link.snapshot().configured))
        self.link.update_config(load_project(EXAMPLES_DIR / "led_button.yaml"))
        self.assertTrue(wait_for(lambda: "button" in self.link.snapshot().values))
        self.assertNotIn("pot", self.link.snapshot().values)

    def test_board_restart_sends_config_again(self) -> None:
        def config_count() -> int:
            return sum("configured 3 pins" in line for line in self.link.snapshot().log)

        self.assertTrue(wait_for(lambda: config_count() == 1))
        self.link.reset_board()
        self.assertTrue(wait_for(lambda: config_count() == 2))
        time.sleep(1.5)
        self.assertEqual(config_count(), 2)

    def test_history(self) -> None:
        self.assertTrue(wait_for(lambda: len(self.link.snapshot().history.get("pot", [])) >= 3))


class BusLinkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_project(EXAMPLES_DIR / "bus_sensors.yaml")
        self.link = AgentLink(SimulatedTransport(), self.config)
        self.link.start()
        self.assertTrue(wait_for(lambda: self.link.snapshot().configured))

    def tearDown(self) -> None:
        self.link.stop()

    def test_i2c(self) -> None:
        seq = self.link.i2c_scan("i2c")
        self.assertTrue(wait_for(lambda: "i2c" in self.link.snapshot().i2c_scans))
        self.assertEqual(self.link.snapshot().i2c_scans["i2c"], (0x3C, 0x76))
        self.assertIsNone(self.link.snapshot().results[seq])
        seq = self.link.i2c_read("i2c", 0x76, 0xD0, 1)
        self.assertTrue(wait_for(lambda: seq in self.link.snapshot().results))
        self.assertIn("read 0x76 register 0xd0: 60", self.link.snapshot().i2c_results[-1])
        seq = self.link.i2c_write("i2c", 0x10, None, b"\x01")
        self.assertTrue(wait_for(lambda: seq in self.link.snapshot().results))
        self.assertEqual(self.link.snapshot().results[seq], "no answer from the I2C device")

    def test_uart(self) -> None:
        self.assertTrue(wait_for(lambda: self.link.snapshot().uart_lines.get("gps")))
        self.assertTrue(self.link.snapshot().uart_lines["gps"][0].startswith("$GPGGA"))
        seq = self.link.uart_send("gps", b"hello\n")
        self.assertTrue(wait_for(lambda: "hello" in self.link.snapshot().uart_lines["gps"]))
        self.assertIsNone(self.link.snapshot().results[seq])

    def test_sensors_and_counter(self) -> None:
        self.assertTrue(wait_for(lambda: "room" in self.link.snapshot().humidity))
        state = self.link.snapshot()
        self.assertAlmostEqual(state.values["water"], 21.5, delta=1.0)
        self.assertAlmostEqual(state.humidity["room"], 45.0, delta=3.0)
        self.assertIn("flow", state.edge_rates)


class WatchdogTests(unittest.TestCase):
    def test_simulator_watchdog(self) -> None:
        now = [0.0]
        transport = SimulatedTransport(clock=lambda: now[0], sleep=lambda seconds: None)
        transport.open()
        transport.write(protocol.encode("config", 1, report_period_ms=100, pins=[{"id": "led", "gpio": 2, "mode": "digital_out"}]))
        transport.write(protocol.encode("set", 2, id="led", value=1))
        lines = [transport.read_line(0) for _ in range(8)]
        self.assertIn('{"type":"ack","seq":2}', lines)
        now[0] = 2.5
        lines = []
        while (line := transport.read_line(0)) is not None:
            lines.append(line)
        self.assertIn('{"type":"event","seq":0,"event":"watchdog"}', lines)
        state = protocol.parse_line(lines[-1])
        self.assertEqual(state.values["led"], 0.0)


class LogLinkTests(unittest.TestCase):
    def test_rules(self) -> None:
        config = load_project(EXAMPLES_DIR / "log_listen.yaml")
        transport = ReplayTransport(
            [
                "I (100) eth: Ethernet link up",
                "W (200) app: Event queue full, dropped 7 events",
                "W (300) app: Lost the server, free heap 123456",
            ]
        )
        link = LogLink(transport, config)
        link.start()
        try:
            self.assertTrue(wait_for(lambda: "free_heap" in link.snapshot().values))
            state = link.snapshot()
        finally:
            link.stop()
        self.assertEqual(state.values["ethernet_up"], "up")
        self.assertEqual(state.values["dropped_events"], 7.0)
        self.assertAlmostEqual(state.values["free_heap"], 123.456)
        self.assertEqual(len(state.log), 3)
        self.assertEqual(transport.written, [])

    def test_simulated_log_mode(self) -> None:
        config = load_project(EXAMPLES_DIR / "log_listen.yaml")
        link = LogLink(SimulatedTransport(mode="log"), config)
        link.start()
        try:
            self.assertTrue(wait_for(lambda: "free_heap" in link.snapshot().values))
        finally:
            link.stop()

    def test_log_value(self) -> None:
        config = load_project(EXAMPLES_DIR / "log_listen.yaml")
        rule = next(value for value in config.log_values if value.name == "free_heap")
        self.assertAlmostEqual(log_value(rule, "2000"), 2.0)
        self.assertEqual(log_value(rule, "n/a"), "n/a")


class AsyncioRunnerTests(unittest.IsolatedAsyncioTestCase):
    """The runner for the browser, where Python has no threads."""

    async def test_agent_handshake_and_set(self) -> None:
        config = load_project(EXAMPLES_DIR / "pot_servo.yaml")
        link = AgentLink(SimulatedTransport(sleep=no_sleep), config, runner=ASYNCIO_RUNNER)
        link.start()
        try:
            self.assertIsNone(link._thread)
            self.assertTrue(await async_wait_for(lambda: link.snapshot().configured))
            self.assertTrue(await async_wait_for(lambda: "pot" in link.snapshot().values))
            seq = link.set_output("servo", 45.0)
            self.assertTrue(await async_wait_for(lambda: link.snapshot().values.get("servo") == 45.0))
            self.assertIsNone(link.snapshot().results[seq])
        finally:
            link.stop()

    async def test_log_rules(self) -> None:
        config = load_project(EXAMPLES_DIR / "log_listen.yaml")
        transport = ReplayTransport(["W (300) app: Lost the server, free heap 123456"])
        link = LogLink(transport, config, runner=ASYNCIO_RUNNER)
        link.start()
        try:
            self.assertTrue(await async_wait_for(lambda: "free_heap" in link.snapshot().values))
        finally:
            link.stop()
        self.assertAlmostEqual(link.snapshot().values["free_heap"], 123.456)


class StepTests(unittest.TestCase):
    def test_unknown_runner(self) -> None:
        config = load_project(EXAMPLES_DIR / "pot_servo.yaml")
        with self.assertRaises(ValueError):
            AgentLink(SimulatedTransport(), config, runner="process")

    def test_reopen_waits_for_the_delay(self) -> None:
        config = load_project(EXAMPLES_DIR / "pot_servo.yaml")
        transport = FailingTransport()
        link = AgentLink(transport, config)
        link.step()
        link.step()
        self.assertEqual(transport.opens, 1)
        self.assertIn("cannot open", link.snapshot().status)
        self.assertFalse(link.snapshot().connected)
        with mock.patch("bench.link.time.monotonic", return_value=time.monotonic() + REOPEN_DELAY_S + 0.1):
            link.step()
        self.assertEqual(transport.opens, 2)

    def test_step_handles_lines_without_waiting(self) -> None:
        config = load_project(EXAMPLES_DIR / "pot_servo.yaml")
        link = AgentLink(SimulatedTransport(sleep=no_sleep), config)
        for _ in range(5):
            link.step()
        state = link.snapshot()
        self.assertIsNotNone(state.hello)
        self.assertTrue(state.configured)
        link.stop()

    def test_simulator_read_line_zero_does_not_sleep(self) -> None:
        transport = SimulatedTransport(sleep=no_sleep)
        transport.open()
        while transport.read_line(0.0) is not None:
            pass
        self.assertIsNone(transport.read_line(0.0))

    def test_serial_read_line_zero_does_not_sleep(self) -> None:
        transport = SerialTransport("/dev/null", 115200)
        transport._serial = mock.Mock(in_waiting=0)
        with mock.patch("bench.link.time.sleep", side_effect=no_sleep):
            self.assertIsNone(transport.read_line(0.0))
        transport._serial = mock.Mock(in_waiting=6)
        transport._serial.read.return_value = b"hello\n"
        with mock.patch("bench.link.time.sleep", side_effect=no_sleep):
            self.assertEqual(transport.read_line(0.0), "hello")


class BufferTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.written: list[bytes] = []
        self.resets = 0
        self.transport = BufferTransport("web serial")

    def connect(self) -> None:
        def reset() -> None:
            self.resets += 1

        self.transport.connect(self.written.append, reset)

    def test_open_needs_a_port(self) -> None:
        with self.assertRaisesRegex(LinkError, "no serial port"):
            self.transport.open()
        with self.assertRaises(LinkError):
            self.transport.write(b"x")

    def test_split_lines(self) -> None:
        self.connect()
        self.transport.open()
        self.transport.feed(b'{"type":"po')
        self.assertIsNone(self.transport.read_line(1.0))
        self.transport.feed(b'ng"}\r\nlog line\nrest')
        self.assertEqual(self.transport.read_line(0.0), '{"type":"pong"}')
        self.assertEqual(self.transport.read_line(0.0), "log line")
        self.assertIsNone(self.transport.read_line(0.0))
        self.transport.feed(b"\n")
        self.assertEqual(self.transport.read_line(0.0), "rest")

    def test_bytes_before_open_are_dropped(self) -> None:
        self.connect()
        self.transport.feed(b"boot noise\n")
        self.transport.open()
        self.assertIsNone(self.transport.read_line(0.0))

    def test_bad_utf8_and_long_lines(self) -> None:
        self.connect()
        self.transport.open()
        self.transport.feed(b"\xff\xfeok\n")
        self.assertEqual(self.transport.read_line(0.0), "\ufffd\ufffdok")
        self.transport.feed(b"x" * (protocol.MAX_LINE_LENGTH + 10))
        self.assertEqual(len(self.transport.read_line(0.0)), protocol.MAX_LINE_LENGTH + 10)

    def test_write_and_reset(self) -> None:
        self.connect()
        self.transport.open()
        self.transport.write(b"hello\n")
        self.transport.reset_board()
        self.assertEqual(self.written, [b"hello\n"])
        self.assertEqual(self.resets, 1)

    def test_write_error_is_a_link_error(self) -> None:
        def broken(data: bytes) -> None:
            raise OSError("device lost")

        self.transport.connect(broken)
        self.transport.open()
        with self.assertRaisesRegex(LinkError, "device lost"):
            self.transport.write(b"x")

    def test_disconnect(self) -> None:
        self.connect()
        self.transport.open()
        self.transport.disconnect("the cable was pulled")
        with self.assertRaisesRegex(LinkError, "cable"):
            self.transport.read_line(0.0)
        with self.assertRaisesRegex(LinkError, "cable"):
            self.transport.open()

    def test_agent_link_over_the_buffer(self) -> None:
        config = load_project(EXAMPLES_DIR / "pot_servo.yaml")
        link = AgentLink(self.transport, config)
        link.step()
        self.assertFalse(link.snapshot().connected)
        self.connect()
        with mock.patch("bench.link.time.monotonic", return_value=time.monotonic() + REOPEN_DELAY_S + 0.1):
            link.step()
        self.assertTrue(link.snapshot().connected)
        self.assertTrue(self.written[0].startswith(b'{"type":"hello"'))
        hello = protocol.encode("hello", 0, protocol=protocol.PROTOCOL_VERSION, agent="test", chip="esp32")
        self.transport.feed(hello)
        link.step()
        self.assertEqual(link.snapshot().hello.chip, "esp32")
        self.transport.disconnect()
        link.step()
        self.assertIn("link lost", link.snapshot().status)
        self.assertFalse(link.snapshot().connected)


if __name__ == "__main__":
    unittest.main()

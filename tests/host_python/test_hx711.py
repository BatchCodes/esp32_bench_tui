"""Tests for the HX711 load cell mode on the host."""

import asyncio
import unittest
from pathlib import Path

from tests.host_python import host_path  # noqa: F401
from bench import board_layout, display, protocol
from bench.config import dump_project, load_project, project_data
from bench.link import AgentLink
from bench.pin_command import entry_gpios, parse_pin_command
from bench.simulator import SimulatedTransport
from tests.host_python.test_config import load_errors
from tests.host_python.test_tui import TERMINAL_SIZE, wait_until

try:
    from bench.tui.app import BenchApp
    from bench.tui.board_view import BoardView
    from bench.tui.pin_detail import PinDetail
except ImportError:
    BenchApp = None

REPO_DIR = Path(__file__).resolve().parents[2]
EXAMPLE = REPO_DIR / "examples" / "lafvin_hw_scales_tester.yaml"


class Hx711ConfigTests(unittest.TestCase):
    def test_example(self) -> None:
        config = load_project(EXAMPLE)
        scales = config.device("scales")
        self.assertEqual(scales.gpios, [18, 19, 21])
        self.assertEqual(scales.gpio_text(), "clock 18 data 19 data2 21")
        self.assertEqual(
            scales.wire_pin(), {"id": "scales", "mode": "hx711", "clock": 18, "data": 19, "data2": 21, "gain": 128}
        )
        self.assertTrue(any("3.3 V" in warning for warning in config.warnings))

    def test_round_trip(self) -> None:
        config = load_project(EXAMPLE)
        self.assertEqual(project_data(config)["devices"][0], {"name": "scales", "type": "hx711", "clock": 18, "data": 19, "data2": 21})
        self.assertIn("data2: 21", dump_project(config))

    def test_checks(self) -> None:
        errors = load_errors(
            """
            board: lafvin_esp32_devkit
            devices:
              - {name: one, type: hx711, clock: 34, data: 19}
              - {name: two, type: hx711, clock: 18, data: 21, gain: 100}
              - {name: led, type: led, gpio: 21}
            """
        )
        joined = " | ".join(errors)
        self.assertIn("clock: GPIO 34 is input-only", joined)
        self.assertIn("gain must be", joined)
        self.assertIn("both use GPIO 21", joined)

    def test_pin_command(self) -> None:
        entry = parse_pin_command("hx711 18 19 21")
        self.assertEqual(entry, {"type": "hx711", "clock": 18, "data": 19, "data2": 21, "name": "hx711_18"})
        self.assertEqual(entry_gpios(entry), {18, 19, 21})
        self.assertNotIn("data2", parse_pin_command("hx711 18 19 gain=64"))
        self.assertEqual(parse_pin_command("hx711 18 19 gain=64")["gain"], 64)


class Hx711ProtocolTests(unittest.TestCase):
    def test_state(self) -> None:
        state = protocol.parse_line(
            '{"type":"state","seq":0,"uptime_ms":5,"values":{"scales":-12345},"edges":{},'
            '"hx711":{"scales":{"raw2":6789,"ready":[true,false],"timeouts":[0,3],"reads":40}}}'
        )
        self.assertEqual(state.values["scales"], -12345.0)
        self.assertEqual(state.hx711["scales"], protocol.Hx711State(raw2=6789.0, ready=(True, False), timeouts=(0, 3), reads=40))

    def test_text(self) -> None:
        info = protocol.Hx711State(raw2=6789.0, ready=(True, False), timeouts=(0, 3), reads=40)
        self.assertEqual(display.hx711_text(1000.0, info), "1: 1000 · 2: 6789 (stale, 3 timeouts)")
        self.assertEqual(display.hx711_text(1000.0, info, (900.0, None)), "1: +100 · 2: 6789 (stale, 3 timeouts)")
        none = protocol.Hx711State(raw2=None, ready=(False, False), timeouts=(5, 5), reads=0)
        self.assertEqual(display.hx711_text(float("nan"), none), "1: no data (5 timeouts) · 2: no data (5 timeouts)")
        self.assertEqual(board_layout.mode_code(load_project(EXAMPLE).device("scales")), "HX")


@unittest.skipIf(BenchApp is None, "Textual is not installed")
class Hx711TuiTests(unittest.TestCase):
    def test_board_pins_detail_and_tare(self) -> None:
        async def run() -> None:
            config = load_project(EXAMPLE)
            app = BenchApp(config, AgentLink(SimulatedTransport(), config))
            async with app.run_test(size=(160, 45)) as pilot:
                self.assertTrue(await wait_until(pilot, lambda: "scales" in app.state.hx711))
                await pilot.pause(0.3)
                board = app.main_screen.query_one(BoardView).render().plain
                row = next(line for line in board.split("\n") if "IO18" in line)
                self.assertRegex(row, r"IO18 HX +CLK")
                row = next(line for line in board.split("\n") if "IO19" in line)
                self.assertRegex(row, r"IO19 HX +25\d{4}")
                await pilot.press("p")
                self.assertEqual(app._selected_device().name, "scales")
                await pilot.pause(0.2)
                self.assertRegex(app._value_text(config.device("scales"), "scales", app.state.values["scales"]), r"^1: 25\d{4} · 2: -8\d{4}$")
                # Enter tares, enter again clears the tare.
                await pilot.press("enter")
                self.assertIn("scales", app._tare)
                await pilot.pause(0.3)
                self.assertRegex(app._value_text(config.device("scales"), "scales", app.state.values["scales"]), r"^1: [+-]\d+ · 2: [+-]\d+$")
                await pilot.press("space")
                self.assertIsInstance(app.screen, PinDetail)
                await pilot.pause(0.5)
                body = app.screen.query_one("#detail-body").render().plain
                self.assertIn("Channel 1", body)
                self.assertIn("Channel 2", body)
                self.assertIn("answering", body)
                await pilot.press("enter")
                self.assertNotIn("scales", app._tare)
                await pilot.press("space")
                # Tab does not change an HX711.
                await pilot.press("tab")
                await pilot.pause(0.2)
                self.assertEqual(app.config.device("scales").type, "hx711")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()

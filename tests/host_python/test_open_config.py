"""Tests for open mode: generic boards, the pin command and saving."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from tests.host_python import host_path  # noqa: F401
from bench.config import (
    ConfigError,
    dump_project,
    empty_project,
    load_board,
    load_project,
    project_data,
    with_device_entries,
)
from bench.link import AgentLink, LogLink
from bench.pin_command import PinCommandError, entry_gpios, parse_pin_command
from bench.simulator import SimulatedTransport
from tests.host_python.test_tui import TERMINAL_SIZE, wait_until

try:
    from bench.tui.app import BenchApp
except ImportError:
    BenchApp = None

REPO_DIR = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_DIR / "examples"


class GenericBoardTests(unittest.TestCase):
    def test_generic_board(self) -> None:
        board = load_board("generic_esp32s3")
        self.assertEqual(board.chip.chip, "esp32s3")
        self.assertNotIn(43, board.pins)
        self.assertNotIn(26, board.pins)
        self.assertIn(4, board.pins)
        with self.assertRaises(ConfigError):
            load_board("generic_esp8266")

    def test_empty_project(self) -> None:
        config = empty_project("generic_esp32", Path("bench.yaml"))
        self.assertEqual(config.devices, ())
        self.assertTrue(any("generic board" in warning for warning in config.warnings))


class WatchAllTests(unittest.TestCase):
    def test_olimex_inputs(self) -> None:
        from bench.config import with_all_inputs

        config = with_all_inputs(empty_project("olimex_esp32_poe_iso", Path("bench.yaml")))
        types = {device.gpio: device.type for device in config.devices}
        self.assertEqual(types[36], "adc")
        self.assertEqual(types[32], "adc")
        self.assertEqual(types[4], "digital_in")
        for gpio in (1, 3, 12, 17, 18, 19, 21, 22, 23, 25, 26, 27):
            self.assertNotIn(gpio, types)

    def test_every_board_fits(self) -> None:
        import json

        from bench.config import list_boards, with_all_inputs
        from bench.protocol import MAX_LINE_LENGTH, encode

        for name in list_boards() + ["generic_esp32", "generic_esp32s3", "generic_esp32c6"]:
            with self.subTest(board=name):
                config = with_all_inputs(empty_project(name, Path("bench.yaml")))
                self.assertLessEqual(len(encode("config", 1, **config.wire_config())), MAX_LINE_LENGTH)
                self.assertTrue(json.dumps(config.wire_config()))


class ListenTests(unittest.TestCase):
    def test_listen_config(self) -> None:
        config = empty_project("generic_esp32", Path("bench.yaml"), mode="log", baud=74880)
        self.assertEqual((config.mode, config.baud, config.devices, config.log_values), ("log", 74880, (), ()))


@unittest.skipIf(BenchApp is None, "Textual is not installed")
class BoardPickerTests(unittest.TestCase):
    def test_choices_and_last_board(self) -> None:
        from bench.tui import picker

        choices = picker.board_choices()
        keys = [choice.key for choice in choices]
        self.assertIn("olimex_esp32_poe_iso", keys)
        self.assertEqual(keys[-1], picker.DETECT)
        self.assertTrue(keys[-2].startswith("generic_"))

        async def run() -> None:
            with tempfile.TemporaryDirectory() as directory:
                original = picker.LAST_BOARD_FILE, picker.STATE_DIR
                picker.STATE_DIR = Path(directory)
                picker.LAST_BOARD_FILE = Path(directory) / "last_board"
                try:
                    app = picker.BoardPicker("a test")
                    async with app.run_test(size=TERMINAL_SIZE) as pilot:
                        # No last board yet: the cursor is on the last choice.
                        self.assertEqual(app.query_one("OptionList").highlighted, len(keys) - 1)
                        await pilot.press("home", "enter")
                    self.assertEqual(app.return_value, keys[0])
                    self.assertEqual(picker.read_last_board(), keys[0])
                    app = picker.BoardPicker("a test")
                    async with app.run_test(size=TERMINAL_SIZE) as pilot:
                        self.assertEqual(app.query_one("OptionList").highlighted, 0)
                        await pilot.press("escape")
                    self.assertIsNone(app.return_value)
                finally:
                    picker.LAST_BOARD_FILE, picker.STATE_DIR = original

        asyncio.run(run())


class PinCommandTests(unittest.TestCase):
    def test_simple(self) -> None:
        self.assertEqual(parse_pin_command("out 4"), {"type": "digital_out", "gpio": 4, "name": "gpio4"})
        self.assertEqual(parse_pin_command("in 15 pull=up invert=true")["invert"], True)
        self.assertEqual(parse_pin_command("pwm 13 freq=5000")["freq_hz"], 5000)
        self.assertEqual(parse_pin_command("adc 32 scale=0.001 units=V name=pot")["name"], "pot")
        self.assertEqual(parse_pin_command("dht 5")["type"], "dht22")

    def test_two_gpios(self) -> None:
        entry = parse_pin_command("i2c 21 22")
        self.assertEqual((entry["sda"], entry["scl"], entry["name"]), (21, 22, "i2c_21"))
        self.assertEqual(entry_gpios(entry), {21, 22})
        self.assertEqual(parse_pin_command("uart 17 16 baud=115200")["baud"], 115200)

    def test_replace_entry_keeps_the_place(self) -> None:
        from bench.pin_command import replace_entry

        entries = [{"name": "a", "type": "digital_in", "gpio": 1}, {"name": "b", "type": "adc", "gpio": 32}, {"name": "c", "type": "digital_in", "gpio": 4}]
        changed = replace_entry(entries, {"name": "b", "type": "pwm", "gpio": 32})
        self.assertEqual([item["name"] for item in changed], ["a", "b", "c"])
        self.assertEqual(changed[1]["type"], "pwm")
        moved = replace_entry(entries, {"name": "x", "type": "digital_out", "gpio": 4})
        self.assertEqual([item["name"] for item in moved], ["a", "b", "x"])
        added = replace_entry(entries, {"name": "d", "type": "adc", "gpio": 33})
        self.assertEqual([item["name"] for item in added], ["a", "b", "c", "d"])

    def test_errors(self) -> None:
        for bad in ("out", "motor 4", "out x", "out 99", "i2c 21", "out 4 freq", "out 4 colour=red", "pwm 4 freq=fast"):
            with self.subTest(command=bad), self.assertRaises(PinCommandError):
                parse_pin_command(bad)


class SaveTests(unittest.TestCase):
    def test_examples_round_trip(self) -> None:
        for path in sorted(EXAMPLES_DIR.glob("*.yaml")):
            with self.subTest(example=path.name), tempfile.TemporaryDirectory() as directory:
                config = load_project(path)
                saved = Path(directory) / "bench.yaml"
                saved.write_text(dump_project(config))
                again = load_project(saved)
                self.assertEqual(project_data(again), project_data(config))
                self.assertEqual(again.devices, config.devices)

    def test_with_device_entries_checks(self) -> None:
        config = empty_project("generic_esp32", Path("bench.yaml"))
        config = with_device_entries(config, [parse_pin_command("out 4")])
        self.assertEqual(config.device("gpio4").mode, "digital_out")
        with self.assertRaises(ConfigError):
            with_device_entries(config, [parse_pin_command("out 34")])


@unittest.skipIf(BenchApp is None, "Textual is not installed")
class OpenModeTuiTests(unittest.TestCase):
    def test_add_toggle_remove_save(self) -> None:
        async def type_text(pilot, text: str) -> None:
            for character in text:
                await pilot.press({" ": "space", "=": "equals_sign"}.get(character, character))

        async def run() -> None:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bench.yaml"
                config = empty_project("generic_esp32", path)
                app = BenchApp(config, AgentLink(SimulatedTransport(), config), auto_board=True)
                async with app.run_test(size=TERMINAL_SIZE) as pilot:
                    self.assertTrue(await wait_until(pilot, lambda: app.state.configured))
                    await pilot.press("a")
                    await type_text(pilot, "out 4")
                    await pilot.press("enter")
                    self.assertTrue(await wait_until(pilot, lambda: "gpio4" in app.state.values))
                    await pilot.press("p")
                    await pilot.press("enter")
                    self.assertTrue(await wait_until(pilot, lambda: app.state.values.get("gpio4") == 1.0))
                    await pilot.press("a")
                    await type_text(pilot, "adc 32")
                    await pilot.press("enter")
                    self.assertTrue(await wait_until(pilot, lambda: "gpio32" in app.state.values))
                    # Adding a pin must not reset the output that is on.
                    await pilot.pause(0.5)
                    self.assertEqual(app.state.values.get("gpio4"), 1.0)
                    await pilot.press("a")
                    await type_text(pilot, "out 34")
                    await pilot.press("enter")
                    await pilot.pause(0.2)
                    self.assertIsNone(app.config.device("gpio34"))
                    await pilot.press("ctrl+s")
                    await pilot.pause(0.2)
                    saved = load_project(path)
                    self.assertEqual([device.name for device in saved.devices], ["gpio4", "gpio32"])
                    self.assertEqual(saved.device("gpio4").initial, 1.0)
                    # x no longer removes a pin.
                    await pilot.press("p", "x")
                    await pilot.pause(0.3)
                    self.assertEqual(len(app.config.devices), 2)

        asyncio.run(run())


    def test_listen_and_add_log_rule(self) -> None:
        async def run() -> None:
            config = empty_project("generic_esp32", Path("bench.yaml"), mode="log")
            app = BenchApp(config, LogLink(SimulatedTransport(mode="log"), config))
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                self.assertEqual(app.query_one("TabbedContent").active, "log")
                self.assertTrue(await wait_until(pilot, lambda: app.state.log_total > 3))
                await pilot.press("a")
                for character in "heap free heap (\\d+)":
                    await pilot.press({" ": "space", "(": "left_parenthesis", ")": "right_parenthesis", "\\": "backslash", "+": "plus"}.get(character, character))
                await pilot.press("enter")
                self.assertTrue(await wait_until(pilot, lambda: "heap" in app.state.values))
                await pilot.press("x")
                self.assertTrue(await wait_until(pilot, lambda: not app.config.log_values))

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()

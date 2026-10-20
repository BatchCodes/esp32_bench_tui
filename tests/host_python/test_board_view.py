"""Tests for the Board page layout and its keys."""

import asyncio
import unittest
from pathlib import Path

from tests.host_python import host_path  # noqa: F401
from bench import board_layout
from bench.board_layout import RIGHT, Cursor
from bench.config import Device, empty_project, list_boards, load_board
from bench.link import AgentLink
from bench.simulator import SimulatedTransport
from tests.host_python.test_tui import TERMINAL_SIZE, wait_until

try:
    from bench.tui.app import BenchApp
    from bench.tui.board_view import BoardView
    from bench.tui.pin_detail import PinDetail
except ImportError:
    BenchApp = None


class BoardLayoutTests(unittest.TestCase):
    def test_physical_layout(self) -> None:
        board = load_board("esp32_devkitc")
        layout = board_layout.board_layout(board)
        self.assertTrue(layout.physical)
        self.assertEqual(layout.left[0], board_layout.Slot("3V3", None))
        self.assertEqual(layout.left[2], board_layout.Slot("VP/IO36", 36))
        self.assertEqual(layout.rows, 19)

    def test_every_header_gpio_is_known(self) -> None:
        for name in list_boards():
            board = load_board(name)
            for slot in board_layout.board_layout(board).left + board_layout.board_layout(board).right:
                if slot.gpio is not None:
                    self.assertIn(slot.gpio, board.chip.gpios, f"{name}: GPIO {slot.gpio}")

    def test_olimex_and_lafvin_layout(self) -> None:
        olimex = board_layout.board_layout(load_board("olimex_esp32_poe_iso"))
        self.assertTrue(olimex.physical)
        self.assertEqual([slot.gpio for slot in olimex.left], [None, None, None, None, 0, 1, 2, 3, 4, 5])
        self.assertEqual([slot.gpio for slot in olimex.right], [39, 36, 35, 34, 33, 32, 16, 15, 14, 13])
        lafvin = board_layout.board_layout(load_board("lafvin_esp32_devkit"))
        self.assertEqual(lafvin.left[1], board_layout.Slot("VP/IO36", 36))
        self.assertEqual(lafvin.right[2], board_layout.Slot("TX0/IO1", 1))
        self.assertEqual((len(lafvin.left), len(lafvin.right)), (15, 15))

    def test_header_gpios_are_on_the_pin_list(self) -> None:
        for name in list_boards():
            board = load_board(name)
            layout = board_layout.board_layout(board)
            for slot in layout.left + layout.right:
                if slot.gpio is not None and slot.gpio not in board.never_usable():
                    self.assertIn(slot.gpio, board.pins, f"{name}: GPIO {slot.gpio}")

    def test_fallback_layout(self) -> None:
        board = load_board("generic_esp32")
        layout = board_layout.board_layout(board)
        self.assertFalse(layout.physical)
        gpios = [slot.gpio for slot in layout.left + layout.right]
        self.assertEqual(gpios, sorted(board.pins))

    def test_cursor_order_skips_power_and_flash(self) -> None:
        board = load_board("esp32_devkitc")
        layout = board_layout.board_layout(board)
        order = board_layout.cursor_order(layout, board)
        gpios = [layout.side(stop.side)[stop.row].gpio for stop in order]
        self.assertEqual(gpios[0], 36)
        for gpio in (1, 3, 6, 7, 8, 9, 10, 11):
            self.assertNotIn(gpio, gpios)
        self.assertEqual(order[-1], Cursor(RIGHT, 15))

    def test_move(self) -> None:
        board = load_board("esp32_devkitc")
        layout = board_layout.board_layout(board)
        order = board_layout.cursor_order(layout, board)
        self.assertEqual(board_layout.move(order, None, 1), order[0])
        self.assertEqual(board_layout.move(order, order[0], -1), order[-1])
        self.assertEqual(board_layout.move(order, order[0], 1), order[1])

    def test_pin_modes(self) -> None:
        board = load_board("esp32_devkitc")
        self.assertEqual(board_layout.pin_modes(board, 32), ["adc", "pwm", "digital_in", "digital_out"])
        self.assertEqual(board_layout.pin_modes(board, 4), ["digital_in", "digital_out"])
        self.assertEqual(board_layout.pin_modes(board, 36), ["adc", "digital_in"])

    def test_next_mode_entry(self) -> None:
        board = load_board("esp32_devkitc")
        cycle = []
        device = Device("gpio32", "adc", 32)
        for _ in range(4):
            entry = board_layout.next_mode_entry(board, 32, device)
            cycle.append(entry["type"])
            device = Device(entry["name"], entry["type"], 32)
        self.assertEqual(cycle, ["pwm", "digital_in", "digital_out", "adc"])
        self.assertEqual(
            board_layout.next_mode_entry(board, 4, Device("gpio4", "digital_in", 4)),
            {"name": "gpio4", "type": "digital_out", "gpio": 4, "initial": 0},
        )
        self.assertEqual(board_layout.next_mode_entry(board, 4, Device("gpio4", "digital_out", 4))["type"], "digital_in")
        self.assertEqual(board_layout.next_mode_entry(board, 36, Device("gpio36", "adc", 36))["type"], "digital_in")
        self.assertEqual(board_layout.next_mode_entry(board, 36, Device("gpio36", "digital_in", 36))["type"], "adc")
        self.assertEqual(board_layout.next_mode_entry(board, 4, Device("led", "led", 4))["type"], "digital_in")
        self.assertEqual(board_layout.next_mode_entry(board, 5, None)["type"], "digital_in")
        with self.assertRaises(board_layout.SwitchError):
            board_layout.next_mode_entry(board, 21, Device("bus", "i2c", 21, gpio2=22))

    def test_value_text(self) -> None:
        self.assertEqual(board_layout.pin_value_text(Device("b", "digital_in", 4), "gpio", 1.0), "1")
        self.assertEqual(board_layout.pin_value_text(Device("b", "led", 4), "gpio", 0.0), "0")
        self.assertEqual(board_layout.pin_value_text(Device("b", "digital_in", 4), "gpio", None), "—")
        pot = Device("pot", "adc", 32, scale=0.001, units="V")
        self.assertEqual(board_layout.pin_value_text(pot, "gpio", 1650.0), "1.65 V")
        self.assertEqual(board_layout.pin_value_text(Device("bus", "i2c", 21, gpio2=22), "scl", 2.0), "scl")

    def test_mode_code(self) -> None:
        self.assertEqual(board_layout.mode_code(Device("a", "digital_in", 4)), "DI")
        self.assertEqual(board_layout.mode_code(Device("a", "led", 4)), "DO")
        self.assertEqual(board_layout.mode_code(Device("a", "adc", 32)), "ADC")
        self.assertEqual(board_layout.mode_code(Device("a", "pwm", 13)), "PWM")

    def test_board_rows_show_the_mode(self) -> None:
        from bench.config import with_all_inputs, with_device_entries, device_entry

        config = with_all_inputs(empty_project("olimex_esp32_poe_iso", Path("bench.yaml")))
        entries = [device_entry(device) for device in config.devices if device.gpio != 4]
        entries.append({"name": "gpio4", "type": "digital_out", "gpio": 4})
        view = BoardView(with_device_entries(config, entries))
        lines = view.render().plain.split("\n")
        row = next(line for line in lines if "IO4 " in line)
        self.assertRegex(row, r"gpio4 +— +DO IO4 ─┤")
        row = next(line for line in lines if "├─ IO36" in line)
        self.assertRegex(row, r"├─ IO36 ADC +— +gpio36")
        widths = {len(line) for line in lines if "─┤" in line and "├─" in line}
        self.assertEqual(len(widths), 1)

    def test_pin_command_for(self) -> None:
        board = load_board("esp32_devkitc")
        self.assertEqual(board_layout.pin_command_for(board, 4, None), "out 4")
        self.assertEqual(board_layout.pin_command_for(board, 34, None), "in 34")
        self.assertEqual(board_layout.pin_command_for(board, 32, Device("pot", "adc", 32)), "adc 32 name=pot")


@unittest.skipIf(BenchApp is None, "Textual is not installed")
class BoardPageTests(unittest.TestCase):
    def test_add_and_toggle_from_the_board(self) -> None:
        async def run() -> None:
            config = empty_project("esp32_devkitc", Path("/nonexistent/bench.yaml"))
            app = BenchApp(config, AgentLink(SimulatedTransport(), config))
            async with app.run_test(size=(150, 45)) as pilot:
                self.assertTrue(await wait_until(pilot, lambda: app.state.configured))
                self.assertEqual(app.query_one("TabbedContent").active, "board")
                view = app.query_one(BoardView)
                self.assertIs(app.focused, view)
                # VP/IO36, VN/IO39, IO34, IO35, IO32: down 4 times reaches GPIO 32.
                await pilot.press("down", "down", "down", "down")
                self.assertEqual(view.selected_gpio(), 32)
                # a on the Board page starts the pin command with the selected GPIO.
                await pilot.press("a")
                self.assertEqual(app.query_one("#value-input").value, "out 32")
                await pilot.press("enter")
                self.assertTrue(await wait_until(pilot, lambda: "gpio32" in app.state.values))
                self.assertEqual(app.query_one("TabbedContent").active, "board")
                self.assertIs(app.focused, view)
                # Enter toggles the output.
                await pilot.press("enter")
                self.assertTrue(await wait_until(pilot, lambda: app.state.values.get("gpio32") == 1.0))
                self.assertIn("gpio32", view.render().plain)
                # Tab cycles analog in, analog out, digital in, digital out (GPIO 32 is ADC1).
                for expected in ("adc", "pwm", "digital_in", "digital_out"):
                    await pilot.press("tab")
                    self.assertTrue(await wait_until(pilot, lambda: app.config.device("gpio32").type == expected), expected)
                # Space opens the detail view with the chart, tab works there too.
                await pilot.press("space")
                self.assertIsInstance(app.screen, PinDetail)
                await pilot.press("tab")
                self.assertTrue(await wait_until(pilot, lambda: app.config.device("gpio32").type == "adc"))
                await pilot.pause(1.0)
                body = app.screen.query_one("#detail-body").render().plain
                self.assertIn("GPIO 32", body)
                self.assertIn("last", body)
                self.assertIn("scale: fixed", body)
                self.assertIn("3150 mV", body)
                await pilot.press("z")
                self.assertIn("scale: zoom", app.screen.query_one("#detail-body").render().plain)
                await pilot.press("right")
                self.assertIsInstance(app.screen, PinDetail)
                # Enter in the detail view changes the pin: an input says so.
                await pilot.press("enter")
                self.assertIsInstance(app.screen, PinDetail)
                await pilot.press("space")
                self.assertIs(app.focused, view)
                # Left and right change the page.
                await pilot.press("right")
                self.assertEqual(app.query_one("TabbedContent").active, "overview")
                await pilot.press("left", "left")
                self.assertEqual(app.query_one("TabbedContent").active, "link")
                await pilot.press("right")
                # In the text input, left and right move the cursor.
                await pilot.press("a")
                await pilot.press("left")
                self.assertEqual(app.query_one("TabbedContent").active, "board")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()

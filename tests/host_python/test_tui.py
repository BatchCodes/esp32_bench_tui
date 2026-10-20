"""Smoke tests of the Textual app against the simulated agent.

The tests are skipped when Textual is not installed.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.host_python import host_path  # noqa: F401
from bench.config import load_project
from bench.link import AgentLink, LogLink
from bench.simulator import SimulatedTransport

try:
    from bench.tui.app import BenchApp
    from bench.tui.pin_detail import PinDetail
except ImportError:
    BenchApp = None

REPO_DIR = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_DIR / "examples"
TERMINAL_SIZE = (140, 40)


async def wait_until(pilot, condition, timeout: float = 5.0) -> bool:
    for _ in range(int(timeout / 0.05)):
        if condition():
            return True
        await pilot.pause(0.05)
    return condition()


@unittest.skipIf(BenchApp is None, "Textual is not installed")
class TuiTests(unittest.TestCase):
    def test_control_outputs(self) -> None:
        async def run() -> None:
            config = load_project(EXAMPLES_DIR / "led_button.yaml")
            app = BenchApp(config, AgentLink(SimulatedTransport(), config))
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                self.assertTrue(await wait_until(pilot, lambda: app.state.configured))
                await pilot.press("p")
                self.assertEqual(app._selected_device().name, "led")
                await pilot.press("enter")
                self.assertTrue(await wait_until(pilot, lambda: app.state.values.get("led") == 1.0))
                await pilot.press("enter")
                self.assertTrue(await wait_until(pilot, lambda: app.state.values.get("led") == 0.0))
                # Space opens the detail view, enter still changes the pin there.
                await pilot.press("space")
                self.assertIsInstance(app.screen, PinDetail)
                await pilot.press("enter")
                self.assertTrue(await wait_until(pilot, lambda: app.state.values.get("led") == 1.0))
                await pilot.pause(0.3)
                self.assertIn("GPIO 4", app.screen.query_one("#detail-body").render().plain)
                await pilot.press("space")
                self.assertNotIsInstance(app.screen, PinDetail)
                # The + and - keys are gone.
                self.assertNotIn("step", {binding.action for binding in app.BINDINGS})
                for page in ("o", "l", "i", "p"):
                    await pilot.press(page)
                    await pilot.pause(0.15)

        asyncio.run(run())

    def test_pins_page_keeps_order_and_cursor(self) -> None:
        async def run() -> None:
            from bench.config import empty_project, with_all_inputs

            config = with_all_inputs(empty_project("esp32_devkitc", Path("/nonexistent/bench.yaml")))
            app = BenchApp(config, AgentLink(SimulatedTransport(), config))
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                self.assertTrue(await wait_until(pilot, lambda: app.state.configured))
                await pilot.press("p", "down", "down", "down")
                before = [device.name for device in app.config.devices]
                selected = app._selected_device().name
                first_type = app.config.device(selected).type
                await pilot.press("tab")
                self.assertTrue(await wait_until(pilot, lambda: app.config.device(selected).type != first_type))
                await pilot.pause(0.3)
                self.assertEqual([device.name for device in app.config.devices], before)
                self.assertEqual(app._selected_device().name, selected)
                await pilot.press("tab")
                await pilot.pause(0.3)
                self.assertEqual(app._selected_device().name, selected)

        asyncio.run(run())

    def test_pwm_value_prompt(self) -> None:
        async def run() -> None:
            config = load_project(EXAMPLES_DIR / "pot_servo.yaml")
            app = BenchApp(config, AgentLink(SimulatedTransport(), config))
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                self.assertTrue(await wait_until(pilot, lambda: app.state.configured))
                await pilot.press("p", "down", "down")
                self.assertEqual(app._selected_device().name, "dimmer")
                for text, expected in (("25", 0.25), ("0.5", 0.5), ("150", 1.0)):
                    await pilot.press("enter", *text, "enter")
                    self.assertTrue(await wait_until(pilot, lambda: app.state.values.get("dimmer") == expected), text)
                self.assertTrue(
                    await wait_until(pilot, lambda: "above 100" in str(app.main_screen.query_one("#status-bar").render()))
                )
                field = app.main_screen.query_one("#value-input")
                # Space sends the typed value and closes the prompt.
                await pilot.press("enter", "4", "0", "space")
                self.assertFalse(field.display)
                self.assertTrue(await wait_until(pilot, lambda: app.state.values.get("dimmer") == 0.4))
                # An empty prompt closes with space or enter and sends nothing.
                sent = len(app._pending) + len(app.state.results)
                await pilot.press("enter")
                self.assertTrue(field.display)
                await pilot.press("space")
                self.assertFalse(field.display)
                await pilot.press("enter", "enter")
                self.assertFalse(field.display)
                await pilot.pause(0.3)
                self.assertEqual(len(app._pending) + len(app.state.results), sent)
                self.assertEqual(app.state.values.get("dimmer"), 0.4)
                self.assertNotIn("not a number", str(app.main_screen.query_one("#status-bar").render()))

        asyncio.run(run())

    def test_config_reload(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bench.yaml"
                shutil.copy(EXAMPLES_DIR / "led_button.yaml", path)
                config = load_project(path)
                app = BenchApp(config, AgentLink(SimulatedTransport(), config))
                async with app.run_test(size=TERMINAL_SIZE) as pilot:
                    self.assertTrue(await wait_until(pilot, lambda: app.state.configured))
                    path.write_text((EXAMPLES_DIR / "pot_servo.yaml").read_text())
                    self.assertTrue(await wait_until(pilot, lambda: "pot" in app.state.values))
                    path.write_text("board: no_such_board\n")
                    await pilot.pause(1.5)
                    self.assertEqual(app.config.board.name, "olimex_esp32_poe_iso")

        asyncio.run(run())

    def test_save_callback_and_no_file_watch(self) -> None:
        saved: list[tuple[Path, str]] = []

        def download(path: Path, text: str) -> str:
            saved.append((path, text))
            return f"Downloaded {path.name}"

        async def run() -> None:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bench.yaml"
                shutil.copy(EXAMPLES_DIR / "led_button.yaml", path)
                config = load_project(path)
                app = BenchApp(config, AgentLink(SimulatedTransport(), config), save=download, watch_file=False)
                async with app.run_test(size=TERMINAL_SIZE) as pilot:
                    self.assertTrue(await wait_until(pilot, lambda: app.state.configured))
                    await pilot.press("ctrl+s")
                    status = app.main_screen.query_one("#status-bar")
                    self.assertTrue(await wait_until(pilot, lambda: "Downloaded bench.yaml" in str(status.render())))
                    # With no file watch, a change on disk is not loaded.
                    path.write_text((EXAMPLES_DIR / "pot_servo.yaml").read_text())
                    await pilot.pause(1.5)
                    self.assertNotIn("pot", app.state.values)
                self.assertEqual(path.read_text(), (EXAMPLES_DIR / "pot_servo.yaml").read_text())

        asyncio.run(run())
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0][0].name, "bench.yaml")
        self.assertIn("board: olimex_esp32_poe_iso", saved[0][1])

    def test_save_error(self) -> None:
        def broken(path: Path, text: str) -> str:
            raise OSError("the browser blocked the download")

        async def run() -> None:
            config = load_project(EXAMPLES_DIR / "led_button.yaml")
            app = BenchApp(config, AgentLink(SimulatedTransport(), config), save=broken, watch_file=False)
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                await pilot.press("ctrl+s")
                status = app.main_screen.query_one("#status-bar")
                self.assertTrue(await wait_until(pilot, lambda: "Not saved: the browser blocked" in str(status.render())))

        asyncio.run(run())

    def test_bus_page(self) -> None:
        async def run() -> None:
            config = load_project(EXAMPLES_DIR / "bus_sensors.yaml")
            app = BenchApp(config, AgentLink(SimulatedTransport(), config))
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                self.assertTrue(await wait_until(pilot, lambda: app.state.configured))
                await pilot.press("b")
                await pilot.press("s")
                self.assertTrue(await wait_until(pilot, lambda: "i2c" in app.state.i2c_scans))
                await pilot.press("colon")
                for key in "read 0x76 0xd0":
                    await pilot.press("space" if key == " " else key)
                await pilot.press("enter")
                self.assertTrue(await wait_until(pilot, lambda: any("register 0xd0: 60" in line for line in app.state.i2c_results)))
                await pilot.press("colon")
                for key in "send hi":
                    await pilot.press("space" if key == " " else key)
                await pilot.press("enter")
                self.assertTrue(await wait_until(pilot, lambda: "hi" in app.state.uart_lines.get("gps", [])))
                await pilot.press("p")
                self.assertTrue(await wait_until(pilot, lambda: "room" in app.state.humidity))

        asyncio.run(run())

    def test_radio_pages(self) -> None:
        async def run() -> None:
            config = load_project(EXAMPLES_DIR / "led_button.yaml")
            app = BenchApp(config, AgentLink(SimulatedTransport(), config))
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                self.assertTrue(await wait_until(pilot, lambda: app.state.configured))
                await pilot.press("w", "s", "n")
                self.assertTrue(await wait_until(pilot, lambda: len(app.state.wifi_aps) == 4))
                self.assertTrue(await wait_until(pilot, lambda: len(app.state.wifi_channels) == 13))
                self.assertEqual(app.link.radio_settings().wifi_scan_ms, 5000)
                self.assertTrue(app.link.radio_settings().sniffer)
                await pilot.press("c", *"bench-lab", "enter", *"secret", "enter")
                self.assertTrue(
                    await wait_until(pilot, lambda: app.state.wifi_status is not None and app.state.wifi_status.state == "connected")
                )
                await pilot.press("d")
                self.assertTrue(await wait_until(pilot, lambda: app.state.wifi_status.state == "idle"))
                await pilot.press("t", "s")
                self.assertTrue(await wait_until(pilot, lambda: len(app.state.ble_devices) == 5))
                await pilot.press("slash", *"ruuvi", "enter")
                await pilot.pause(0.3)
                self.assertEqual(app._ble_filter, "ruuvi")

        asyncio.run(run())

    def test_radio_lists_detail_and_connect(self) -> None:
        async def run() -> None:
            from bench.tui.radio_detail import RadioDetail

            config = load_project(EXAMPLES_DIR / "led_button.yaml")
            app = BenchApp(config, AgentLink(SimulatedTransport(), config))
            async with app.run_test(size=(160, 45)) as pilot:
                self.assertTrue(await wait_until(pilot, lambda: app.state.configured))
                await pilot.press("w", "s")
                table = app.main_screen.query_one("#wifi-table")
                self.assertTrue(await wait_until(pilot, lambda: table.row_count == 4))
                self.assertIs(app.focused, table)
                # The strongest first: bench-lab, farm-iot, guest, hidden.
                await pilot.press("down", "down")
                self.assertEqual(app._table_key(table), "24:6f:28:aa:bb:03")
                await pilot.pause(1.2)
                self.assertEqual(app._table_key(table), "24:6f:28:aa:bb:03")
                await pilot.press("space")
                self.assertIsInstance(app.screen, RadioDetail)
                await pilot.pause(0.6)
                body = app.screen.query_one("#radio-detail-body").render().plain
                self.assertIn("guest", body)
                self.assertIn("40 MHz", body)
                self.assertIn("b/g/n/ax", body)
                # Enter on an open network connects with no password.
                await pilot.press("enter")
                self.assertNotIsInstance(app.screen, RadioDetail)
                self.assertTrue(await wait_until(pilot, lambda: app.state.wifi_status is not None and app.state.wifi_status.state == "connected"))
                self.assertEqual(app.state.wifi_status.ssid, "guest")
                # Enter again on the connected access point disconnects.
                await pilot.press("enter")
                self.assertTrue(await wait_until(pilot, lambda: app.state.wifi_status.state == "idle"))
                # Enter on a protected network asks for the password.
                await pilot.press("up", "up", "enter")
                field = app.main_screen.query_one("#value-input")
                self.assertTrue(field.display)
                self.assertTrue(field.password)
                await pilot.press(*"secret", "enter")
                self.assertTrue(await wait_until(pilot, lambda: app.state.wifi_status.ssid == "bench-lab" and app.state.wifi_status.state == "connected"))

                await pilot.press("t", "s")
                ble = app.main_screen.query_one("#ble-table")
                self.assertTrue(await wait_until(pilot, lambda: ble.row_count == 5))
                self.assertIs(app.focused, ble)
                # The active scan gets the scan response name of the Mi Band.
                self.assertTrue(await wait_until(pilot, lambda: app.state.ble_seen["f1:22:33:44:55:66"].item.name == "Mi Band 6"))
                cells = [str(ble.get_row(key)[1]) for key in ble.rows]
                self.assertIn("Microsoft beacon (Windows device, Swift Pair)", cells)
                self.assertIn("Exposure Notification", cells)
                await pilot.press("space")
                self.assertIsInstance(app.screen, RadioDetail)
                await pilot.pause(0.6)
                self.assertIn("Address", app.screen.query_one("#radio-detail-body").render().plain)
                await pilot.press("space")
                self.assertIs(app.focused, ble)

        asyncio.run(run())

    def test_log_mode(self) -> None:
        async def run() -> None:
            config = load_project(EXAMPLES_DIR / "log_listen.yaml")
            app = BenchApp(config, LogLink(SimulatedTransport(mode="log"), config))
            async with app.run_test(size=TERMINAL_SIZE) as pilot:
                self.assertTrue(await wait_until(pilot, lambda: "free_heap" in app.state.values))
                await pilot.press("space")
                await pilot.press("l")
                await pilot.pause(0.2)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()

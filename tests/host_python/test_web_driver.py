"""Tests for the browser terminal driver, in CPython with a fake terminal.

The tests are skipped when Textual is not installed.
"""

import asyncio
import unittest
from pathlib import Path

from tests.host_python import host_path  # noqa: F401
from bench.config import load_project
from bench.link import ASYNCIO_RUNNER, AgentLink
from bench.simulator import SimulatedTransport

try:
    from textual.widgets import TabbedContent

    from bench.tui.app import BenchApp
    from bench.tui.picker import BoardPicker
    from bench.web.driver import ENTER_APPLICATION_MODE, EXIT_APPLICATION_MODE, BrowserTerminal, PyodideDriver
except ImportError:
    BenchApp = None

REPO_DIR = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_DIR / "examples"
TERMINAL_SIZE = (140, 40)
WAIT_TIMEOUT_S = 10.0


async def wait_for(condition, timeout: float = WAIT_TIMEOUT_S) -> bool:
    for _ in range(int(timeout / 0.02)):
        if condition():
            return True
        await asyncio.sleep(0.02)
    return condition()


@unittest.skipIf(BenchApp is None, "Textual is not installed")
class PyodideDriverTests(unittest.TestCase):
    def test_bench_app_in_a_fake_terminal(self) -> None:
        output: list[str] = []

        async def run() -> None:
            terminal = BrowserTerminal(output.append, *TERMINAL_SIZE)
            config = load_project(EXAMPLES_DIR / "led_button.yaml")
            link = AgentLink(SimulatedTransport(), config, runner=ASYNCIO_RUNNER)
            app = BenchApp(config, link, watch_file=False)
            app.driver_class = PyodideDriver
            task = asyncio.create_task(app.run_async())
            self.assertTrue(await wait_for(lambda: app.state.configured))
            self.assertIs(terminal.driver, app._driver)
            self.assertEqual(app.size, TERMINAL_SIZE)
            screen = "".join(output)
            self.assertTrue(screen.startswith(ENTER_APPLICATION_MODE))
            self.assertIn("Board", screen)

            terminal.feed("p")
            tabs = app.main_screen.query_one(TabbedContent)
            self.assertTrue(await wait_for(lambda: tabs.active == "pins"))

            terminal.resize(100, 30)
            self.assertTrue(await wait_for(lambda: app.size == (100, 30)))

            terminal.feed("q")
            await asyncio.wait_for(task, WAIT_TIMEOUT_S)
            self.assertIsNone(terminal.driver)
            self.assertTrue("".join(output).endswith(EXIT_APPLICATION_MODE))

        asyncio.run(run())

    def test_lone_escape_is_a_key(self) -> None:
        """A lone escape byte is a key only after the parser timeout. The
        picker quits on escape, so its result shows that the key arrived."""
        output: list[str] = []

        async def run() -> str | None:
            terminal = BrowserTerminal(output.append, *TERMINAL_SIZE)
            app = BoardPicker("a test", hint="")
            app.driver_class = PyodideDriver
            task = asyncio.create_task(app.run_async())
            self.assertTrue(await wait_for(lambda: terminal.driver is not None))
            terminal.feed("\x1b")
            return await asyncio.wait_for(task, WAIT_TIMEOUT_S)

        self.assertIsNone(asyncio.run(run()))

    def test_driver_needs_a_terminal(self) -> None:
        async def run() -> None:
            BrowserTerminal.current = None
            app = BoardPicker("a test")
            with self.assertRaises(RuntimeError):
                PyodideDriver(app)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()

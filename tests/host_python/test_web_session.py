"""Tests for the web session: the project choices and a full run against the
simulated agent in a fake browser terminal.

The tests are skipped when Textual is not installed.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.host_python import host_path  # noqa: F401
from bench.config import ConfigError

try:
    from bench.tui import picker
    from bench.web import session
    from bench.web.driver import BrowserTerminal
except ImportError:
    session = None

REPO_DIR = Path(__file__).resolve().parents[2]
TERMINAL_SIZE = (140, 40)
WAIT_TIMEOUT_S = 10.0


async def wait_for(condition, timeout: float = WAIT_TIMEOUT_S) -> bool:
    for _ in range(int(timeout / 0.02)):
        if condition():
            return True
        await asyncio.sleep(0.02)
    return condition()


@unittest.skipIf(session is None, "Textual is not installed")
class WebSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work_dir = tempfile.TemporaryDirectory()
        work_dir = Path(self.work_dir.name)
        # The picker must not read or write the real last board file.
        for target, name, value in (
            (session, "WORK_DIR", work_dir),
            (picker, "STATE_DIR", work_dir),
            (picker, "LAST_BOARD_FILE", work_dir / "last_board"),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.work_dir.cleanup)

    def test_list_examples(self) -> None:
        examples = {example["name"]: example["title"] for example in session.list_examples()}
        self.assertEqual(examples["pot_servo.yaml"], "A potentiometer, a servo and a PWM output on the Olimex ESP32-POE-ISO")
        self.assertIn("log_listen.yaml", examples)

    def test_load_choice(self) -> None:
        self.assertIsNone(session.load_choice(session.OPEN))
        self.assertEqual(session.load_choice(session.EXAMPLE, "pot_servo.yaml").board.name, "olimex_esp32_poe_iso")
        # A path in the name cannot leave the examples directory.
        with self.assertRaises(ConfigError):
            session.load_choice(session.EXAMPLE, "../boards/olimex_esp32_poe_iso.yaml")
        text = (REPO_DIR / "examples" / "led_button.yaml").read_text() + "baud: 74880\n"
        config = session.load_choice(session.FILE, "my_bench.yaml", text)
        self.assertEqual(config.path, Path(self.work_dir.name) / "my_bench.yaml")
        self.assertEqual(session.project_baud(session.FILE, "my_bench.yaml", text), 74880)
        self.assertEqual(session.project_baud(session.OPEN), 115200)
        with self.assertRaises(ConfigError):
            session.load_choice(session.FILE, "bad.yaml", "board: no_such_board\n")

    def test_bad_file_ends_the_session_with_a_message(self) -> None:
        result = asyncio.run(session.run_session(session.FILE, "bad.yaml", "board: no_such_board\n", print))
        self.assertFalse(result.ok)
        self.assertIn("no board profile 'no_such_board'", result.message)

    def test_example_with_the_simulator_and_a_download(self) -> None:
        output: list[str] = []
        downloads: list[tuple[str, str]] = []

        async def run():
            terminal = BrowserTerminal(output.append, *TERMINAL_SIZE)
            task = asyncio.create_task(
                session.run_session(session.EXAMPLE, "pot_servo.yaml", "", lambda name, text: downloads.append((name, text)))
            )
            self.assertTrue(await wait_for(lambda: terminal.driver is not None))
            app = terminal.driver._app
            self.assertTrue(await wait_for(lambda: app.state.configured))
            terminal.feed("\x13")  # ctrl+s
            self.assertTrue(await wait_for(lambda: downloads))
            terminal.feed("q")
            return await asyncio.wait_for(task, WAIT_TIMEOUT_S)

        result = asyncio.run(run())
        self.assertTrue(result.ok)
        self.assertEqual(downloads[0][0], "pot_servo.yaml")
        self.assertIn("servo", downloads[0][1])

    def test_open_mode_runs_the_picker_first(self) -> None:
        output: list[str] = []

        async def run():
            terminal = BrowserTerminal(output.append, *TERMINAL_SIZE)
            task = asyncio.create_task(session.run_session(session.OPEN, "", "", print))
            self.assertTrue(await wait_for(lambda: "Which board" in "".join(output)))
            terminal.feed("\r")  # the last choice: detect the chip
            self.assertTrue(await wait_for(lambda: terminal.driver is not None and hasattr(terminal.driver._app, "link")))
            app = terminal.driver._app
            self.assertTrue(await wait_for(lambda: app.state.configured))
            self.assertEqual(app.config.board.name, "generic_esp32")
            self.assertGreater(len(app.config.devices), 10)
            terminal.feed("q")
            return await asyncio.wait_for(task, WAIT_TIMEOUT_S)

        self.assertTrue(asyncio.run(run()).ok)

    def test_picker_escape_ends_the_session(self) -> None:
        output: list[str] = []

        async def run():
            terminal = BrowserTerminal(output.append, *TERMINAL_SIZE)
            task = asyncio.create_task(session.run_session(session.OPEN, "", "", print))
            self.assertTrue(await wait_for(lambda: terminal.driver is not None))
            terminal.feed("\x1b")
            return await asyncio.wait_for(task, WAIT_TIMEOUT_S)

        result = asyncio.run(run())
        self.assertTrue(result.ok)
        self.assertIn("picker closed", result.message)


if __name__ == "__main__":
    unittest.main()

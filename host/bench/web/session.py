"""One run of the bench TUI in a web page: the project, the link and the app.

The page (web/app/bench.js) calls list_examples() to fill its project list,
project_baud() before it opens the serial port, and run_session() to run the
board picker (in open mode) and then the bench TUI in its browser terminal.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bench.config import DEFAULT_BAUD, REPO_DIR, ConfigError, ProjectConfig, empty_project, load_project, with_all_inputs
from bench.link import ASYNCIO_RUNNER, Transport, link_for
from bench.simulator import SimulatedTransport
from bench.tui.app import BenchApp
from bench.tui.picker import board_from_choice, pick_board_async
from bench.web.driver import PyodideDriver

EXAMPLES_DIR = REPO_DIR / "examples"
# The in-memory file system of Pyodide. An uploaded project file goes here.
WORK_DIR = Path("/tmp/bench")
OPEN_MODE_FILE = "bench.yaml"
OPEN = "open"
EXAMPLE = "example"
FILE = "file"
PICKER_HINT = "Reload the page to open a project file instead."


@dataclass(frozen=True)
class SessionResult:
    """How a session ended. The page shows the message."""

    ok: bool
    message: str


def list_examples() -> list[dict[str, str]]:
    """The example project files, each with the first sentence of the
    comment at the top of the file."""
    examples = []
    for path in sorted(EXAMPLES_DIR.glob("*.yaml")):
        comment = []
        for line in path.read_text().splitlines():
            if not line.startswith("#"):
                break
            comment.append(line.lstrip("#").strip())
        text = " ".join(comment)
        title = text.split(". ")[0].rstrip(".") if text else path.stem
        examples.append({"name": path.name, "title": title})
    return examples


def load_choice(kind: str, name: str = "", text: str = "") -> ProjectConfig | None:
    """The project for a choice on the page, or None for open mode.
    Raises ConfigError for a file with errors."""
    if kind == OPEN:
        return None
    if kind == EXAMPLE:
        path = EXAMPLES_DIR / Path(name).name
        if not path.is_file():
            raise ConfigError(name, ["no such example"])
        return load_project(path)
    if kind == FILE:
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        path = WORK_DIR / (Path(name).name or OPEN_MODE_FILE)
        path.write_text(text)
        return load_project(path)
    raise ValueError(f"unknown project choice {kind!r}")


def project_baud(kind: str, name: str = "", text: str = "") -> int:
    """The baud rate to open the serial port at."""
    config = load_choice(kind, name, text)
    return config.baud if config is not None else DEFAULT_BAUD


def describe_error(error: ConfigError) -> str:
    return f"{error.source}: " + "; ".join(error.errors)


def download_save(download: Any) -> Any:
    """A BenchApp save that gives the file to the page as a download."""

    def save(path: Path, text: str) -> str:
        download(path.name, text)
        return f"Downloaded {path.name}"

    return save


async def run_session(
    kind: str,
    name: str,
    text: str,
    download: Any,
    transport: Transport | None = None,
) -> SessionResult:
    """Runs the board picker in open mode, then the bench TUI. With no
    transport, the TUI runs against the simulated bench agent. A
    BrowserTerminal must exist before the call."""
    try:
        config = load_choice(kind, name, text)
    except ConfigError as error:
        return SessionResult(False, describe_error(error))
    auto_board = False
    if config is None:
        choice = await pick_board_async("open mode", PICKER_HINT, PyodideDriver)
        if choice is None:
            return SessionResult(True, "The board picker closed.")
        board, auto_board = board_from_choice(choice)
        config = with_all_inputs(empty_project(board, WORK_DIR / OPEN_MODE_FILE))
    if transport is None:
        transport = SimulatedTransport(mode=config.mode, sleep=lambda seconds: None)
    link = link_for(config, transport, ASYNCIO_RUNNER)
    app = BenchApp(
        config,
        link,
        auto_board=auto_board,
        watch_all=kind == OPEN,
        save=download_save(download),
        watch_file=False,
    )
    app.driver_class = PyodideDriver
    try:
        await app.run_async()
    finally:
        link.stop()
    return SessionResult(True, "The TUI stopped.")

"""A Textual driver for a browser terminal, with no threads.

The page creates one BrowserTerminal and gives it a write function, for
example the write method of an xterm.js terminal. The page calls feed() with
the data that the terminal sends (keys, mouse reports, paste, replies to
queries) and resize() when the terminal changes size. Each app that runs with
PyodideDriver attaches itself to BrowserTerminal.current while it runs, so
two apps (the board picker, then the bench TUI) can use one terminal in turn.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from textual import events
from textual._xterm_parser import XTermParser
from textual.driver import Driver
from textual.geometry import Size
from textual.message import Message

# How often the driver checks the parser timeout, so that a lone escape key
# arrives as a key and not as the start of a sequence.
PARSER_TICK_S = 0.05
DEFAULT_SIZE = (80, 24)

ENTER_APPLICATION_MODE = (
    "\x1b[?1049h"  # alternate screen
    "\x1b[?25l"  # hide the cursor
    "\x1b[?1004h"  # focus in and focus out events
    "\x1b[?2004h"  # bracketed paste
)
EXIT_APPLICATION_MODE = (
    "\x1b[?2004l"
    "\x1b[?1004l"
    "\x1b[?25h"  # show the cursor
    "\x1b[?1049l"  # main screen
)
MOUSE_ON = "\x1b[?1000h\x1b[?1003h\x1b[?1015h\x1b[?1006h"
MOUSE_OFF = "\x1b[?1000l\x1b[?1003l\x1b[?1015l\x1b[?1006l"
# Asks the terminal if it supports synchronized output. Textual reads the reply.
QUERY_SYNC_MODE = "\x1b[?2026$p"

# Textual sets the eager task factory. The Pyodide webloop (314.0.6) then
# calls asyncio.tasks._set_task_name, which Python 3.14 removed.
if not hasattr(asyncio.tasks, "_set_task_name"):

    def _set_task_name(task: asyncio.Task[Any], name: str | None) -> None:
        if name is not None:
            task.set_name(name)

    asyncio.tasks._set_task_name = _set_task_name  # type: ignore[attr-defined]


class BrowserTerminal:
    """The page side of the driver: one terminal that apps take in turn."""

    current: BrowserTerminal | None = None

    def __init__(self, write: Callable[[str], Any], columns: int = DEFAULT_SIZE[0], rows: int = DEFAULT_SIZE[1]) -> None:
        self._write = write
        self.size = (columns, rows)
        self.driver: PyodideDriver | None = None
        BrowserTerminal.current = self

    def write(self, data: str) -> None:
        self._write(data)

    def feed(self, data: str) -> None:
        """Data from the terminal: keys, mouse reports and query replies."""
        if self.driver is not None:
            self.driver.feed(data)

    def resize(self, columns: int, rows: int) -> None:
        self.size = (int(columns), int(rows))
        if self.driver is not None:
            self.driver.resize(*self.size)


class PyodideDriver(Driver):
    """Writes to BrowserTerminal.current and reads the data it feeds in."""

    def __init__(self, app: Any, *, debug: bool = False, mouse: bool = True, size: tuple[int, int] | None = None) -> None:
        super().__init__(app, debug=debug, mouse=mouse, size=size)
        terminal = BrowserTerminal.current
        if terminal is None:
            raise RuntimeError("create a BrowserTerminal before the app starts")
        self._terminal = terminal
        self._parser = XTermParser(debug)
        self._output: list[str] = []
        self._input_enabled = False
        self._tick_handle: asyncio.TimerHandle | None = None

    def write(self, data: str) -> None:
        self._output.append(data)

    def flush(self) -> None:
        if self._output:
            data = "".join(self._output)
            self._output.clear()
            self._terminal.write(data)

    def send_message(self, message: Message) -> None:
        # One thread only, so the message goes straight on the app queue.
        self._app.post_message(message)

    def start_application_mode(self) -> None:
        self._terminal.driver = self
        self.write(ENTER_APPLICATION_MODE)
        if self._mouse:
            self.write(MOUSE_ON)
        self.write(QUERY_SYNC_MODE)
        self.flush()
        self._input_enabled = True
        self.resize(*self._terminal.size)
        self._schedule_tick()

    def feed(self, data: str) -> None:
        if not self._input_enabled:
            return
        for message in self._parser.feed(data):
            self.process_message(message)

    def resize(self, columns: int, rows: int) -> None:
        size = Size(columns, rows)
        self.send_message(events.Resize(size, size))

    def disable_input(self) -> None:
        self._input_enabled = False
        if self._tick_handle is not None:
            self._tick_handle.cancel()
            self._tick_handle = None

    def stop_application_mode(self) -> None:
        self.disable_input()
        if self._mouse:
            self.write(MOUSE_OFF)
        self.write(EXIT_APPLICATION_MODE)
        self.flush()
        if self._terminal.driver is self:
            self._terminal.driver = None

    def _schedule_tick(self) -> None:
        self._tick_handle = self._loop.call_later(PARSER_TICK_S, self._tick)

    def _tick(self) -> None:
        if not self._input_enabled:
            return
        for message in self._parser.tick():
            self.process_message(message)
        self._schedule_tick()

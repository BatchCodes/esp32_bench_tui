"""The board picker: a short list that the TUI shows when no board is given.

The list has the board profiles first, then the generic board of each chip,
and last the generic board that follows the chip that the board reports.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from bench.config import DEFAULT_CHIP, GENERIC_PREFIX, ConfigError, list_boards, list_chips, load_board, load_chip

DETECT = "detect"
COMMAND_LINE_HINT = "Use --board or --config to skip this list."
STATE_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "bench"
LAST_BOARD_FILE = STATE_DIR / "last_board"


@dataclass(frozen=True)
class Choice:
    key: str
    label: Text


def board_choices() -> list[Choice]:
    """The board profiles, the generic boards, and the detect choice last."""
    choices = []
    for name in list_boards():
        try:
            board = load_board(name)
        except ConfigError:
            continue
        label = Text(board.title, style="bold")
        label.append(f"  {board.chip.title}, {name}", style="grey50")
        choices.append(Choice(name, label))
    for chip_name in list_chips():
        chip = load_chip(chip_name)
        label = Text(f"Generic {chip.title} board", style="bold")
        label.append(f"  {GENERIC_PREFIX}{chip_name}, chip facts only", style="grey50")
        choices.append(Choice(f"{GENERIC_PREFIX}{chip_name}", label))
    label = Text("Generic board, detect the chip", style="bold")
    label.append("  uses the chip that the bench agent reports", style="grey50")
    choices.append(Choice(DETECT, label))
    return choices


def read_last_board() -> str | None:
    try:
        return LAST_BOARD_FILE.read_text().strip() or None
    except OSError:
        return None


def write_last_board(key: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        LAST_BOARD_FILE.write_text(key + "\n")
    except OSError:
        # The choice is a convenience only. A read-only home is not an error.
        pass


class BoardPicker(App[str | None]):
    """Returns the chosen board name, DETECT, or None when the user quits."""

    TITLE = "bench"
    SUB_TITLE = "Which board is connected?"
    CSS = """
    #picker-help {
        padding: 0 1;
        color: $text-muted;
    }
    OptionList {
        height: 1fr;
    }
    """
    BINDINGS = [
        Binding("escape,q", "quit_picker", "Quit"),
    ]

    def __init__(self, purpose: str, hint: str = COMMAND_LINE_HINT) -> None:
        super().__init__()
        self.choices = board_choices()
        self.purpose = purpose
        self.hint = hint

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            f"Choose the board for {self.purpose}. Up and down to move, enter to choose. {self.hint}".rstrip(),
            id="picker-help",
        )
        yield OptionList(*[Option(choice.label, id=choice.key) for choice in self.choices])
        yield Footer()

    def on_mount(self) -> None:
        options = self.query_one(OptionList)
        keys = [choice.key for choice in self.choices]
        last = read_last_board()
        options.highlighted = keys.index(last) if last in keys else len(keys) - 1
        options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        key = str(event.option.id)
        write_last_board(key)
        self.exit(key)

    def action_quit_picker(self) -> None:
        self.exit(None)


def pick_board(purpose: str) -> str | None:
    return BoardPicker(purpose).run()


async def pick_board_async(purpose: str, hint: str = COMMAND_LINE_HINT, driver_class: type | None = None) -> str | None:
    """pick_board for a running event loop. In a browser, driver_class is the
    browser terminal driver."""
    picker = BoardPicker(purpose, hint)
    if driver_class is not None:
        picker.driver_class = driver_class
    return await picker.run_async()


def board_from_choice(choice: str) -> tuple[str, bool]:
    """The board name for a picker choice, and True when the TUI follows the
    chip that the agent reports."""
    if choice == DETECT:
        return f"{GENERIC_PREFIX}{DEFAULT_CHIP}", True
    return choice, False

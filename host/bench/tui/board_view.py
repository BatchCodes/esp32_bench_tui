"""The Board page widget: a portrait drawing of the board in the middle, and
the header pins on the left and right in their physical order."""

from __future__ import annotations

import time

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget

from bench import board_layout, display
from bench.board_layout import LEFT, Cursor
from bench.config import ProjectConfig
from bench.link import LinkState

BODY_WIDTH = 26
NAME_WIDTH = 14
VALUE_WIDTH = 12
LABEL_WIDTH = 10
MODE_WIDTH = 4
MODE_STYLES = {
    "digital_in": "green",
    "digital_out": "yellow",
    "adc": "magenta",
    "pwm": "cyan",
    "servo": "cyan",
    "i2c": "blue",
    "uart": "blue",
    "ds18b20": "magenta",
    "dht11": "magenta",
    "dht22": "magenta",
}
STALE_STYLES = {"fresh": "bold", "stale": "grey50", "lost": "red"}


class BoardView(Widget, can_focus=True):
    """Up and down move through the GPIOs, and enter posts PinChosen for the
    GPIO under the cursor. Left and right belong to the app: they change the page."""

    BINDINGS = [
        Binding("up", "move(-1)", "Previous pin", show=False),
        Binding("down", "move(1)", "Next pin", show=False),
        Binding("enter", "choose", "Change"),
    ]

    DEFAULT_CSS = """
    BoardView {
        height: auto;
        width: 100%;
        content-align: center top;
    }
    """

    class PinChosen(Message):
        def __init__(self, gpio: int) -> None:
            super().__init__()
            self.gpio = gpio

    def __init__(self, config: ProjectConfig, **kwargs) -> None:
        super().__init__(**kwargs)
        self.config = config
        self.state = LinkState()
        self.pin_layout = board_layout.board_layout(config.board)
        self.order = board_layout.cursor_order(self.pin_layout, config.board)
        self.cursor: Cursor | None = self.order[0] if self.order else None

    def set_config(self, config: ProjectConfig) -> None:
        """A new configuration. Keeps the cursor on the same GPIO when the board is the same."""
        gpio = self.selected_gpio()
        self.config = config
        self.pin_layout = board_layout.board_layout(config.board)
        self.order = board_layout.cursor_order(self.pin_layout, config.board)
        self.cursor = next((stop for stop in self.order if self._gpio_at(stop) == gpio), self.order[0] if self.order else None)
        self.refresh(layout=True)

    def set_state(self, state: LinkState) -> None:
        self.state = state
        self.refresh()

    def _gpio_at(self, cursor: Cursor | None) -> int | None:
        if cursor is None:
            return None
        return self.pin_layout.side(cursor.side)[cursor.row].gpio

    def selected_gpio(self) -> int | None:
        return self._gpio_at(self.cursor)

    def action_move(self, step: int) -> None:
        self.cursor = board_layout.move(self.order, self.cursor, step)
        self.refresh()

    def action_choose(self) -> None:
        gpio = self.selected_gpio()
        if gpio is not None:
            self.post_message(self.PinChosen(gpio))

    def get_content_height(self, container, viewport, width: int) -> int:
        return self.pin_layout.rows + 6

    def _pin_parts(self, side: str, row: int) -> tuple[str, Text, Text, Text]:
        """The name, value, label and mode code of one header pin."""
        slots = self.pin_layout.side(side)
        if row >= len(slots):
            return "", Text(""), Text(""), Text("")
        slot = slots[row]
        board = self.config.board
        if slot.gpio is None:
            return "", Text(""), Text(slot.label, style="grey50"), Text("")
        used = board_layout.devices_by_gpio(self.config.devices).get(slot.gpio)
        if used is not None:
            device, role = used
            age = self.state.updated.get(device.name)
            staleness = display.staleness(None if age is None else time.monotonic() - age)
            if device.type == "hx711" and role in ("data", "data2"):
                value = self._hx711_value(device.name, 0 if role == "data" else 1)
            else:
                value = board_layout.pin_value_text(
                    device,
                    role,
                    self.state.values.get(device.name),
                    self.state.humidity.get(device.name),
                    self.state.edge_rates.get(device.name),
                )
            error = self.state.config_errors.get(device.name)
            value_text = Text("error" if error else value, style="red" if error else STALE_STYLES[staleness])
            style = MODE_STYLES.get(device.mode, "")
            mode = Text(board_layout.mode_code(device), style="bold " + style if style else "bold")
            return device.name, value_text, Text(slot.label, style=style), mode
        if not board_layout.is_selectable(board, slot):
            return "", Text("reserved", style="grey35"), Text(slot.label, style="grey35"), Text("")
        reserved = slot.gpio in board.reserved
        note = "board" if reserved else ""
        return "", Text(note, style="grey50"), Text(slot.label, style="grey50" if reserved else ""), Text("")

    def _hx711_value(self, name: str, channel: int) -> str:
        info = self.state.hx711.get(name)
        if info is None or channel >= len(info.ready):
            return "waiting"
        raw = self.state.values.get(name) if channel == 0 else info.raw2
        tares = getattr(self.app, "_tare", {}).get(name, (None, None))
        return display.hx711_channel_text(
            raw if isinstance(raw, float) else None, info.ready[channel], info.timeouts[channel], tares[channel]
        )

    def _side_text(self, side: str, row: int) -> Text:
        name, value, label, mode = self._pin_parts(side, row)
        selected = self.cursor is not None and self.cursor.side == side and self.cursor.row == row
        name_text = Text(name[:NAME_WIDTH], style="bold")
        if side == LEFT:
            line = Text()
            line.append_text(self._pad(name_text, NAME_WIDTH, right=True))
            line.append(" ")
            line.append_text(self._pad(value, VALUE_WIDTH, right=True))
            line.append(" ")
            # The mode sits next to the label, so it reads "DI IO4".
            mode_and_label = mode + Text(" ") + label if mode.plain else label
            line.append_text(self._pad(mode_and_label, MODE_WIDTH + 1 + LABEL_WIDTH, right=True))
            connector = " ─┤" if label.plain else "  │"
        else:
            line = Text()
            label_and_mode = label + Text(" ") + mode if mode.plain else label
            line.append_text(self._pad(label_and_mode, LABEL_WIDTH + 1 + MODE_WIDTH, right=False))
            line.append(" ")
            line.append_text(self._pad(value, VALUE_WIDTH, right=False))
            line.append(" ")
            line.append_text(self._pad(name_text, NAME_WIDTH, right=False))
            connector = "├─ " if label.plain else "│  "
        if selected:
            line.stylize("reverse")
        if side == LEFT:
            line.append(connector, style="grey62")
            return line
        result = Text(connector, style="grey62")
        result.append_text(line)
        return result

    @staticmethod
    def _pad(text: Text, width: int, right: bool) -> Text:
        text = text.copy()
        text.truncate(width)
        padding = " " * (width - len(text.plain))
        if right:
            return Text(padding) + text
        return text + Text(padding)

    def _body_lines(self, rows: int) -> list[Text]:
        """The text inside the board outline, one line for each pin row."""
        board = self.config.board
        hello = self.state.hello
        words = [
            Text(board.chip.title, style="bold"),
            Text(board.title[:BODY_WIDTH - 2], style="grey62"),
        ]
        if hello is not None:
            words.append(Text(f"agent {hello.agent}", style="grey50"))
        if not self.pin_layout.physical:
            words.append(Text("pin order unknown", style="yellow"))
        lines = [Text("") for _ in range(rows)]
        start = max(0, (rows - len(words)) // 2)
        for index, word in enumerate(words):
            if start + index < rows:
                lines[start + index] = word
        return lines

    def render(self) -> Text:
        rows = self.pin_layout.rows
        side_width = NAME_WIDTH + VALUE_WIDTH + MODE_WIDTH + LABEL_WIDTH + 3 + 3
        # The outline's corner sits on the last character of the pin connector.
        blank = " " * (side_width - 1)
        inner = BODY_WIDTH - 2
        out = Text()
        out.append(blank + "┌" + "─" * inner + "┐\n", style="grey62")
        out.append(blank + "│", style="grey62")
        out.append(" antenna ".center(inner, "~"), style="grey50")
        out.append("│\n", style="grey62")
        body = self._body_lines(rows)
        for row in range(rows):
            out.append_text(self._side_text(LEFT, row))
            centred = body[row].copy()
            centred.truncate(inner)
            left_pad = (inner - len(centred.plain)) // 2
            out.append(" " * left_pad)
            out.append_text(centred)
            out.append(" " * (inner - left_pad - len(centred.plain)))
            out.append_text(self._side_text("right", row))
            out.append("\n")
        out.append(blank + "│" + " " * inner + "│\n", style="grey62")
        out.append(blank + "│", style="grey62")
        out.append("[ USB ]".center(inner), style="grey50")
        out.append("│\n", style="grey62")
        out.append(blank + "└" + "─" * inner + "┘", style="grey62")
        return out

    def selected_text(self) -> Text:
        """One line about the GPIO under the cursor, for the help bar."""
        gpio = self.selected_gpio()
        if gpio is None:
            return Text("No usable GPIO on this board.", style="yellow")
        board = self.config.board
        text = Text(f"GPIO {gpio}", style="bold")
        info = board.pin_info(gpio)
        if info:
            text.append("  " + " · ".join(info), style="grey62")
        return text

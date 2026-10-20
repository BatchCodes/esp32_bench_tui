"""The pin detail view: one GPIO with its live value, a big history chart and
the pin facts. Enter on the Board page or the Pins page opens it."""

from __future__ import annotations

import time

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from bench import board_layout, display

REFRESH_S = 0.1
CHART_HEIGHT = 14
AXIS_WIDTH = 12
SECONDS_PER_SAMPLE_DEFAULT = 0.1


class PinDetail(ModalScreen[None]):
    # A modal screen gets only the priority bindings of the app (tab, left,
    # right), so enter is bound here too.
    BINDINGS = [
        Binding("escape,space,q", "close", "Close"),
        Binding("enter", "app.activate", "Change"),
        Binding("z", "zoom", "Zoom"),
    ]

    DEFAULT_CSS = """
    PinDetail {
        align: center middle;
    }
    #detail {
        width: 90%;
        height: auto;
        max-height: 90%;
        border: round $primary;
        background: $surface;
        padding: 0 1;
    }
    """

    def __init__(self, gpio: int) -> None:
        super().__init__()
        self.gpio = gpio
        # False: the fixed scale of the pin type (0 to 3150 mV for an ADC).
        # True: the chart scales to its own values, to show small changes.
        self.zoom = False

    def compose(self) -> ComposeResult:
        with Vertical(id="detail"):
            yield Static(id="detail-body")

    def on_mount(self) -> None:
        self.set_interval(REFRESH_S, self.refresh_body)
        self.refresh_body()

    def action_zoom(self) -> None:
        self.zoom = not self.zoom
        self.refresh_body()

    def action_close(self) -> None:
        self.app.pop_screen()

    def _chart_width(self) -> int:
        width = self.query_one("#detail-body", Static).size.width
        return max(20, (width or 80) - AXIS_WIDTH - 2)

    def refresh_body(self) -> None:
        app = self.app
        config = app.config
        state = app.state
        board = config.board
        used = board_layout.devices_by_gpio(config.devices).get(self.gpio)
        text = Text()
        text.append(f"GPIO {self.gpio}", style="bold")
        label = board.labels.get(self.gpio)
        if label:
            text.append(f" ({label})", style="bold")
        if used is None:
            text.append("  free\n\n", style="grey50")
            text.append("No device on this pin. Tab gives it the first pin mode, a adds another type.\n", style="grey62")
            self._append_facts(text)
            self.query_one("#detail-body", Static).update(text)
            return
        device, role = used
        text.append(f"  {device.name}  ", style="bold cyan")
        text.append(f"{device.type}{'' if role == 'gpio' else ' ' + role}\n\n", style="grey62")

        value = state.values.get(device.name)
        age = state.updated.get(device.name)
        age_s = None if age is None else time.monotonic() - age
        value_text = board_layout.pin_value_text(
            device, role, value, state.humidity.get(device.name), state.edge_rates.get(device.name)
        )
        text.append("Value  ", style="grey62")
        text.append(value_text, style="bold " + ("" if display.staleness(age_s) == "fresh" else "grey50"))
        if age_s is not None:
            text.append(f"   {age_s:.1f} s ago", style="grey50")
        edges = state.edges.get(device.name)
        if edges is not None:
            text.append(f"   {edges} level changes", style="grey62")
        error = state.config_errors.get(device.name)
        if error:
            text.append(f"   error: {error}", style="red")
        text.append("\n\n")

        if device.type == "hx711":
            self._hx711_body(text, device)
            self._append_facts(text)
            self.query_one("#detail-body", Static).update(text)
            return

        samples = state.history.get(device.name, [])
        scale = None if self.zoom else display.graph_scale(device)
        rows, low, high = display.chart_lines(samples, self._chart_width(), CHART_HEIGHT, scale)
        if rows:
            seconds = len(samples[-self._chart_width():]) * config.report_period_ms / 1000.0
            high_text = display.format_value(device, high) if device.mode not in ("digital_in", "digital_out") else "1"
            low_text = display.format_value(device, low) if device.mode not in ("digital_in", "digital_out") else "0"
            for index, row in enumerate(rows):
                axis = high_text if index == 0 else low_text if index == len(rows) - 1 else ""
                text.append(f"{axis:>{AXIS_WIDTH}} ", style="grey62")
                text.append("│", style="grey50")
                text.append(row + "\n", style="cyan")
            text.append(" " * AXIS_WIDTH + " └" + "─" * len(rows[0]) + "\n", style="grey50")
            if display.graph_scale(device) is None:
                scale_text = "scale: auto"
            else:
                scale_text = "scale: zoom (z for the fixed scale)" if self.zoom else "scale: fixed (z to zoom)"
            text.append(" " * AXIS_WIDTH + f"  last {seconds:.0f} s · {scale_text}\n\n", style="grey50")
        else:
            text.append("No history yet.\n\n", style="grey50")
        self._append_facts(text)
        self.query_one("#detail-body", Static).update(text)

    def _hx711_body(self, text: Text, device) -> None:
        """Both HX711 channels: ready state, timeouts and a chart each."""
        state = self.app.state
        info = state.hx711.get(device.name)
        tares = self.app._tare.get(device.name, (None, None))
        if info is None:
            text.append("No data from the agent yet.\n\n", style="grey50")
            return
        text.append(f"{info.reads} reads", style="grey62")
        text.append("   tared\n\n" if device.name in self.app._tare else "   raw counts, enter tares\n\n", style="grey62")
        width = self._chart_width()
        for channel, (key, gpio) in enumerate(((device.name, device.gpio2), (f"{device.name}:2", device.gpio3))):
            if channel >= len(info.ready):
                break
            ready = info.ready[channel]
            text.append(f"Channel {channel + 1}", style="bold")
            text.append(f"  data GPIO {gpio}  ", style="grey62")
            if ready:
                text.append("answering", style="green")
            else:
                text.append("not answering: check power, ground and this data wire", style="red")
            text.append(f"   {info.timeouts[channel]} timeouts\n", style="grey62")
            samples = [value - (tares[channel] or 0.0) for value in state.history.get(key, [])]
            rows, low, high = display.chart_lines(samples, width, CHART_HEIGHT // 2)
            for index, row in enumerate(rows):
                axis = f"{high:.0f}" if index == 0 else f"{low:.0f}" if index == len(rows) - 1 else ""
                text.append(f"{axis:>{AXIS_WIDTH}} ", style="grey62")
                text.append("│", style="grey50")
                text.append(row + "\n", style="cyan")
            text.append("\n")

    def _append_facts(self, text: Text) -> None:
        facts = self.app.config.board.pin_info(self.gpio)
        if facts:
            text.append(" · ".join(facts) + "\n", style="grey62")
        text.append("\nenter: on or off, a value, or tare an HX711 · tab: next pin mode · z: zoom · space or escape: close", style="grey50")

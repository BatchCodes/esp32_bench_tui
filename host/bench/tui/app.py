"""The Textual application of the bench host tool.

The pages have one key for each page, a fixed render tick,
a cursor to select an output, and grey or red values when data is old. The app
reads the link state with snapshot() at each tick and never waits for the board.
"""

from __future__ import annotations

import time
from pathlib import Path

from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import DataTable, Footer, Header, Input, RichLog, Static, TabbedContent, Tabs, TabPane

from bench import bus, display, pin_command, radio
from bench.config import (
    GENERIC_PREFIX,
    ConfigError,
    Device,
    ProjectConfig,
    device_entry,
    dump_project,
    load_project,
    project_data,
    project_from_data,
    empty_project,
    with_all_inputs,
    with_board,
    with_device_entries,
)
from bench.link import BaseLink, LinkState, RadioSettings
from bench.tui.board_view import BoardView
from bench.tui.pin_detail import PinDetail
from bench.tui.radio_detail import BLE, WIFI, RadioDetail
from bench import board_layout

RENDER_TICK_S = 0.1
CONFIG_CHECK_S = 1.0
SPARK_WIDTH = 24
RESULT_SHOW_S = 4.0
STALE_STYLES = {"fresh": "", "stale": "grey50", "lost": "red"}
MODE_STYLES = {
    "digital_in": "green",
    "digital_out": "yellow",
    "adc": "magenta",
    "pwm": "cyan",
    "servo": "cyan",
    "log": "blue",
}
LOG_LEVEL_STYLES = {"E": "red", "W": "yellow", "D": "grey50", "V": "grey50", "[": "cyan"}
PIN_COLUMNS = ("Name", "GPIO", "Type", "Value", "Edges", "History", "Age")
WIFI_COLUMNS = (("SSID", 24), ("BSSID", 17), ("Ch", 3), ("RSSI", 8), ("Signal", 16), ("Security", 10), ("802.11", 9), ("Seen", 8))
BLE_COLUMNS = (("Address", 17), ("Name or type", 30), ("RSSI", 8), ("Signal", 12), ("Company", 20), ("Conn", 4), ("Seen", 8))
COLUMN_WIDTHS = {"Name": 24, "GPIO": 13, "Type": 12, "Value": 28, "Edges": 6, "History": SPARK_WIDTH, "Age": 7}


class BenchApp(App):
    CSS_PATH = "app.tcss"
    # The page decides the focus. Automatic focus would pick the hidden input.
    AUTO_FOCUS = None
    TITLE = "bench"
    BINDINGS = [
        Binding("g", "page('board')", "Board"),
        Binding("o", "page('overview')", "Overview"),
        Binding("p", "page('pins')", "Pins"),
        Binding("l", "page('log')", "Log"),
        Binding("b", "page('bus')", "Bus"),
        Binding("w", "page('wifi')", "Wi-Fi"),
        Binding("t", "page('ble')", "Bluetooth"),
        Binding("i", "page('link')", "Link"),
        Binding("s", "scan", "Scan", show=False),
        Binding("n", "sniffer", "Sniffer", show=False),
        Binding("c", "wifi_connect", "Connect", show=False),
        Binding("d", "wifi_disconnect", "Disconnect", show=False),
        Binding("slash", "ble_filter", "Filter", show=False),
        Binding("colon", "command", "Command", show=False),
        Binding("left", "cycle_page(-1)", "Page", priority=True),
        Binding("right", "cycle_page(1)", "Page", show=False, priority=True),
        Binding("tab", "switch_direction", "In/out", priority=True),
        Binding("shift+tab", "focus_page", show=False, priority=True),
        Binding("space", "details", "Details"),
        Binding("a", "add_pin", "Add pin"),
        Binding("x", "remove_log_value", "Remove log value", show=False),
        Binding("ctrl+s", "save_config", "Save"),
        Binding("r", "reset_board", "Reset board"),
        Binding("escape", "cancel_input", "Cancel", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, config: ProjectConfig, link: BaseLink, auto_board: bool = False, watch_all: bool = False) -> None:
        super().__init__()
        self.config = config
        self.link = link
        self.state = LinkState()
        self._config_mtime = self._mtime(config.path)
        # Open mode with no board given: use the generic board of the chip
        # that the agent reports.
        self._auto_board = auto_board
        # Open mode: when the board changes, put an input on each free GPIO again.
        self._watch_all = watch_all and auto_board
        self._log_shown = 0
        self._pending: dict[int, tuple[str, str]] = {}
        self._result_text: Text | None = None
        self._result_time = 0.0
        self._input_device: str | None = None
        self._input_mode = "value"
        self._ble_filter = ""
        self._connect_ssid = ""
        # HX711 tare: the raw value of each channel when enter was pressed.
        self._tare: dict[str, tuple[float | None, float | None]] = {}

    @property
    def main_screen(self):
        """The screen with the pages. A pin detail view can be on top of it,
        and App.query_one would search that view instead."""
        return self.screen_stack[0] if self.screen_stack else self.screen

    def compose(self) -> ComposeResult:
        yield Header()
        listen_only = self.config.mode == "log" and not self.config.log_values
        with TabbedContent(initial="log" if listen_only else "board"):
            with TabPane("Board (g)", id="board"):
                with VerticalScroll(id="board-scroll"):
                    yield BoardView(self.config, id="board-view")
                yield Static(id="board-help")
            with TabPane("Overview (o)", id="overview"):
                with Horizontal():
                    yield Static(id="board-info")
                    with VerticalScroll():
                        yield Static(id="pin-map")
            with TabPane("Pins (p)", id="pins"):
                yield DataTable(id="pin-table", cursor_type="row", zebra_stripes=True)
                yield Static(id="pin-notes")
            with TabPane("Bus (b)", id="bus"):
                with Horizontal():
                    with VerticalScroll(id="i2c-pane"):
                        yield Static(id="i2c-view")
                    with VerticalScroll(id="uart-pane"):
                        yield Static(id="uart-view")
                yield Static(Text(" s: scan all I2C buses · ':' command: " + bus.HELP, style="grey50"), id="bus-help")
            with TabPane("Wi-Fi (w)", id="wifi"):
                yield Static(id="wifi-status")
                with Horizontal(id="wifi-body"):
                    yield DataTable(id="wifi-table", cursor_type="row", zebra_stripes=True)
                    yield Static(id="wifi-channels")
                yield Static(
                    Text(
                        " ↑ ↓: access point · enter: connect, or disconnect · space: details · s: scan on or off · "
                        "n: sniffer on or off · c: connect by SSID · d: disconnect",
                        style="grey50",
                    ),
                    id="wifi-help",
                )
            with TabPane("Bluetooth (t)", id="ble"):
                yield Static(id="ble-status")
                yield DataTable(id="ble-table", cursor_type="row", zebra_stripes=True)
                yield Static(
                    Text(" ↑ ↓: device · space: details · s: scan on or off · /: filter by name, address or type", style="grey50"),
                    id="ble-help",
                )
            with TabPane("Log (l)", id="log"):
                yield RichLog(id="log-view", max_lines=5000, wrap=False, markup=False, highlight=False)
            with TabPane("Link (i)", id="link"):
                yield Static(id="link-info")
        yield Input(id="value-input")
        yield Static(id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.main_screen.query_one("#value-input", Input).display = False
        self._build_table()
        for table_id, columns in (("#wifi-table", WIFI_COLUMNS), ("#ble-table", BLE_COLUMNS)):
            table = self.main_screen.query_one(table_id, DataTable)
            for column, width in columns:
                table.add_column(column, key=column, width=width)
        # Tab must not move the focus to the page selector.
        for tabs in self.main_screen.query(Tabs):
            tabs.can_focus = False
        self._focus_page()
        self.link.start()
        self.set_interval(RENDER_TICK_S, self._tick)
        self.set_interval(CONFIG_CHECK_S, self._check_config)
        self._tick()

    def on_unmount(self) -> None:
        self.link.stop()

    @staticmethod
    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    def _rows(self) -> list[tuple[str, str, str]]:
        """The (name, gpio, type) of each row of the pin table."""
        if self.config.mode == "log":
            return [(value.name, "—", "log") for value in self.config.log_values]
        return [(device.name, str(device.gpio), device.type) for device in self.config.devices]

    def _build_table(self) -> None:
        table = self.main_screen.query_one("#pin-table", DataTable)
        # Keep the cursor on the same device, or on the same row, after a change.
        selected = self._selected_device()
        selected_name = selected.name if selected is not None else None
        selected_row = table.cursor_row
        table.clear(columns=True)
        for column in PIN_COLUMNS:
            table.add_column(column, key=column, width=COLUMN_WIDTHS.get(column))
        for name, gpio, device_type in self._rows():
            device = self.config.device(name)
            gpio = device.gpio_text() if device is not None else gpio
            style = MODE_STYLES.get(self._mode_of(name, device_type), "")
            table.add_row(Text(name, style="bold"), gpio, Text(device_type, style=style), "—", "", "", "", key=name)
        names = [name for name, _gpio, _type in self._rows()]
        if names:
            row = names.index(selected_name) if selected_name in names else min(selected_row, len(names) - 1)
            table.move_cursor(row=max(0, row), animate=False)

    def _mode_of(self, name: str, device_type: str) -> str:
        device = self.config.device(name)
        return device.mode if device is not None else device_type

    def _check_config(self) -> None:
        mtime = self._mtime(self.config.path)
        if mtime == self._config_mtime:
            return
        self._config_mtime = mtime
        try:
            config = load_project(self.config.path)
        except ConfigError as error:
            self._show_result(Text(f"Config not loaded: {'; '.join(error.errors)}", style="red"))
            return
        self.config = config
        self.link.update_config(config)
        self._build_table()
        self._show_result(Text(f"Config loaded from {config.path}, sent to the board", style="green"))

    def _tick(self) -> None:
        try:
            self._render_tick()
        except NoMatches:
            # A timer can fire while the app shuts down and its widgets are gone.
            return

    def _apply_config(self, config: ProjectConfig, message: str) -> None:
        self.config = config
        self.link.update_config(config)
        self._build_table()
        self.main_screen.query_one(BoardView).set_config(config)
        self._show_result(Text(message, style="green"))

    def _match_board_to_chip(self) -> None:
        hello = self.state.hello
        if not self._auto_board or hello is None:
            return
        self._auto_board = False
        if hello.chip == self.config.board.chip.chip:
            return
        try:
            if self._watch_all:
                config = with_all_inputs(empty_project(f"{GENERIC_PREFIX}{hello.chip}", self.config.path))
            else:
                config = with_board(self.config, f"{GENERIC_PREFIX}{hello.chip}")
        except ConfigError as error:
            self._show_result(Text(f"Board is {hello.chip}, but: {'; '.join(error.errors)}", style="red"))
            return
        self._apply_config(config, f"Board reports {hello.chip}: using the generic {hello.chip} board")

    def _entries_with_current_outputs(self) -> list[dict]:
        """The device entries, with each output's current value as its initial
        value, so a new configuration does not reset the outputs."""
        entries = []
        for device in self.config.devices:
            entry = device_entry(device)
            value = self.state.values.get(device.name)
            if device.is_output and isinstance(value, float):
                entry["initial"] = int(value >= 0.5) if device.mode == "digital_out" else value
            entries.append(entry)
        return entries

    def action_add_pin(self) -> None:
        if self.config.mode == "log":
            self._open_input("log_rule", "log value: <name> <regex with one (group)>, for example: heap free heap (\\d+)", password=False)
            return
        value = ""
        if self.main_screen.query_one(TabbedContent).active == "board":
            selected = self._selected_pin()
            if selected is not None:
                value = board_layout.pin_command_for(self.config.board, selected[0], selected[1])
        self._open_input("pin", pin_command.HELP, password=False, value=value)

    def _add_log_rule(self, text: str) -> None:
        parts = text.strip().split(None, 1)
        if len(parts) != 2:
            self._show_result(Text("enter a name and a regex, for example: heap free heap (\\d+)", style="red"))
            return
        name, pattern = parts
        data = project_data(self.config)
        rules = [rule for rule in data.get("log_values", []) if rule["name"] != name]
        rules.append({"name": name, "pattern": pattern})
        data["log_values"] = rules
        try:
            config = project_from_data(data, self.config.path)
        except ConfigError as error:
            self._show_result(Text(f"Rule not added: {'; '.join(error.errors)}", style="red"))
            return
        self._apply_config(config, f"Added the log value {name}")
        self.action_page("pins")

    def _add_pin(self, text: str) -> None:
        try:
            entry = pin_command.parse_pin_command(text)
        except pin_command.PinCommandError as error:
            self._show_result(Text(str(error), style="red"))
            return
        entries = pin_command.replace_entry(self._entries_with_current_outputs(), entry)
        try:
            config = with_device_entries(self.config, entries)
        except ConfigError as error:
            self._show_result(Text(f"Pin not added: {'; '.join(error.errors)}", style="red"))
            return
        self._apply_config(config, f"Added {entry['name']} ({entry['type']}), sent to the board")
        if self.main_screen.query_one(TabbedContent).active != "board":
            self.action_page("pins")

    def action_remove_log_value(self) -> None:
        """x in listen mode: remove the selected log value."""
        if self.main_screen.query_one(TabbedContent).active != "pins" or self.config.mode != "log":
            return
        self._remove_log_rule()

    def _remove_log_rule(self) -> None:
        table = self.main_screen.query_one("#pin-table", DataTable)
        if table.row_count == 0:
            return
        name = str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        data = project_data(self.config)
        data["log_values"] = [rule for rule in data.get("log_values", []) if rule["name"] != name]
        self._apply_config(project_from_data(data, self.config.path), f"Removed the log value {name}")

    def action_save_config(self) -> None:
        path = self.config.path
        try:
            path.write_text(dump_project(self.config))
        except OSError as error:
            self._show_result(Text(f"Not saved: {error.strerror}", style="red"))
            return
        self._config_mtime = self._mtime(path)
        self._show_result(Text(f"Saved to {path}", style="green"))

    def _render_tick(self) -> None:
        self.state = self.link.snapshot()
        self._match_board_to_chip()
        self.sub_title = f"{self.config.board.title} · {self.state.port} · {self.state.status}"
        self._update_results()
        active = self.main_screen.query_one(TabbedContent).active
        self._update_table()
        if active == "board":
            self._update_board()
        if active == "overview":
            self._update_overview()
        elif active == "link":
            self._update_link_info()
        elif active == "bus":
            self._update_bus()
        elif active == "wifi":
            self._update_wifi()
        elif active == "ble":
            self._update_ble()
        self._update_log()
        self._update_status_bar()

    def _age(self, name: str, now: float) -> float | None:
        updated = self.state.updated.get(name)
        return None if updated is None else now - updated

    def _update_table(self) -> None:
        table = self.main_screen.query_one("#pin-table", DataTable)
        now = time.monotonic()
        for name, _gpio, _type in self._rows():
            device = self.config.device(name)
            value = self.state.values.get(name)
            age = self._age(name, now)
            style = STALE_STYLES[display.staleness(age)]
            error = self.state.config_errors.get(name)
            if error:
                value_cell = Text(f"error: {error}", style="red")
            else:
                text = self._value_text(device, name, value)
                value_cell = Text(text, style=style or ("bold" if value is not None else ""))
            edges = self.state.edges.get(name)
            spark = display.sparkline(self.state.history.get(name, []), SPARK_WIDTH, display.graph_scale(device))
            age_text = "—" if age is None else f"{age:.1f} s"
            try:
                table.update_cell(name, "Value", value_cell)
                table.update_cell(name, "Edges", "" if edges is None else str(edges))
                table.update_cell(name, "History", Text(spark, style=style or "cyan"))
                table.update_cell(name, "Age", Text(age_text, style=style))
            except Exception:  # noqa: BLE001 - the table is rebuilt after a config reload
                return
        self._update_pin_notes()

    def _value_text(self, device: Device | None, name: str, value: float | str | None) -> str:
        if self.config.mode != "agent" or device is None:
            return self._log_text(name, value)
        if device.type == "counter":
            return display.format_rate(self.state.edge_rates.get(name))
        if device.type == "hx711":
            raw = value if isinstance(value, float) else None
            return display.hx711_text(raw, self.state.hx711.get(name), self._tare.get(name, (None, None)))
        if device.mode in ("dht11", "dht22"):
            return display.format_sensor(device, value, self.state.humidity.get(name))
        return display.format_value(device, value)

    def _devices_of(self, device_type: str) -> list[str]:
        return [device.name for device in self.config.devices if device.type == device_type]

    def _update_bus(self) -> None:
        i2c = Text()
        names = self._devices_of("i2c")
        if not names:
            i2c.append("No i2c device in the configuration.\n", style="grey50")
        for name in names:
            device = self.config.device(name)
            i2c.append(f"{name}", style="bold")
            i2c.append(f"  {device.gpio_text()}, {device.freq_hz // 1000} kHz\n", style="grey50")
            addresses = self.state.i2c_scans.get(name)
            if addresses is None:
                i2c.append("  not scanned yet. Press s.\n", style="yellow")
            elif not addresses:
                i2c.append("  no devices found. Check the wiring and the pull-up resistors.\n", style="yellow")
            for address in addresses or ():
                i2c.append(f"  0x{address:02x}", style="cyan")
                i2c.append(f"  {bus.chip_name(address)}\n")
            i2c.append("\n")
        if self.state.i2c_results:
            i2c.append("Results\n", style="bold")
            for line in self.state.i2c_results[-10:]:
                i2c.append(f"  {line}\n")
        self.main_screen.query_one("#i2c-view", Static).update(i2c)

        uart = Text()
        names = self._devices_of("uart")
        if not names:
            uart.append("No uart device in the configuration.\n", style="grey50")
        for name in names:
            device = self.config.device(name)
            total = self.state.uart_total.get(name, 0)
            uart.append(f"{name}", style="bold")
            uart.append(f"  {device.gpio_text()}, {device.baud} baud, {total} B received\n", style="grey50")
            for line in self.state.uart_lines.get(name, [])[-20:]:
                uart.append(f"  {line}\n")
            uart.append("\n")
        self.main_screen.query_one("#uart-view", Static).update(uart)

    def _log_text(self, name: str, value: float | str | None) -> str:
        rule = next((item for item in self.config.log_values if item.name == name), None)
        if value is None:
            return "—"
        if isinstance(value, str):
            return value
        units = f" {rule.units}" if rule is not None and rule.units else ""
        return f"{value:g}{units}"

    def _selected_device(self) -> Device | None:
        table = self.main_screen.query_one("#pin-table", DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        except Exception:  # noqa: BLE001 - no row under the cursor
            return None
        return self.config.device(str(row_key.value))

    def _update_pin_notes(self) -> None:
        notes = Text()
        device = self._selected_device()
        if device is not None:
            label = self.config.board.labels.get(device.gpio)
            notes.append(f"{device.name}: GPIO {device.gpio}{f' ({label})' if label else ''}", style="bold")
            info = self.config.board.pin_info(device.gpio)
            if info:
                notes.append(" · " + " · ".join(info))
            notes.append("\n")
            if device.is_output and self.link.can_control:
                notes.append("enter: on or off, or type a value · tab: next pin mode · space: details\n", style="grey50")
        if self.config.mode == "log":
            notes.append("Log mode: the board keeps its own firmware. a: add a log value (name and regex) · x: remove it · ctrl+s: save\n", style="grey50")
        elif not self.config.devices and self.config.mode == "agent":
            notes.append("No pins yet. Press a and type a pin, for example: out 4, in 34, adc 32, pwm 13\n", style="cyan")
        else:
            notes.append("a: give a pin another type (I2C, UART, servo, sensor) · ctrl+s: save to ", style="grey50")
            notes.append(f"{self.config.path}\n", style="grey50")
        for warning in self.config.warnings:
            notes.append(f"warning: {warning}\n", style="yellow")
        self.main_screen.query_one("#pin-notes", Static).update(notes)

    def _update_overview(self) -> None:
        hello = self.state.hello
        info = Text()
        board = self.config.board
        info.append(f"{board.title}\n", style="bold")
        info.append(f"profile {board.name}{'' if board.verified else ' (not verified)'}\n", style="grey50")
        info.append(f"chip {board.chip.title}, {board.flash_mb} MB flash, {board.psram_mb} MB PSRAM\n")
        info.append(f"{board.usb}\n\n", style="grey50")
        if hello is None:
            info.append("No hello from the bench agent yet.\n" if self.config.mode == "agent" else "Log mode.\n", style="yellow")
        else:
            info.append(f"agent {hello.agent}, protocol {hello.protocol}\n")
            info.append(f"chip {hello.chip} rev {hello.revision // 100}.{hello.revision % 100}, {hello.cores} cores\n")
            info.append(f"MAC {hello.mac}\nflash {hello.flash_mb} MB\n")
            info.append(f"uptime {display.format_duration(self.state.uptime_ms)}\n")
            info.append(f"free heap {self.state.free_heap // 1024} kB\n")
        self.main_screen.query_one("#board-info", Static).update(info)
        self.main_screen.query_one("#pin-map", Static).update(self._pin_map())

    def _pin_map(self) -> Table:
        board = self.config.board
        by_gpio = {gpio: device for device in self.config.devices for gpio in device.gpios}
        blocked = board.never_usable()
        table = Table(box=None, pad_edge=False, expand=True)
        for column in ("GPIO", "Label", "Use", "Value", "Notes"):
            table.add_column(column, no_wrap=column != "Notes")
        now = time.monotonic()
        for gpio in sorted(board.chip.gpios):
            if gpio not in board.pins and gpio not in board.reserved:
                continue
            device = by_gpio.get(gpio)
            facts = board.pin_info(gpio)
            if device is not None:
                style = MODE_STYLES.get(device.mode, "")
                age = self._age(device.name, now)
                value = Text(
                    self._value_text(device, device.name, self.state.values.get(device.name)),
                    style=STALE_STYLES[display.staleness(age)] or "bold",
                )
                role = next(role for pin, role, _output in device.gpio_roles() if pin == gpio)
                role_text = "" if role == "gpio" else f" {role}"
                use = Text(f"{device.name} ({device.type}{role_text})", style=style)
            elif gpio in blocked or gpio in board.reserved:
                use = Text("reserved", style="grey50")
                value = Text("")
            else:
                use = Text("free", style="grey50")
                value = Text("")
            marker = " !" if gpio in board.chip.strapping else ""
            table.add_row(
                f"{gpio}{marker}",
                board.label(gpio),
                use,
                value,
                Text(" · ".join(facts), style="grey50"),
            )
        return table

    def _update_link_info(self) -> None:
        state = self.state
        now = time.monotonic()
        last_rx = "never" if not state.last_rx else f"{now - state.last_rx:.1f} s ago"
        text = Text()
        text.append(f"mode          {state.mode}\n")
        text.append(f"port          {state.port}\n")
        text.append(f"connected     {'yes' if state.connected else 'no'}\n", style="" if state.connected else "red")
        text.append(f"status        {state.status}\n")
        text.append(f"last receive  {last_rx}\n", style=STALE_STYLES[display.staleness(now - state.last_rx if state.last_rx else None)])
        text.append(f"messages      {state.rx_messages} ({state.message_rate:.1f} per second)\n")
        text.append(f"log lines     {state.rx_log_lines}\n")
        text.append(f"bad lines     {state.bad_lines}\n")
        text.append(f"agent errors  {state.errors}\n")
        text.append(f"watchdog      {state.watchdog_events}\n", style="yellow" if state.watchdog_events else "")
        self.main_screen.query_one("#link-info", Static).update(text)

    def _update_log(self) -> None:
        new_lines = self.state.log_total - self._log_shown
        if new_lines <= 0:
            return
        view = self.main_screen.query_one("#log-view", RichLog)
        for line in self.state.log[-min(new_lines, len(self.state.log)):]:
            view.write(Text(line, style=LOG_LEVEL_STYLES.get(line[:1], "")))
        self._log_shown = self.state.log_total

    def _update_status_bar(self) -> None:
        bar = self.main_screen.query_one("#status-bar", Static)
        if self._result_text is not None and time.monotonic() - self._result_time < RESULT_SHOW_S:
            bar.update(self._result_text)
            return
        connected = self.state.connected
        text = Text(f" {self.state.status}", style="green" if connected and self.state.configured else "yellow")
        if self.config.mode == "log":
            text = Text(f" {self.state.status} · log mode, read-only", style="green" if connected else "yellow")
        bar.update(text)

    def _show_result(self, text: Text) -> None:
        self._result_text = text
        self._result_time = time.monotonic()

    def _update_results(self) -> None:
        for seq in [seq for seq in self._pending if seq in self.state.results]:
            name, value_text = self._pending.pop(seq)
            error = self.state.results[seq]
            label = f"{name} = {value_text}" if value_text else name
            if error is None:
                self._show_result(Text(f"{label}: OK", style="green"))
            else:
                self._show_result(Text(f"{label}: FAILED, {error}", style="red"))

    def _send(self, device: Device, value: float, note: str | None = None) -> None:
        if not self.link.can_control:
            self._show_result(Text("Log mode is read-only. Use the bench agent to control outputs.", style="yellow"))
            return
        seq = self.link.set_output(device.name, value)
        value_text = display.format_value(device, value)
        if seq is None:
            self._show_result(Text(f"{device.name}: not sent, the board is not configured", style="red"))
            return
        self._pending[seq] = (device.name, value_text if note is None else f"{value_text} ({note})")

    def _output_device(self) -> Device | None:
        if self.main_screen.query_one(TabbedContent).active != "pins":
            return None
        device = self._selected_device()
        if device is None or not device.is_output:
            return None
        return device

    def action_page(self, page: str) -> None:
        self.main_screen.query_one(TabbedContent).active = page
        self._focus_page()

    def _update_board(self) -> None:
        view = self.main_screen.query_one(BoardView)
        view.set_state(self.state)
        help_text = view.selected_text()
        help_text.append(
            "\n↑ ↓: pin · enter: on or off, or a value · tab: next pin mode · space: details · a: another pin type · ← →: page",
            style="grey50",
        )
        if self.config.mode == "log":
            help_text.append(" · log mode: read-only", style="yellow")
        self.main_screen.query_one("#board-help", Static).update(help_text)

    def on_board_view_pin_chosen(self, event: BoardView.PinChosen) -> None:
        self.action_activate()

    def action_cycle_page(self, step: int) -> None:
        """Left and right change the page. In the text input they move the cursor."""
        if isinstance(self.screen, PinDetail):
            return
        field = self.main_screen.query_one("#value-input", Input)
        if field.has_focus:
            if step < 0:
                field.action_cursor_left()
            else:
                field.action_cursor_right()
            return
        tabs = self.main_screen.query_one(TabbedContent)
        pages = [pane.id for pane in self.main_screen.query(TabPane)]
        index = pages.index(tabs.active) if tabs.active in pages else 0
        self.action_page(pages[(index + step) % len(pages)])

    def action_focus_page(self) -> None:
        """Tab keeps the focus on the page, not on the page selector."""
        if self.main_screen.query_one("#value-input", Input).has_focus:
            return
        self._focus_page()

    def _selected_pin(self) -> tuple[int, Device | None] | None:
        """The GPIO and device of the pin detail view, the Board page cursor or
        the Pins page row, or None when no pin is selected."""
        if isinstance(self.screen, PinDetail):
            gpio = self.screen.gpio
        else:
            active = self.main_screen.query_one(TabbedContent).active
            if active == "board":
                gpio = self.main_screen.query_one(BoardView).selected_gpio()
            elif active == "pins":
                device = self._selected_device()
                gpio = None if device is None else device.gpio
            else:
                return None
        if gpio is None:
            return None
        used = board_layout.devices_by_gpio(self.config.devices).get(gpio)
        return gpio, (used[0] if used is not None else None)

    def action_details(self) -> None:
        """Space: open the detail view of the selected pin, access point or
        device, or close the detail view that is open."""
        if isinstance(self.screen, (PinDetail, RadioDetail)):
            self.pop_screen()
            return
        active = self.main_screen.query_one(TabbedContent).active
        if active in ("wifi", "ble"):
            key = self._table_key(self.main_screen.query_one(f"#{active}-table", DataTable))
            if key is not None:
                self.push_screen(RadioDetail(WIFI if active == "wifi" else BLE, key))
            return
        selected = self._selected_pin()
        if selected is not None:
            self.push_screen(PinDetail(selected[0]))

    def action_activate(self) -> None:
        """Enter: change the selected thing. Toggle a digital output, ask for a
        PWM or servo value, or connect to or disconnect from an access point."""
        if isinstance(self.screen, RadioDetail):
            if self.screen.kind == WIFI:
                self._connect_to_ap(self.screen.key)
            else:
                self._show_result(Text("A Bluetooth device has nothing to change. Space closes the details.", style="yellow"))
            return
        active = self.main_screen.query_one(TabbedContent).active
        if not isinstance(self.screen, PinDetail) and active == "wifi":
            key = self._table_key(self.main_screen.query_one("#wifi-table", DataTable))
            if key is not None:
                self._connect_to_ap(key)
            return
        if not isinstance(self.screen, PinDetail) and active == "ble":
            self._show_result(Text("A Bluetooth device has nothing to change. Space shows its details.", style="yellow"))
            return
        selected = self._selected_pin()
        if selected is None:
            return
        gpio, device = selected
        if self.config.mode == "log":
            self._show_result(Text("Log mode is read-only.", style="yellow"))
            return
        if device is not None and device.type == "hx711":
            self._tare_hx711(device)
            return
        if device is None or not device.is_output:
            self._show_result(Text(f"GPIO {gpio} is an input. Tab changes the pin mode, space shows its details.", style="yellow"))
            return
        if device.mode == "digital_out":
            self._send(device, display.toggle_value(device, self._current(device)))
            return
        if isinstance(self.screen, PinDetail):
            self.pop_screen()
        self._prompt_value(device)

    def _tare_hx711(self, device: Device) -> None:
        """Enter on an HX711: take the current raw values as zero. Enter again
        while it is tared: clear the tare."""
        if device.name in self._tare:
            del self._tare[device.name]
            self._show_result(Text(f"{device.name}: tare cleared, raw values", style="green"))
            return
        raw1 = self.state.values.get(device.name)
        info = self.state.hx711.get(device.name)
        raw2 = info.raw2 if info is not None else None
        if not isinstance(raw1, float) or raw1 != raw1:
            self._show_result(Text(f"{device.name}: no data to tare yet", style="yellow"))
            return
        self._tare[device.name] = (raw1, raw2 if raw2 is not None and raw2 == raw2 else None)
        self._show_result(Text(f"{device.name}: tared. The values are now counts since the tare. Enter again clears it.", style="green"))

    def action_switch_direction(self) -> None:
        """Tab: switch the selected GPIO between input and output."""
        if self.main_screen.query_one("#value-input", Input).has_focus:
            return
        selected = self._selected_pin()
        if selected is None:
            return
        if self.config.mode == "log":
            self._show_result(Text("Log mode is read-only.", style="yellow"))
            return
        gpio, device = selected
        try:
            entry = board_layout.next_mode_entry(self.config.board, gpio, device)
        except board_layout.SwitchError as error:
            self._show_result(Text(str(error), style="yellow"))
            return
        entries = pin_command.replace_entry(self._entries_with_current_outputs(), entry)
        try:
            config = with_device_entries(self.config, entries)
        except ConfigError as error:
            self._show_result(Text(f"Not switched: {'; '.join(error.errors)}", style="red"))
            return
        modes = board_layout.pin_modes(self.config.board, gpio)
        cycle = " → ".join(board_layout.MODE_NAMES[mode] for mode in modes)
        self._apply_config(config, f"GPIO {gpio} is now {board_layout.MODE_NAMES[entry['type']]}  ({cycle})")

    def _current(self, device: Device) -> float | None:
        value = self.state.values.get(device.name)
        return value if isinstance(value, float) else None

    def action_reset_board(self) -> None:
        self.link.reset_board()
        self._show_result(Text("Board reset through RTS", style="yellow"))

    def action_scan(self) -> None:
        active = self.main_screen.query_one(TabbedContent).active
        if active == "bus":
            for name in self._devices_of("i2c"):
                self._send_bus(bus.BusCommand(action="scan", target=name))
        elif active == "wifi":
            current = self.link.radio_settings()
            period = 0 if current.wifi_scan_ms else radio.WIFI_SCAN_PERIOD_MS
            self._send_radio(RadioSettings(period, current.sniffer, current.ble_scan), "Wi-Fi scan")
        elif active == "ble":
            current = self.link.radio_settings()
            self._send_radio(RadioSettings(current.wifi_scan_ms, current.sniffer, not current.ble_scan), "BLE scan")

    def action_sniffer(self) -> None:
        if self.main_screen.query_one(TabbedContent).active != "wifi":
            return
        current = self.link.radio_settings()
        self._send_radio(RadioSettings(current.wifi_scan_ms, not current.sniffer, current.ble_scan), "channel sniffer")

    def _send_radio(self, settings: RadioSettings, label: str) -> None:
        if not self.link.can_control:
            self._show_result(Text("Log mode is read-only.", style="yellow"))
            return
        seq = self.link.set_radio(settings)
        if seq is None:
            self._show_result(Text(f"{label}: not sent, the board is not configured", style="red"))
            return
        self._pending[seq] = (label, "")

    def action_wifi_connect(self) -> None:
        if self.main_screen.query_one(TabbedContent).active != "wifi" or not self.link.can_control:
            return
        self._open_input("wifi_ssid", "SSID of the access point, enter to continue, escape to cancel", password=False)

    def action_wifi_disconnect(self) -> None:
        if self.main_screen.query_one(TabbedContent).active != "wifi":
            return
        seq = self.link.wifi_disconnect()
        if seq is not None:
            self._pending[seq] = ("Wi-Fi disconnect", "")

    def action_ble_filter(self) -> None:
        if self.main_screen.query_one(TabbedContent).active != "ble":
            return
        self._open_input("ble_filter", "name or address filter, empty for all", password=False, value=self._ble_filter)

    def _open_input(self, mode: str, placeholder: str, password: bool, value: str = "") -> None:
        field = self.main_screen.query_one("#value-input", Input)
        field.placeholder = placeholder
        field.password = password
        field.value = value
        field.display = True
        field.focus()
        self._input_mode = mode

    def _update_wifi(self) -> None:
        state = self.state
        now = time.monotonic()
        text = Text()
        settings = state.radio
        text.append("Station  ", style="bold")
        status = state.wifi_status
        if status is None:
            text.append("off. Select an access point and press space, or press c.", style="grey50")
        else:
            style = {"connected": "green", "connecting": "yellow", "failed": "red"}.get(status.state, "")
            text.append(f"{status.state}", style=style)
            if status.ssid:
                text.append(f"  {status.ssid}")
            if status.state == "connected":
                text.append(f"  {status.ip}  channel {status.channel}  ")
                text.append(f"{status.rssi} dBm", style=radio.rssi_style(status.rssi))
                text.append("  " + display.sparkline(state.wifi_rssi, 40, (radio.RSSI_FLOOR, radio.RSSI_CEILING)), style="cyan")
            if status.reason:
                text.append(f"  reason {status.reason}", style="red")
        scan_age = f", last scan {now - state.wifi_scan_time:.0f} s ago" if state.wifi_scan_time else ""
        text.append("\nAccess points  ", style="bold")
        text.append(f"scan {'on' if settings.wifi_scan_ms else 'off (press s)'}{scan_age}", style="grey50")
        self.main_screen.query_one("#wifi-status", Static).update(text)

        rows = []
        for bssid, seen in sorted(state.wifi_seen.items(), key=lambda item: -item[1].item.rssi):
            ap = seen.item
            age = now - seen.last_seen
            stale = display.staleness(age if age > 2 * settings.wifi_scan_ms / 1000 else 0.0)
            rows.append(
                (
                    bssid,
                    (
                        Text(ap.ssid, style="bold") if ap.ssid else Text("(hidden)", style="grey50"),
                        ap.bssid,
                        str(ap.channel),
                        Text(f"{ap.rssi} dBm", style=radio.rssi_style(ap.rssi)),
                        Text(radio.bar(radio.rssi_fraction(ap.rssi), 16), style=radio.rssi_style(ap.rssi)),
                        ap.auth,
                        radio.phy_text(ap.phy),
                        Text(f"{age:.0f} s", style=STALE_STYLES[stale]),
                    ),
                )
            )
        self._sync_table(self.main_screen.query_one("#wifi-table", DataTable), WIFI_COLUMNS, rows)
        self.main_screen.query_one("#wifi-channels", Static).update(self._channel_text())

    def _channel_text(self) -> Text:
        state = self.state
        text = Text("Channel activity  ", style="bold")
        text.append(f"sniffer {'on' if state.radio.sniffer else 'off (press n)'}\n", style="grey50")
        counts = state.wifi_channels
        if not counts:
            return text
        top = max(max(counts), 1)
        for index, count in enumerate(counts, start=1):
            text.append(f"ch {index:2d} ")
            text.append(radio.bar(count / top, 20), style="cyan")
            text.append(f" {count}\n")
        return text

    def _update_ble(self) -> None:
        state = self.state
        now = time.monotonic()
        text = Text("Bluetooth Low Energy  ", style="bold")
        age = f", updated {now - state.ble_time:.0f} s ago" if state.ble_time else ""
        scan = "off (press s)" if not state.radio.ble_scan else ("active" if state.radio.ble_active else "passive")
        text.append(f"scan {scan}{age}, {len(state.ble_seen)} devices in the last 60 s", style="grey50")
        if self._ble_filter:
            text.append(f"  filter '{self._ble_filter}'", style="yellow")
        self.main_screen.query_one("#ble-status", Static).update(text)

        rows = []
        for address, seen in sorted(state.ble_seen.items(), key=lambda item: -item[1].item.rssi):
            device = seen.item
            hint = radio.device_hint(device)
            if not radio.matches(device.name or hint, address, self._ble_filter):
                continue
            seen_age = now - seen.last_seen
            name = Text(device.name, style="bold") if device.name else Text(hint or "—", style="grey62")
            rows.append(
                (
                    address,
                    (
                        address,
                        name,
                        Text(f"{device.rssi} dBm", style=radio.rssi_style(device.rssi)),
                        Text(radio.bar(radio.rssi_fraction(device.rssi), 12), style=radio.rssi_style(device.rssi)),
                        radio.company_name(device.company_id),
                        "yes" if device.connectable else "",
                        Text(f"{seen_age:.0f} s", style=STALE_STYLES[display.staleness(seen_age / 5)]),
                    ),
                )
            )
        self._sync_table(self.main_screen.query_one("#ble-table", DataTable), BLE_COLUMNS, rows)

    def action_command(self) -> None:
        if self.main_screen.query_one(TabbedContent).active != "bus":
            return
        field = self.main_screen.query_one("#value-input", Input)
        field.placeholder = bus.HELP
        field.value = ""
        field.display = True
        field.focus()
        self._input_mode = "bus"

    def _send_bus(self, command: bus.BusCommand) -> None:
        if not self.link.can_control:
            self._show_result(Text("Log mode is read-only.", style="yellow"))
            return
        if command.action == "scan":
            seq = self.link.i2c_scan(command.target)
            label = f"{command.target}: scan"
        elif command.action == "read":
            seq = self.link.i2c_read(command.target, command.address, command.register, command.length)
            label = f"{command.target}: read 0x{command.address:02x}"
        elif command.action == "write":
            seq = self.link.i2c_write(command.target, command.address, command.register, command.data)
            label = f"{command.target}: write 0x{command.address:02x}"
        else:
            seq = self.link.uart_send(command.target, command.data)
            label = f"{command.target}: send {len(command.data)} B"
        if seq is None:
            self._show_result(Text(f"{label}: not sent, the board is not configured", style="red"))
            return
        self._pending[seq] = (label, "")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # Enter on a row changes it. Space shows the details.
        self.action_activate()

    @staticmethod
    def _table_key(table: DataTable) -> str | None:
        if table.row_count == 0:
            return None
        try:
            return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        except Exception:  # noqa: BLE001 - no row under the cursor
            return None

    def _sync_table(self, table: DataTable, columns, rows: list[tuple[str, tuple]]) -> None:
        """Shows rows in table. Updates the cells when the rows are the same,
        else builds the table again with the cursor on the same key."""
        keys = [key for key, _cells in rows]
        current = [str(row_key.value) for row_key in table.rows]
        column_keys = [name for name, _width in columns]
        if keys == current:
            for key, cells in rows:
                for column, cell in zip(column_keys, cells):
                    table.update_cell(key, column, cell)
            return
        selected = self._table_key(table)
        selected_row = table.cursor_row
        table.clear()
        for key, cells in rows:
            table.add_row(*cells, key=key)
        if keys:
            row = keys.index(selected) if selected in keys else min(selected_row, len(keys) - 1)
            table.move_cursor(row=max(0, row), animate=False)

    def _connect_to_ap(self, bssid: str) -> None:
        seen = self.state.wifi_seen.get(bssid)
        if seen is None:
            return
        ap = seen.item
        status = self.state.wifi_status
        if status is not None and ap.ssid and status.ssid == ap.ssid and status.state in ("connected", "connecting"):
            seq = self.link.wifi_disconnect()
            if seq is not None:
                self._pending[seq] = (f"Wi-Fi disconnect from {ap.ssid}", "")
            return
        if isinstance(self.screen, RadioDetail):
            self.pop_screen()
        if not ap.ssid:
            self._show_result(Text("This network hides its SSID. Press c and type the SSID.", style="yellow"))
            return
        self._connect_ssid = ap.ssid
        if ap.auth == "open":
            seq = self.link.wifi_connect(ap.ssid, "")
            if seq is not None:
                self._pending[seq] = (f"Wi-Fi connect to {ap.ssid}", "")
            return
        self._open_input("wifi_password", f"password for {ap.ssid} ({ap.auth}), enter to connect, escape to cancel", password=True)

    def _prompt_value(self, device: Device) -> None:
        hints = {"digital_out": "0 or 1", "pwm": "a duty below 1 (0.25) or a percentage from 1 to 100 (25)", "servo": "angle 0-180"}
        self._open_input("value", f"{device.name}: {hints[device.mode]}. space or enter sends, empty or escape closes", password=False)
        self._input_device = device.name

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit_input(event.value)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Space in the value prompt sends the value and closes the prompt. A
        value never has a space in it."""
        if self._input_mode == "value" and " " in event.value:
            self._submit_input(event.value.replace(" ", ""))

    def _submit_input(self, value: str) -> None:
        # An empty prompt closes and sends nothing.
        if not value.strip() and self._input_mode in ("value", "pin", "log_rule", "bus"):
            self.action_cancel_input()
            return
        if self._input_mode == "pin":
            text = value
            self.action_cancel_input()
            self._add_pin(text)
            return
        if self._input_mode == "log_rule":
            text = value
            self.action_cancel_input()
            self._add_log_rule(text)
            return
        if self._input_mode == "wifi_ssid":
            ssid = value.strip()
            self.action_cancel_input()
            if not ssid:
                return
            self._connect_ssid = ssid
            self._open_input("wifi_password", f"password for {ssid}, empty for an open network", password=True)
            return
        if self._input_mode == "wifi_password":
            password = value
            self.action_cancel_input()
            seq = self.link.wifi_connect(self._connect_ssid, password)
            if seq is None:
                self._show_result(Text("Wi-Fi connect: not sent, the board is not configured", style="red"))
            else:
                self._pending[seq] = (f"Wi-Fi connect to {self._connect_ssid}", "")
            return
        if self._input_mode == "ble_filter":
            self._ble_filter = value.strip()
            self.action_cancel_input()
            return
        if self._input_mode == "bus":
            self.action_cancel_input()
            try:
                command = bus.parse_command(value, self._devices_of("i2c"), self._devices_of("uart"))
            except bus.CommandError as error:
                self._show_result(Text(str(error), style="red"))
                return
            self._send_bus(command)
            return
        device = self.config.device(self._input_device or "")
        self.action_cancel_input()
        if device is None:
            return
        try:
            value, note = display.parse_output_text(device, value)
        except ValueError as error:
            self._show_result(Text(f"{device.name}: {error}", style="red"))
            return
        self._send(device, value, note)

    def action_cancel_input(self) -> None:
        field = self.main_screen.query_one("#value-input", Input)
        field.display = False
        field.password = False
        field.value = ""
        self._input_device = None
        self._input_mode = "value"
        self._focus_page()

    def _focus_page(self) -> None:
        """Gives the focus to the main widget of the active page."""
        active = self.main_screen.query_one(TabbedContent).active
        if active == "pins":
            self.main_screen.query_one("#pin-table", DataTable).focus()
        elif active == "board":
            self.main_screen.query_one(BoardView).focus()
        elif active == "log":
            self.main_screen.query_one("#log-view", RichLog).focus()
        elif active in ("wifi", "ble"):
            self.main_screen.query_one(f"#{active}-table", DataTable).focus()
        else:
            # Nothing to focus. The hidden input must not take the keys.
            self.set_focus(None)

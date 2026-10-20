"""The detail view of one Wi-Fi access point or one BLE device. Enter on a row
of the Wi-Fi page or the Bluetooth page opens it."""

from __future__ import annotations

import time

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from bench import display, radio

REFRESH_S = 0.5
CHART_HEIGHT = 8
AXIS_WIDTH = 9
RSSI_SCALE = (float(radio.RSSI_FLOOR), float(radio.RSSI_CEILING))
WIFI = "wifi"
BLE = "ble"


class RadioDetail(ModalScreen[None]):
    # A modal screen gets only the priority bindings of the app, so enter is
    # bound here: it connects to the access point, or disconnects from it.
    BINDINGS = [
        Binding("escape,space,q", "close", "Close"),
        Binding("enter", "app.activate", "Change"),
    ]

    DEFAULT_CSS = """
    RadioDetail {
        align: center middle;
    }
    #radio-detail {
        width: 90%;
        height: auto;
        max-height: 90%;
        border: round $primary;
        background: $surface;
        padding: 0 1;
    }
    """

    def __init__(self, kind: str, key: str) -> None:
        super().__init__()
        self.kind = kind
        self.key = key

    def compose(self) -> ComposeResult:
        with Vertical(id="radio-detail"):
            yield Static(id="radio-detail-body")

    def on_mount(self) -> None:
        self.set_interval(REFRESH_S, self.refresh_body)
        self.refresh_body()

    def action_close(self) -> None:
        self.app.pop_screen()

    def _field(self, text: Text, name: str, value: str, style: str = "") -> None:
        if not value:
            return
        text.append(f"{name:<14}", style="grey62")
        text.append(value + "\n", style=style)

    def refresh_body(self) -> None:
        state = self.app.state
        table = state.wifi_seen if self.kind == WIFI else state.ble_seen
        seen = table.get(self.key)
        text = Text()
        if seen is None:
            text.append(f"{self.key} is gone. The board has not seen it for 60 s.\n", style="yellow")
            text.append("\nspace or escape: close", style="grey50")
            self.query_one("#radio-detail-body", Static).update(text)
            return
        age = time.monotonic() - seen.last_seen
        if self.kind == WIFI:
            self._wifi_fields(text, seen.item)
        else:
            self._ble_fields(text, seen.item)
        self._field(text, "Seen", f"{age:.1f} s ago, first {time.monotonic() - seen.first_seen:.0f} s ago")
        text.append("\n")
        rows, _low, _high = display.chart_lines(seen.rssi, 60, CHART_HEIGHT, RSSI_SCALE)
        for index, row in enumerate(rows):
            axis = f"{radio.RSSI_CEILING} dBm" if index == 0 else f"{radio.RSSI_FLOOR} dBm" if index == len(rows) - 1 else ""
            text.append(f"{axis:>{AXIS_WIDTH}} ", style="grey62")
            text.append("│", style="grey50")
            text.append(row + "\n", style="cyan")
        if rows:
            text.append(" " * AXIS_WIDTH + f"  RSSI of the last {len(seen.rssi)} scans\n", style="grey50")
        hint = "enter: connect, or disconnect · space or escape: close" if self.kind == WIFI else "space or escape: close"
        text.append("\n" + hint, style="grey50")
        self.query_one("#radio-detail-body", Static).update(text)

    def _wifi_fields(self, text: Text, ap) -> None:
        text.append((ap.ssid or "(hidden network)") + "\n\n", style="bold")
        self._field(text, "BSSID", ap.bssid)
        self._field(text, "RSSI", f"{ap.rssi} dBm", radio.rssi_style(ap.rssi))
        self._field(text, "Channel", f"{ap.channel}, {radio.ap_width(ap.second)}")
        self._field(text, "Security", ap.auth + ("" if ap.auth != "open" else ", no password"))
        self._field(text, "802.11", radio.phy_text(ap.phy))
        self._field(text, "WPS", "on" if ap.wps else "off")
        status = self.app.state.wifi_status
        if status is not None and status.state == "connected" and status.ssid == ap.ssid:
            self._field(text, "Board", f"connected, IP {status.ip}", "green")

    def _ble_fields(self, text: Text, device) -> None:
        title = device.name or radio.device_hint(device) or "(no name)"
        text.append(title + "\n", style="bold" if device.name else "bold grey62")
        if not device.name:
            text.append("The device sends no name. The title comes from its advertisement.\n", style="grey50")
        text.append("\n")
        self._field(text, "Address", f"{device.address}  ({radio.address_kind(device.address, device.address_type)})")
        self._field(text, "RSSI", f"{device.rssi} dBm", radio.rssi_style(device.rssi))
        if device.tx_power is not None:
            # The path loss gives a rough idea of the distance.
            self._field(text, "TX power", f"{device.tx_power} dBm, path loss {device.tx_power - device.rssi} dB")
        self._field(text, "Connectable", "yes" if device.connectable else "no (beacon or broadcast only)")
        self._field(text, "Company", radio.company_name(device.company_id))
        self._field(text, "Advertises", radio.manufacturer_hint(device.company_id, device.manufacturer))
        self._field(text, "Appearance", radio.appearance_name(device.appearance))
        self._field(text, "Services", ", ".join(radio.service_name(uuid) for uuid in device.services))
        if device.manufacturer:
            self._field(text, "Manufacturer", device.manufacturer.hex(" "), "grey62")
        self._field(text, "Packets", str(device.adv_count))

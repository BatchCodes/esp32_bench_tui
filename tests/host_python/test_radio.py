"""Tests for the Wi-Fi and Bluetooth helpers and messages."""

import unittest

from tests.host_python import host_path  # noqa: F401
from bench import protocol, radio
from bench.config import load_project
from bench.link import AgentLink, RadioSettings
from bench.simulator import SimulatedTransport
from tests.host_python.test_link import EXAMPLES_DIR, wait_for


class RadioHelperTests(unittest.TestCase):
    def test_bar(self) -> None:
        self.assertEqual(radio.bar(1.0, 4), "████")
        self.assertEqual(radio.bar(0.0, 4), "    ")
        self.assertEqual(radio.bar(0.5, 4), "██  ")
        self.assertEqual(len(radio.bar(0.33, 10)), 10)

    def test_rssi(self) -> None:
        self.assertEqual(radio.rssi_style(-50), "green")
        self.assertEqual(radio.rssi_style(-70), "yellow")
        self.assertEqual(radio.rssi_style(-90), "red")
        self.assertAlmostEqual(radio.rssi_fraction(-65), 0.5)

    def test_company_and_filter(self) -> None:
        self.assertEqual(radio.company_name(0x004C), "Apple")
        self.assertEqual(radio.company_name(0x1234), "0x1234")
        self.assertEqual(radio.company_name(-1), "")
        self.assertTrue(radio.matches("Ruuvi 1A2B", "d4:11", "ruuvi"))
        self.assertTrue(radio.matches("", "d4:11:22", "D4:11"))
        self.assertFalse(radio.matches("Tag", "c0:01", "ruuvi"))
        self.assertTrue(radio.matches("Tag", "c0:01", ""))

    def test_parse_radio_messages(self) -> None:
        scan = protocol.parse_line('{"type":"wifi_scan_result","seq":0,"aps":[{"ssid":"a","bssid":"b","channel":6,"rssi":-50,"auth":"wpa2"}]}')
        self.assertEqual(scan.aps[0], protocol.WifiAp("a", "b", 6, -50, "wpa2"))
        status = protocol.parse_line('{"type":"wifi_status","seq":0,"state":"failed","ssid":"x","ip":"","rssi":0,"channel":0,"reason":"201"}')
        self.assertEqual((status.state, status.reason), ("failed", "201"))
        channels = protocol.parse_line('{"type":"wifi_channels","seq":0,"period_ms":1300,"counts":[1,2,3]}')
        self.assertEqual(channels.counts, (1, 2, 3))
        ble = protocol.parse_line('{"type":"ble_devices","seq":0,"devices":[{"address":"c0","name":"","rssi":-70,"company_id":-1,"age_ms":5}]}')
        self.assertEqual(ble.devices[0].company_id, -1)


class DecodeTests(unittest.TestCase):
    def test_ibeacon(self) -> None:
        data = bytes.fromhex("4c0002151122334455667788990011223344556600010002c5")
        hint = radio.manufacturer_hint(0x004C, data)
        self.assertTrue(hint.startswith("iBeacon 11223344-5566-7788-9900-112233445566"), hint)
        self.assertIn("major 1 minor 2", hint)

    def test_apple_and_microsoft(self) -> None:
        self.assertEqual(radio.manufacturer_hint(0x004C, bytes.fromhex("4c001005")), "Nearby Info (iPhone, iPad, Mac)")
        self.assertEqual(radio.manufacturer_hint(0x004C, bytes.fromhex("4c0012")), "Find My (AirTag, offline finding)")
        self.assertIn("Microsoft", radio.manufacturer_hint(0x0006, bytes.fromhex("06000109")))
        self.assertEqual(radio.manufacturer_hint(0x0499, bytes.fromhex("990405")), "")

    def test_device_hint(self) -> None:
        device = protocol.BleDevice("e8:66", "", -80, -1, 0, services=(0xFD6F,))
        self.assertEqual(radio.device_hint(device), "Exposure Notification")
        device = protocol.BleDevice("c0:01", "", -80, 0x004C, 0, manufacturer=bytes.fromhex("4c0002151122334455667788990011223344556600010002c5"))
        self.assertEqual(radio.device_hint(device), "iBeacon")
        device = protocol.BleDevice("c0:01", "", -80, 0x0499, 0)
        self.assertEqual(radio.device_hint(device), "Ruuvi Innovations")
        device = protocol.BleDevice("c0:01", "", -80, -1, 0, appearance=0x00C1)
        self.assertEqual(radio.device_hint(device), "watch")

    def test_address_kind(self) -> None:
        self.assertEqual(radio.address_kind("d4:11:22:33:44:55", 0), "public")
        self.assertEqual(radio.address_kind("c0:01:02:03:04:05", 1), "random static")
        self.assertEqual(radio.address_kind("5a:33:44:55:66:77", 1), "random private, changes")

    def test_ap_text(self) -> None:
        self.assertEqual(radio.phy_text("bgnx"), "b/g/n/ax")
        self.assertEqual(radio.ap_width("none"), "20 MHz")
        self.assertEqual(radio.ap_width("above"), "40 MHz (second channel above)")


class RadioLinkTests(unittest.TestCase):
    def test_radio_resent_after_restart(self) -> None:
        config = load_project(EXAMPLES_DIR / "led_button.yaml")
        transport = SimulatedTransport()
        link = AgentLink(transport, config)
        link.start()
        try:
            self.assertTrue(wait_for(lambda: link.snapshot().configured))
            self.assertIsNotNone(link.set_radio(RadioSettings(ble_scan=True)))
            self.assertTrue(wait_for(lambda: link.snapshot().ble_devices))
            link.reset_board()
            self.assertTrue(wait_for(lambda: transport._radio.get("ble_scan") is True))
        finally:
            link.stop()

    def test_wifi_connect_unknown_network_fails(self) -> None:
        config = load_project(EXAMPLES_DIR / "led_button.yaml")
        link = AgentLink(SimulatedTransport(), config)
        link.start()
        try:
            self.assertTrue(wait_for(lambda: link.snapshot().configured))
            link.wifi_connect("nowhere", "x")
            self.assertTrue(wait_for(lambda: link.snapshot().wifi_status is not None and link.snapshot().wifi_status.state == "failed"))
        finally:
            link.stop()


if __name__ == "__main__":
    unittest.main()

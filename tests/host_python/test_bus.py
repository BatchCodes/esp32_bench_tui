"""Tests for the Bus page command parser."""

import unittest

from tests.host_python import host_path  # noqa: F401
from bench.bus import BusCommand, CommandError, chip_name, parse_command


class BusCommandTests(unittest.TestCase):
    def test_scan(self) -> None:
        self.assertEqual(parse_command("scan", ["i2c"], []), BusCommand(action="scan", target="i2c"))
        self.assertEqual(parse_command("scan b", ["a", "b"], []).target, "b")
        with self.assertRaises(CommandError):
            parse_command("scan", ["a", "b"], [])
        with self.assertRaises(CommandError):
            parse_command("scan", [], [])

    def test_read(self) -> None:
        command = parse_command("read 0x76 0xd0", ["i2c"], [])
        self.assertEqual((command.address, command.register, command.length), (0x76, 0xD0, 1))
        command = parse_command("read 60", ["i2c"], [])
        self.assertEqual((command.address, command.register), (60, None))
        self.assertEqual(parse_command("read 0x76 0 6", ["i2c"], []).length, 6)
        for bad in ("read", "read 0x80", "read 0x76 0x100", "read 0x76 0 33", "read zz"):
            with self.subTest(command=bad), self.assertRaises(CommandError):
                parse_command(bad, ["i2c"], [])

    def test_write(self) -> None:
        command = parse_command("write 0x3c 0x00 ae af", ["i2c"], [])
        self.assertEqual((command.address, command.register, command.data), (0x3C, 0, b"\xae\xaf"))
        self.assertIsNone(parse_command("write 0x3c - 01", ["i2c"], []).register)
        for bad in ("write 0x3c", "write 0x3c 0 xyz", "write 0x3c 0 " + "00" * 33):
            with self.subTest(command=bad), self.assertRaises(CommandError):
                parse_command(bad, ["i2c"], [])

    def test_send(self) -> None:
        command = parse_command("send $PMTK 000*32", [], ["gps"])
        self.assertEqual(command, BusCommand(action="send", target="gps", data=b"$PMTK 000*32\r\n"))
        self.assertEqual(parse_command("send b hi", [], ["a", "b"]).target, "b")
        with self.assertRaises(CommandError):
            parse_command("send hi", [], ["a", "b"])

    def test_unknown(self) -> None:
        with self.assertRaises(CommandError):
            parse_command("reboot", ["i2c"], [])
        with self.assertRaises(CommandError):
            parse_command("  ", ["i2c"], [])

    def test_chip_name(self) -> None:
        self.assertIn("BME280", chip_name(0x76))
        self.assertEqual(chip_name(0x11), "unknown")


if __name__ == "__main__":
    unittest.main()

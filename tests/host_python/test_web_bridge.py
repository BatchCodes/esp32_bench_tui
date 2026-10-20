"""Tests for the SerialBridge that the Web Serial code of the web pages calls."""

import unittest

from tests.host_python import host_path  # noqa: F401
from bench.link import BufferTransport, LinkError
from bench.web.bridge import SerialBridge


class SerialBridgeTests(unittest.TestCase):
    def test_attach_feed_write_reset_and_lost(self) -> None:
        written: list[bytes] = []
        resets: list[bool] = []
        transport = BufferTransport("web serial")
        bridge = SerialBridge(transport)
        bridge.attach(written.append, lambda: resets.append(True))
        transport.open()
        bridge.feed(memoryview(b"one\ntw"))
        bridge.feed(bytearray(b"o\n"))
        self.assertEqual(transport.read_line(0.0), "one")
        self.assertEqual(transport.read_line(0.0), "two")
        transport.write(b"hello\n")
        transport.reset_board()
        self.assertEqual(written, [b"hello\n"])
        self.assertEqual(resets, [True])
        bridge.lost("the cable was pulled")
        with self.assertRaisesRegex(LinkError, "cable"):
            transport.read_line(0.0)


if __name__ == "__main__":
    unittest.main()

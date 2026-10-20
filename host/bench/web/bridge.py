"""The Python side of the web pages: the objects that their JavaScript calls.

SerialBridge connects a BufferTransport to the Web Serial code in
web/app/serial.js. The JavaScript calls attach() when the port opens, feed()
with each chunk that it reads and lost() when the port goes away.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from bench.link import BufferTransport


def _to_js(data: bytes) -> Any:
    """bytes as a JavaScript Uint8Array in Pyodide, unchanged in CPython."""
    try:
        from pyodide.ffi import to_js
    except ImportError:
        return data
    return to_js(data)


def _to_bytes(chunk: Any) -> bytes:
    """A JavaScript Uint8Array (a JsProxy in Pyodide), or bytes, as bytes."""
    if isinstance(chunk, (bytes, bytearray, memoryview)):
        return bytes(chunk)
    return chunk.to_bytes()


class SerialBridge:
    """Feeds a BufferTransport from Web Serial, and writes back through it."""

    def __init__(self, transport: BufferTransport) -> None:
        self.transport = transport

    def attach(self, write: Callable[[Any], Any], reset: Callable[[], Any]) -> None:
        """The port is open. write takes a Uint8Array. reset pulses the reset line."""

        def write_bytes(data: bytes) -> None:
            write(_to_js(data))

        def pulse_reset() -> None:
            reset()

        self.transport.connect(write_bytes, pulse_reset)

    def feed(self, chunk: Any) -> None:
        self.transport.feed(_to_bytes(chunk))

    def lost(self, reason: str) -> None:
        self.transport.disconnect(str(reason))

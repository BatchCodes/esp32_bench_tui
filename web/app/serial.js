// Web Serial glue of the web TUI. A SerialConnection opens a port, reads it
// into the Python SerialBridge (host/bench/web/bridge.py) and writes the bytes
// that the bridge gives it. Web Serial works in Chrome, Edge and Opera only.

const RESET_PULSE_MS = 100;

export function webSerialSupported() {
  return typeof navigator !== "undefined" && "serial" in navigator;
}

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

export class SerialConnection {
  // bridge: the Python SerialBridge. onStatus(text, connected) reports changes.
  constructor(bridge, { onStatus = () => {}, serial = globalThis.navigator?.serial } = {}) {
    this.bridge = bridge;
    this.onStatus = onStatus;
    this.serial = serial;
    this.port = null;
    this.writer = null;
    this.reader = null;
    this.onDisconnect = (event) => {
      if (event.target === this.port) {
        this.lost("the serial port was disconnected");
      }
    };
  }

  // Asks the user for a port. Call it from a click handler.
  async request() {
    return this.serial.requestPort();
  }

  async open(port, baudRate) {
    await port.open({ baudRate });
    // Both lines released, so the auto-reset circuit of most ESP32 boards
    // does not reset the board when the port opens.
    await port.setSignals({ dataTerminalReady: false, requestToSend: false });
    this.port = port;
    this.writer = port.writable.getWriter();
    this.serial?.addEventListener?.("disconnect", this.onDisconnect);
    this.bridge.attach(
      (bytes) => this.write(bytes),
      () => this.reset(),
    );
    this.onStatus("connected", true);
    this.readLoop();
  }

  write(bytes) {
    if (!this.writer) {
      return;
    }
    this.writer
      .write(bytes)
      .catch((error) => this.lost(`cannot write to the serial port: ${error.message}`));
  }

  // Pulses EN low through RTS, the same as esptool.
  async reset() {
    if (!this.port) {
      return;
    }
    await this.port.setSignals({ dataTerminalReady: false, requestToSend: true });
    await sleep(RESET_PULSE_MS);
    await this.port.setSignals({ requestToSend: false });
  }

  async readLoop() {
    const port = this.port;
    // A framing or overrun error ends one stream, and port.readable then
    // gives a new one. A lost device leaves port.readable null.
    while (port === this.port && port.readable) {
      this.reader = port.readable.getReader();
      try {
        for (;;) {
          const { value, done } = await this.reader.read();
          if (done) {
            break;
          }
          if (value && value.length) {
            this.bridge.feed(value);
          }
        }
      } catch (error) {
        if (!port.readable) {
          this.lost(`cannot read the serial port: ${error.message}`);
        }
      } finally {
        this.reader.releaseLock();
        this.reader = null;
      }
    }
  }

  lost(reason) {
    if (!this.port) {
      return;
    }
    this.bridge.lost(reason);
    this.onStatus(reason, false);
    this.close();
  }

  async close() {
    const port = this.port;
    this.port = null;
    this.serial?.removeEventListener?.("disconnect", this.onDisconnect);
    try {
      await this.reader?.cancel();
    } catch {
      // The reader is already closed.
    }
    try {
      this.writer?.releaseLock();
    } catch {
      // The writer is already released.
    }
    this.writer = null;
    try {
      await port?.close();
    } catch {
      // The device is gone, or the port is already closed.
    }
  }
}

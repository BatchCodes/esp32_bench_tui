// Tests of web/app/serial.js: an AgentLink in Pyodide talks over a fake Web
// Serial port to the simulated bench agent.

import assert from "node:assert/strict";
import { after, before, test } from "node:test";

import { SerialConnection } from "../../web/app/serial.js";
import { loadHost, waitFor } from "./pyodide_host.mjs";

class FakeSerial extends EventTarget {}

// A port whose far end is a Python SimulatedTransport. The bytes that the
// page writes go to the simulator. Its lines come back in small chunks, so
// that lines are split across reads.
class FakePort extends EventTarget {
  constructor(simulator) {
    super();
    this.simulator = simulator;
    this.signals = [];
    this.baudRate = null;
    this.closed = false;
    this.readable = new ReadableStream({
      start: (controller) => {
        this.controller = controller;
      },
    });
    this.writable = new WritableStream({
      write: (chunk) => this.simulator.write(chunk),
    });
    this.pump = setInterval(() => this.pumpLines(), 10);
  }

  pumpLines() {
    let line;
    while ((line = this.simulator.read_line(0)) !== undefined) {
      const bytes = new TextEncoder().encode(`${line}\n`);
      for (let start = 0; start < bytes.length; start += 7) {
        this.controller.enqueue(bytes.slice(start, start + 7));
      }
    }
  }

  async open({ baudRate }) {
    this.baudRate = baudRate;
  }

  async setSignals(signals) {
    this.signals.push(signals);
  }

  async close() {
    this.closed = true;
    clearInterval(this.pump);
  }
}

let pyodide;
let python;

before(async () => {
  pyodide = await loadHost();
  python = pyodide.runPython(`
from pathlib import Path
from bench.config import load_project
from bench.link import ASYNCIO_RUNNER, AgentLink, BufferTransport
from bench.simulator import SimulatedTransport
from bench.web.bridge import SerialBridge


class SimulatorEnd:
    """The far end of the fake port. Takes Uint8Array chunks."""

    def __init__(self):
        self.simulator = SimulatedTransport(sleep=lambda seconds: None)
        self.simulator.open()

    def write(self, chunk):
        self.simulator.write(chunk.to_bytes())

    def read_line(self, timeout):
        return self.simulator.read_line(timeout)


config = load_project(Path("/bench/examples/pot_servo.yaml"))
transport = BufferTransport("web serial")
link = AgentLink(transport, config, runner=ASYNCIO_RUNNER)
bridge = SerialBridge(transport)
{"bridge": bridge, "link": link, "SimulatorEnd": SimulatorEnd}
`);
});

after(() => {
  python.get("link").stop();
});

test("the agent link configures the simulator over the fake port", async () => {
  const link = python.get("link");
  const serial = new FakeSerial();
  const port = new FakePort(python.get("SimulatorEnd")());
  const statuses = [];
  const connection = new SerialConnection(python.get("bridge"), {
    serial,
    onStatus: (text, connected) => statuses.push([text, connected]),
  });

  await connection.open(port, 115200);
  assert.equal(port.baudRate, 115200);
  assert.deepEqual(port.signals[0], { dataTerminalReady: false, requestToSend: false });
  assert.deepEqual(statuses[0], ["connected", true]);

  await pyodide.runPythonAsync("link.start()");
  assert.ok(
    await waitFor(() => link.snapshot().configured),
    "the link did not configure the agent",
  );
  assert.ok(await waitFor(() => link.snapshot().values.has("pot")), "no pot value arrived");

  const seq = link.set_output("servo", 45.0);
  assert.ok(
    await waitFor(() => link.snapshot().values.get("servo") === 45.0),
    "the servo value did not change",
  );
  assert.ok(seq > 0);

  link.reset_board();
  assert.ok(await waitFor(() => port.signals.length >= 3), "no reset pulse");
  assert.deepEqual(port.signals[1], { dataTerminalReady: false, requestToSend: true });
  assert.deepEqual(port.signals[2], { requestToSend: false });

  const disconnect = new Event("disconnect");
  Object.defineProperty(disconnect, "target", { value: port });
  connection.onDisconnect(disconnect);
  assert.ok(
    await waitFor(() => link.snapshot().status.includes("link lost")),
    "the link did not see the disconnect",
  );
  assert.equal(link.snapshot().connected, false);
  assert.ok(port.closed);
  assert.deepEqual(statuses.at(-1), ["the serial port was disconnected", false]);
});

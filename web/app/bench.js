// Start script of the web TUI pages (/tui/ and /simulator/). It loads Pyodide
// and the bench host package, shows the project choices, and runs the TUI in
// an xterm.js terminal. Refer to docs/web_tui.md.

import { SerialConnection, webSerialSupported } from "./serial.js";

const PYODIDE_VERSION = "314.0.6";
const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/pyodide.mjs`;
const APP_DIR = new URL("./", import.meta.url);
const BUNDLE_URL = new URL("bundle.json", APP_DIR);
const HOST_DIR = "/bench";
const TERMINAL_OPTIONS = {
  fontFamily: 'ui-monospace, "SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace',
  fontSize: 14,
  // At line height 1 the DOM renderer cuts off the underscores.
  lineHeight: 1.15,
  cursorBlink: false,
  scrollback: 0,
  theme: { background: "#0c0c0c" },
};
// Textual reads these before it starts.
const PYTHON_ENVIRONMENT = `
import os
os.environ.update({"TERM": "xterm-256color", "COLORTERM": "truecolor", "TEXTUAL_COLOR_SYSTEM": "truecolor"})
`;

const element = (id) => document.getElementById(id);

function setStatus(text, kind = "info") {
  const status = element("status");
  status.textContent = text;
  status.dataset.kind = kind;
}

function downloadText(name, text) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([text], { type: "text/yaml" }));
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

async function loadBench() {
  setStatus("Loading Python (Pyodide). The first visit loads about 15 MB.");
  const { loadPyodide } = await import(PYODIDE_URL);
  const pyodide = await loadPyodide();
  const bundle = await (await fetch(BUNDLE_URL)).json();

  setStatus("Loading Textual and PyYAML.");
  await pyodide.loadPackage(["micropip", "pyyaml"]);
  const micropip = pyodide.pyimport("micropip");
  await micropip.install(bundle.packages.map((item) => (item.endsWith(".whl") ? new URL(item, APP_DIR).href : item)));

  setStatus("Loading the bench host package.");
  const archive = await (await fetch(new URL(bundle.host_archive, APP_DIR))).arrayBuffer();
  pyodide.unpackArchive(archive, "zip", { extractDir: HOST_DIR });
  pyodide.runPython(`import sys; sys.path.insert(0, "${HOST_DIR}/host")`);
  pyodide.runPython(PYTHON_ENVIRONMENT);
  return {
    pyodide,
    session: pyodide.pyimport("bench.web.session"),
    driver: pyodide.pyimport("bench.web.driver"),
    link: pyodide.pyimport("bench.link"),
    bridge: pyodide.pyimport("bench.web.bridge"),
    version: bundle.version,
  };
}

function fillProjects(bench) {
  const select = element("project");
  for (const example of bench.session.list_examples().toJs({ dict_converter: Object.fromEntries })) {
    const option = document.createElement("option");
    option.value = `example:${example.name}`;
    option.textContent = `Example: ${example.title}`;
    select.append(option);
  }
  const fileOption = document.createElement("option");
  fileOption.value = "file:";
  fileOption.textContent = "Open a project file…";
  select.append(fileOption);
  select.addEventListener("change", () => {
    element("project-file-row").hidden = select.value !== "file:";
  });
}

async function readChoice() {
  const [kind, name] = element("project").value.split(/:(.*)/s);
  if (kind !== "file") {
    return { kind, name: name ?? "", text: "" };
  }
  const file = element("project-file").files[0];
  if (!file) {
    throw new Error("Choose a project file first.");
  }
  return { kind, name: file.name, text: await file.text() };
}

function openTerminal(bench) {
  const container = element("terminal");
  container.hidden = false;
  const terminal = new globalThis.Terminal(TERMINAL_OPTIONS);
  const fit = new globalThis.FitAddon.FitAddon();
  terminal.loadAddon(fit);
  terminal.open(container);
  fit.fit();
  const browserTerminal = bench.driver.BrowserTerminal((data) => terminal.write(data), terminal.cols, terminal.rows);
  terminal.onData((data) => browserTerminal.feed(data));
  terminal.onBinary((data) => browserTerminal.feed(data));
  const onResize = () => {
    fit.fit();
    browserTerminal.resize(terminal.cols, terminal.rows);
  };
  window.addEventListener("resize", onResize);
  terminal.focus();
  return {
    close() {
      window.removeEventListener("resize", onResize);
      terminal.dispose();
      browserTerminal.destroy();
      container.hidden = true;
    },
  };
}

function showRunning(running) {
  element("start-panel").hidden = running;
  document.body.classList.toggle("running", running);
}

// mode: "serial" for /tui/, "simulator" for /simulator/.
export async function startBenchPage({ mode }) {
  const start = element("start");
  start.disabled = true;
  if (mode === "serial" && !webSerialSupported()) {
    element("no-web-serial").hidden = false;
  }

  let bench;
  try {
    bench = await loadBench();
  } catch (error) {
    setStatus(`The page could not load: ${error.message}`, "error");
    throw error;
  }
  fillProjects(bench);
  setStatus(`Ready. Bench ${bench.version}.`, "ready");
  start.disabled = mode === "serial" && !webSerialSupported();

  start.addEventListener("click", async () => {
    let connection = null;
    let terminal = null;
    try {
      // The port prompt needs the click, so it comes before any other wait.
      const port = mode === "serial" ? await navigator.serial.requestPort() : null;
      const choice = await readChoice();
      // undefined arrives in Python as None. null would arrive as JsNull.
      let transport = undefined;
      if (mode === "serial") {
        const baud = bench.session.project_baud(choice.kind, choice.name, choice.text);
        transport = bench.link.BufferTransport("web serial");
        connection = new SerialConnection(bench.bridge.SerialBridge(transport), {
          onStatus: (text, connected) => setStatus(`Serial port: ${text}.`, connected ? "ready" : "error"),
        });
        await connection.open(port, baud);
        element("reconnect").hidden = false;
        element("reconnect").onclick = async () => {
          await connection.close();
          await connection.open(await navigator.serial.requestPort(), baud);
        };
      }
      showRunning(true);
      terminal = openTerminal(bench);
      const result = await bench.session.run_session(choice.kind, choice.name, choice.text, downloadText, transport);
      setStatus(result.message, result.ok ? "ready" : "error");
    } catch (error) {
      if (error.name !== "NotFoundError") {
        setStatus(error.message, "error");
      }
    } finally {
      terminal?.close();
      await connection?.close();
      element("reconnect").hidden = true;
      showRunning(false);
    }
  });
}

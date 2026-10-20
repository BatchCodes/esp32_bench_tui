// Loads Pyodide with the host package of this repository, for the Node tests
// of the web TUI. The wheels come from the Pyodide CDN and PyPI on the first
// run, and Pyodide caches them in node_modules.

import { fileURLToPath } from "node:url";
import { loadPyodide } from "pyodide";

export const REPO_DIR = fileURLToPath(new URL("../..", import.meta.url));
export const TEXTUAL_VERSION = "8.2.8";

export async function loadHost() {
  const pyodide = await loadPyodide();
  await pyodide.loadPackage(["micropip", "pyyaml"], { messageCallback: () => {} });
  const micropip = pyodide.pyimport("micropip");
  await micropip.install([`textual==${TEXTUAL_VERSION}`]);
  pyodide.FS.mkdirTree("/repo");
  pyodide.mountNodeFS("/repo", REPO_DIR);
  pyodide.runPython('import sys; sys.path.insert(0, "/repo/host")');
  return pyodide;
}

export async function waitFor(condition, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (condition()) {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  return condition();
}

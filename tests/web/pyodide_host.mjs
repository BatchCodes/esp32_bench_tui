// Loads Pyodide with the web TUI bundle, the same way as web/app/bench.js.
// npm test builds the bundle in build/ first (the pretest script). PyYAML
// comes from the Pyodide CDN on the first run, and Pyodide caches it in
// node_modules.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { loadPyodide } from "pyodide";

export const BUNDLE_DIR = fileURLToPath(new URL("build/", import.meta.url));
export const HOST_DIR = "/bench";
const WHEELS_DIR = "/wheels";

export async function loadHost() {
  const pyodide = await loadPyodide();
  const bundle = JSON.parse(readFileSync(`${BUNDLE_DIR}bundle.json`, "utf8"));
  await pyodide.loadPackage(["micropip", "pyyaml"], { messageCallback: () => {} });
  pyodide.FS.mkdirTree(WHEELS_DIR);
  const wheels = bundle.packages.map((item) => {
    const target = `${WHEELS_DIR}/${item.split("/").pop()}`;
    pyodide.FS.writeFile(target, readFileSync(`${BUNDLE_DIR}${item}`));
    return `emfs:${target}`;
  });
  await pyodide.pyimport("micropip").install.callKwargs(wheels, { deps: false });
  // unpackArchive takes a typed array, not a Node Buffer.
  const archive = new Uint8Array(readFileSync(`${BUNDLE_DIR}${bundle.host_archive}`));
  pyodide.unpackArchive(archive, "zip", { extractDir: HOST_DIR });
  pyodide.runPython(`import sys; sys.path.insert(0, "${HOST_DIR}/host")`);
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

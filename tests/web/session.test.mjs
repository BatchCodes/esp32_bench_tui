// Smoke test of the web TUI bundle: a full session of the bench TUI against
// the simulated agent, in a fake browser terminal. It checks the same path
// as the /simulator/ page, with no browser.

import assert from "node:assert/strict";
import { before, test } from "node:test";

import { loadHost, waitFor } from "./pyodide_host.mjs";

let pyodide;

before(async () => {
  pyodide = await loadHost();
});

test("the simulator session configures the pins and stops on q", async () => {
  const output = [];
  const downloads = [];
  const driver = pyodide.pyimport("bench.web.driver");
  const session = pyodide.pyimport("bench.web.session");
  const terminal = driver.BrowserTerminal((data) => output.push(data), 140, 40);

  const run = session.run_session("example", "pot_servo.yaml", "", (name, text) =>
    downloads.push([name, text]),
  );
  const app = () => terminal.driver?._app;
  assert.ok(await waitFor(() => app()?.state.configured), "the simulated agent was not configured");
  assert.ok(await waitFor(() => app().state.values.has("pot")), "no pot value arrived");
  // Look for the text with no escape sequences. The first frame can come
  // after the configuration.
  const screen = () => output.join("").replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "");
  assert.ok(
    await waitFor(() => screen().includes("Board (g)  Overview (o)")),
    "the TUI did not draw its pages",
  );

  terminal.feed("\x13");
  assert.ok(await waitFor(() => downloads.length === 1), "ctrl+s did not download the project");
  assert.equal(downloads[0][0], "pot_servo.yaml");

  terminal.feed("q");
  const result = await run;
  assert.equal(result.ok, true);
  assert.equal(result.message, "The TUI stopped.");
});

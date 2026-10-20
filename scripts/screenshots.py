#!/usr/bin/env python3
"""Make the TUI screenshots in docs/images/screenshots.

The script runs the bench TUI against the simulated bench agent, with no
terminal, and saves each page as an SVG file. Run it again after a change to
the TUI pages:

    .venv/bin/python scripts/screenshots.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR / "host"))

from bench.config import empty_project, load_project, with_all_inputs  # noqa: E402
from bench.link import ASYNCIO_RUNNER, AgentLink  # noqa: E402
from bench.simulator import SimulatedTransport  # noqa: E402
from bench.tui.app import BenchApp  # noqa: E402

OUT_DIR = REPO_DIR / "docs" / "images" / "screenshots"
# Relative to the repository, so that the screenshots show no local path.
EXAMPLES_DIR = Path("examples")
TERMINAL_SIZE = (124, 32)
# Time for the simulated values and the chart history to fill in.
SETTLE_S = 6.0
WIFI_SCAN_S = 4.0


async def wait_until(pilot, condition, timeout: float = 10.0) -> None:
    for _ in range(int(timeout / 0.05)):
        if condition():
            return
        await pilot.pause(0.05)
    raise TimeoutError("the simulated agent did not answer")


def save(app: BenchApp, name: str) -> None:
    path = OUT_DIR / f"{name}.svg"
    path.write_text(app.export_screenshot(title="bench"))
    print(f"Wrote {path.relative_to(REPO_DIR)}")


def make_app(config) -> BenchApp:
    link = AgentLink(SimulatedTransport(), config, runner=ASYNCIO_RUNNER)
    return BenchApp(config, link, watch_file=False)


async def board_page() -> None:
    config = with_all_inputs(empty_project("olimex_esp32_poe_iso", Path("bench.yaml")))
    app = make_app(config)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await wait_until(pilot, lambda: app.state.configured)
        await pilot.pause(SETTLE_S)
        save(app, "board_page")


async def pins_page_and_detail() -> None:
    config = load_project(EXAMPLES_DIR / "bus_sensors.yaml")
    app = make_app(config)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await wait_until(pilot, lambda: app.state.configured)
        await pilot.press("p")
        await pilot.pause(SETTLE_S)
        save(app, "pins_page")

    config = load_project(EXAMPLES_DIR / "pot_servo.yaml")
    app = make_app(config)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await wait_until(pilot, lambda: app.state.configured)
        await pilot.press("p")
        await pilot.pause(SETTLE_S)
        await pilot.press("space")
        await pilot.pause(1.0)
        save(app, "pin_detail")


async def wifi_page() -> None:
    config = load_project(EXAMPLES_DIR / "pot_servo.yaml")
    app = make_app(config)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await wait_until(pilot, lambda: app.state.configured)
        await pilot.press("w", "s", "n")
        await pilot.pause(WIFI_SCAN_S)
        save(app, "wifi_page")


async def main() -> None:
    os.chdir(REPO_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    await board_page()
    await pins_page_and_detail()
    await wifi_page()


if __name__ == "__main__":
    asyncio.run(main())

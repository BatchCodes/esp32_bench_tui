---
paths:
  - "**/*.py"
---

# Python Rules

Python in this repo is the host tool in `host/bench/` and its tests in `tests/host_python/`.

- Follow PEP 8: four-space indents, snake_case functions and variables, PascalCase classes, SHOUT_CASE constants.
- The project has no licence yet. Do not add SPDX header lines until the licence is chosen.
- Start an executable script with `#!/usr/bin/env python3`. Give each module a docstring that states what it does.
- Use only the standard library, `pyserial`, `PyYAML` and `textual`. Debian ships all of them (`python3-serial`, `python3-yaml`, `python3-textual`). Add a new dependency only when Debian ships it. Name it in `pyproject.toml`, `scripts/install.sh` and `CONTRIBUTING.md` in the same change.
- Keep the TUI code (`host/bench/tui/`) apart from the logic. The configuration loader, the links and the protocol code must import nothing from Textual, so the unit tests run with no terminal.
- Use dataclasses for configuration and message types. Do not pass raw dictionaries between modules after the loader has checked them.
- A link must never block the Textual event loop. Read the serial port in a worker thread and hand messages to the UI through a queue or `call_from_thread`.
- Put file-level constants, such as paths, rates and timeouts, near the top of the file. Resolve repo paths from `Path(__file__)`, not from the current directory.
- Add type hints to function parameters and return values.
- Add a unit test in `tests/host_python/` for each change to the configuration loader, the protocol code or a link. Use `SimulatedLink` for tests that need a board.

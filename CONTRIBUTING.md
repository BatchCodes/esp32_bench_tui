# Contributing to ESP32 Bench TUI

This document tells you how the repository is organised, how to build and test it, and which code style to use.

## Repository Layout

| Path                    | Contents                                                                        |
| ----------------------- | ------------------------------------------------------------------------------- |
| `firmware/bench_agent/` | The bench agent, one ESP-IDF app for all supported chips.                       |
| `components/`           | Shared ESP-IDF components that the bench agent uses.                            |
| `host/bench/`           | The Python host tool: configuration loader, board links and the Textual TUI.    |
| `boards/`               | Board profiles, one YAML file for each board.                                   |
| `examples/`             | Example project configuration files.                                            |
| `tests/host/`           | Firmware host tests. They run on your computer with the ESP-IDF `linux` target. |
| `tests/host_python/`    | Python unit tests for the host tool.                                            |
| `scripts/`              | Install, build, flash and test scripts, and the pinned ESP-IDF version.         |
| `docker/host/`          | The Docker image of the host tool.                                              |
| `web/`                  | The web flasher page. Refer to [docs/web_flasher.md](docs/web_flasher.md).      |
| `docs/`                 | Protocol, configuration and board profile documents.                            |

The shared firmware components follow these rules:

- `bench_protocol` and `pin_model` must not include ESP-IDF headers. The host tests compile them on your computer.
- Hardware access lives in separate components.
- Board-specific values (pins) live in the board profiles on the host, not in the firmware. The firmware gets the pin list at run time.

## Host Tool

The host tool needs Python 3.11 or later, `pyserial`, `PyYAML` and `textual`. On Debian, install the packages:

```bash
sudo apt install python3-serial python3-yaml python3-textual
```

Or use a virtual environment:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

Or use Docker only. [scripts/bench_docker.sh](scripts/bench_docker.sh) runs the tool in the image from [docker/host/Dockerfile](docker/host/Dockerfile), and `./bench` uses it when the Python packages are missing.

Run the Python tests:

```bash
python3 -m unittest discover -s tests/host_python -t .
```

Or in Docker:

```bash
./scripts/bench_docker.sh --test
```

## Firmware

The firmware uses ESP-IDF at the version in [scripts/esp_idf_version.txt](scripts/esp_idf_version.txt). Build in Docker, with no native installation:

```bash
./scripts/firmware.sh --target esp32 build
```

Or load a native ESP-IDF first. The script uses `idf.py` from your shell if it is available:

```bash
. ~/esp/esp-idf/export.sh
./scripts/firmware.sh --native --target esp32s3 build
```

Run the firmware host tests:

```bash
./scripts/run_host_tests.sh
```

To change the ESP-IDF version, update [scripts/esp_idf_version.txt](scripts/esp_idf_version.txt), the image tag in [.devcontainer/devcontainer.json](.devcontainer/devcontainer.json) and the image tag in [.github/workflows/ci.yml](.github/workflows/ci.yml) in the same change.

## Checks

[scripts/ci.sh](scripts/ci.sh) runs all checks that CI runs. Run it before you send a change.

## Code Style

The style rules for each language are in [.claude/rules](.claude/rules). They apply to people and to coding agents.

## Issue Tracking

Work is tracked with [bd (beads)](https://github.com/gastownhall/beads). Plans live in [.claude/plans](.claude/plans).

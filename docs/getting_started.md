# Getting Started

This document tells you how to install the bench agent on a board and how to start the bench TUI. There are three ways: in the browser, with Docker, or with a local install. To use the TUI after it starts, refer to [Using the TUI](using_the_tui.md).

## In the Browser

You do not need to install anything. Use Chrome, Edge or Opera on a desktop computer, because the pages use Web Serial.

1. Open the [web flasher](https://batchcodes.github.io/esp32_bench_tui/) and flash the bench agent to the board. Refer to [Web flasher](web_flasher.md).
2. Open the [web TUI](https://batchcodes.github.io/esp32_bench_tui/tui/) and connect to the board. Refer to [Web TUI](web_tui.md).

To try the TUI with no board, open the [simulator](https://batchcodes.github.io/esp32_bench_tui/simulator/). It works in every browser.

## With Docker

You need Docker. The scripts build and flash the firmware in the `espressif/idf` image, and run the host tool in a small Python image. The first run of each image takes some minutes.

1. Try the TUI with no board:

   ```bash
   ./bench --config examples/pot_servo.yaml --sim
   ```

   `./bench` uses your local Python if it has `pyserial`, `PyYAML` and `textual`. If not, it runs the tool in Docker. Set `BENCH_DOCKER=1` to always use Docker.

2. Connect the board. Build and flash the bench agent. This example is for the Olimex `ESP32-POE-ISO` (`esp32` target):

   ```bash
   ./scripts/firmware.sh --target esp32 flash
   ```

   The scripts use the only device in `/dev/serial/by-id/`. If more than one board is connected, give the port: `./scripts/firmware.sh --target esp32 flash /dev/ttyUSB0`.

3. Start the TUI. With no configuration file, it asks which board is connected and puts an input on each free pin:

   ```bash
   ./bench
   ```

   To start with a configuration file, give its path, for example `./bench --config examples/led_button.yaml`.

4. Connect a sensor, add it to the configuration file and save the file. The TUI loads the file again and sends the new configuration to the board. To check a configuration without a board, run `./bench --config my_bench.yaml --check`.

| Task                      | Command                                                             |
| ------------------------- | ------------------------------------------------------------------- |
| Run the TUI               | `./scripts/bench_docker.sh --config examples/led_button.yaml`       |
| Run the TUI with no board | `./scripts/bench_docker.sh --config examples/led_button.yaml --sim` |
| Build the firmware        | `./scripts/firmware.sh --docker --target esp32 build`               |
| Flash the firmware        | `./scripts/firmware.sh --docker --target esp32 flash`               |
| Show the board log        | `./scripts/firmware.sh --docker --target esp32 monitor`             |
| Run all checks            | `./scripts/ci.sh`                                                   |

`scripts/bench_docker.sh` mounts the repository and the current directory at the same paths, so configuration files work with the same paths as on your computer. It passes the serial port into the container. USB pass-through to a container works on Linux only. On macOS and Windows, use `--sim`, the web pages, or a local install.

## Local Install

To run the host tool without Docker, install the Python packages. On Debian 13 the script installs `python3-serial`, `python3-yaml` and `python3-textual`. With `--venv` it installs them with pip into `.venv/`:

```bash
./scripts/install.sh
```

To build the firmware without Docker, install ESP-IDF at the version in [scripts/esp_idf_version.txt](../scripts/esp_idf_version.txt) and load it in your shell. `./scripts/firmware.sh` then uses `idf.py` from your shell.

## Serial Port Access

Your user needs access to the serial port. On Debian and Ubuntu, add your user to the `dialout` group, then log out and log in again:

```bash
sudo usermod -aG dialout "$USER"
```

Only one program can open a serial port. Close `idf.py monitor`, the web pages and other TUIs before you start the TUI.

## See also

- [Using the TUI](using_the_tui.md)
- [Project configuration](project_config.md)
- [Web flasher](web_flasher.md)
- [Web TUI](web_tui.md)

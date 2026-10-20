# Web Flasher

The web flasher is a web page that flashes the bench agent firmware to a board from the browser. Use it when you do not want to install ESP-IDF or Docker. After the flash, open the [web TUI](web_tui.md), or start the bench TUI in a terminal. Refer to [Getting started](getting_started.md).

The page is at <https://batchcodes.github.io/esp32_bench_tui/>.

## Requirements

- Chrome, Edge or Opera on a desktop computer. The page uses the Web Serial API. Firefox and Safari do not support it.
- A USB data cable. Some USB cables have no data wires and only charge the board.
- On Linux, access to the serial port. Add your user to the `dialout` group, then log out and log in again:

  ```bash
  sudo usermod -aG dialout "$USER"
  ```

## Flash a Board

1. Connect the board to the computer with a USB cable.
2. Open the page and click **Connect and install**.
3. Select the serial port of the board.
4. Accept the erase prompt for a board that runs other firmware. The bench agent keeps no settings, so an erase is safe.
5. When the flash is done, close the install window. The window keeps the serial port open until you close it.
6. Start the bench TUI with the same USB port.

If the page cannot connect, hold the `BOOT` button of the board and click **Connect and install** again. Release `BOOT` when the flash starts.

The flash replaces the firmware on the board. To keep a copy of the old firmware, make a backup before the flash:

```bash
python3 -m esptool --port /dev/ttyUSB0 read_flash 0 ALL backup.bin
```

## Firmware Images

The page uses [ESP Web Tools](https://esphome.github.io/esp-web-tools/). ESP Web Tools reads the chip type from the board. Then it selects an image from `manifest.json`. Each image is one merged file (bootloader, partition table and app) that the page writes at offset 0.

| Image                                     | Chip     | USB port of the board | Serial link of the bench agent |
| ----------------------------------------- | -------- | --------------------- | ------------------------------ |
| `bench_agent_esp32.bin`                   | ESP32    | any                   | UART0                          |
| `bench_agent_esp32s3.bin`                 | ESP32-S3 | USB-to-UART bridge    | UART0                          |
| `bench_agent_esp32s3_usb_serial_jtag.bin` | ESP32-S3 | native USB            | USB-Serial-JTAG                |
| `bench_agent_esp32c3.bin`                 | ESP32-C3 | USB-to-UART bridge    | UART0                          |
| `bench_agent_esp32c3_usb_serial_jtag.bin` | ESP32-C3 | native USB            | USB-Serial-JTAG                |
| `bench_agent_esp32c6.bin`                 | ESP32-C6 | USB-to-UART bridge    | UART0                          |
| `bench_agent_esp32c6_usb_serial_jtag.bin` | ESP32-C6 | native USB            | USB-Serial-JTAG                |

ESP Web Tools selects the native USB image when the board connects through the native USB port of the chip. The bench agent then talks on that port. If you move the cable to the other port of the board, flash the board again from that port.

## How the Site Is Built

The `pages` job in [ci.yml](../.github/workflows/ci.yml) builds and deploys the site after each push to `main`:

1. The `build` jobs build the bench agent for each image with `scripts/ci.sh build TARGET [VARIANT]`. This also writes `merged-binary.bin` in the build directory.
2. The `pages` job runs [build_site.sh](../scripts/build_site.sh). The script copies the page from [web/](../web), copies the images, and writes `manifest.json`.
3. The job deploys the site to GitHub Pages.

To turn on GitHub Pages for the repository, open **Settings**, then **Pages**, and set **Source** to **GitHub Actions**.

### Test the page locally

Web Serial works on `localhost` without HTTPS. Build the images, then build and serve the site:

```bash
./scripts/ci.sh build esp32
./scripts/build_site.sh --serve
```

Open <http://localhost:8000> in Chrome or Edge. The site includes only the images that you built.

## See also

- [Web TUI](web_tui.md)
- [Wire protocol](protocol.md)
- [Board profiles](board_profiles.md)

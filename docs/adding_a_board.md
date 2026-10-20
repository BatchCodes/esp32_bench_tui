# Add a Board

This document tells you how to add a board profile. A board profile lets the host tool check a project configuration and show the pin map of the board. The bench agent firmware does not change for a new board, unless the board uses a new chip. Refer to [Board profiles](board_profiles.md) for the meaning of each key.

## Board With a Supported Chip

The supported chips are in [boards/chips](../boards/chips): `esp32`, `esp32s3`, `esp32c3` and `esp32c6`.

1. Get the schematic or the pin table of the board. Use the manufacturer documents, not a third-party pinout image, when you can.
2. Copy a board file of the same chip, for example [esp32_devkitc.yaml](../boards/esp32_devkitc.yaml), to `boards/<name>.yaml`. Use lower-case letters, digits and `_` for the name.
3. Set `name`, `title`, `chip`, `flash_mb`, `psram_mb` and `usb`.
4. Set `link`:
   - `uart0` if the board has a USB-UART bridge, for example a CP2102 or a CH340. Linux shows the board as `/dev/ttyUSB0`.
   - `usb_serial_jtag` if the board uses the native USB of the chip. Linux shows the board as `/dev/ttyACM0`. Build the bench agent with the USB-Serial-JTAG console. Refer to [sdkconfig.local.example](../firmware/bench_agent/sdkconfig.local.example).
5. Set `pins` to the list of GPIOs on the headers. If you do not know the list, use `all`.
6. Add each GPIO that a part of the board uses to `reserved`, for example a display, a radio or an Ethernet PHY. Add each fact that does not stop the use of a pin to `notes`.
7. Add the on-board LEDs, buttons and ADC inputs to `onboard`. A project configuration can then use them with `onboard: <id>`.
8. Add the header pins to `header_left` and `header_right`, from the antenna end to the USB end. Use a GPIO number for a GPIO pin and a label such as `GND` for the other pins. Check the order on the board silkscreen. The Board page of the TUI shows the result.
9. Add each source to `sources`.
10. Keep `verified: false` until a person checks each pin against the hardware. The TUI shows a warning for a board that is not verified.
11. Check the profile:

    ```bash
    ./bench --list-boards
    python3 -m unittest discover -s tests/host_python -t .
    ```

    The test `test_every_board_profile_loads` loads every profile.

12. Add the board to the table in [README.md](../README.md).

## Board With a New Chip

1. Add a chip file to [boards/chips](../boards/chips). Take the facts from the chip datasheet: the GPIO list, the UART0 pins, the flash and PSRAM pins, the strapping pins and the ADC channels.
2. Add the target to `SUPPORTED_TARGETS` in [scripts/firmware.sh](../scripts/firmware.sh) and `FIRMWARE_TARGETS` in [scripts/ci.sh](../scripts/ci.sh), and to the build matrix in [.github/workflows/ci.yml](../.github/workflows/ci.yml).
3. Build the bench agent for the target. Fix each error in [components/bench_io](../components/bench_io) or [components/bench_transport](../components/bench_transport) with a `#if` on the `soc_caps.h` value, not on the target name, when a capability is the cause.
4. Add the board file as in the section above.

## See also

- [Board profiles](board_profiles.md)
- [Add a device type](adding_a_device_type.md)

# Board Profiles

A board profile tells the host tool which GPIOs a board has and what each one can do. The host uses the profile to refuse a project configuration that is not safe, and to show the pin map on the Overview page. The firmware does not read board profiles.

The facts come from two files:

- A **chip file** in [boards/chips](../boards/chips), for example [esp32.yaml](../boards/chips/esp32.yaml). It has the facts that are the same for every board with that chip: valid GPIOs, input-only GPIOs, flash pins, strapping pins, ADC and touch pins.
- A **board file** in [boards](../boards), for example [olimex_esp32_poe_iso.yaml](../boards/olimex_esp32_poe_iso.yaml). It has the facts of one board: which GPIOs are on the headers, which GPIOs the board uses for its own parts, and the on-board LEDs and buttons.

## Chip File

| Key                        | Type              | Description                                                                             |
| -------------------------- | ----------------- | --------------------------------------------------------------------------------------- |
| `chip`                     | string            | ESP-IDF target name, for example `esp32s3`. The file name is `<chip>.yaml`.             |
| `title`                    | string            | Display name.                                                                           |
| `gpios`                    | list of integers  | All GPIOs of the chip.                                                                  |
| `uart0`                    | map               | `tx` and `rx` GPIOs of UART0. These pins are reserved when the board `link` is `uart0`. |
| `input_only`               | list of integers  | GPIOs with no output driver.                                                            |
| `reserved`                 | map, GPIO to text | GPIOs that are never usable, for example the SPI flash pins.                            |
| `strapping`                | map, GPIO to text | Strapping pins. The host shows a warning for each one in a configuration.               |
| `adc1`                     | list of integers  | GPIOs with an ADC1 channel.                                                             |
| `adc2`                     | list of integers  | GPIOs with an ADC2 channel.                                                             |
| `adc2_conflicts_with_wifi` | boolean           | `true` if ADC2 cannot read while Wi-Fi is on.                                           |
| `touch`                    | list of integers  | GPIOs with a touch sensor channel.                                                      |
| `dac`                      | list of integers  | GPIOs with a DAC output.                                                                |
| `notes`                    | map, GPIO to text | Other facts, for example JTAG or USB pins. The host shows them as information.          |

## Board File

| Key                           | Type                       | Description                                                                                                                                                                                                                                                                                                                                                                                          |
| ----------------------------- | -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                        | string                     | Profile name. The file name is `<name>.yaml`. A project configuration selects the board with this name.                                                                                                                                                                                                                                                                                              |
| `title`                       | string                     | Display name.                                                                                                                                                                                                                                                                                                                                                                                        |
| `chip`                        | string                     | The chip file to use.                                                                                                                                                                                                                                                                                                                                                                                |
| `flash_mb`                    | integer                    | Flash size in MB.                                                                                                                                                                                                                                                                                                                                                                                    |
| `psram_mb`                    | integer                    | PSRAM size in MB.                                                                                                                                                                                                                                                                                                                                                                                    |
| `link`                        | string                     | `uart0` (USB-UART bridge) or `usb_serial_jtag` (native USB).                                                                                                                                                                                                                                                                                                                                         |
| `usb`                         | string                     | A description of the USB connection.                                                                                                                                                                                                                                                                                                                                                                 |
| `verified`                    | boolean                    | `true` when a person checked every pin fact against the schematic or the hardware.                                                                                                                                                                                                                                                                                                                   |
| `sources`                     | list of strings            | Where the facts come from.                                                                                                                                                                                                                                                                                                                                                                           |
| `pins`                        | list of integers, or `all` | The GPIOs on the headers. `all` means every GPIO of the chip that is not reserved.                                                                                                                                                                                                                                                                                                                   |
| `labels`                      | map, GPIO to text          | Optional. Silkscreen labels, for example `VP` for GPIO 36.                                                                                                                                                                                                                                                                                                                                           |
| `reserved`                    | map, GPIO to text          | GPIOs that the board uses for its own parts, for example Ethernet. A device can use one only with `allow_reserved: true`.                                                                                                                                                                                                                                                                            |
| `notes`                       | map, GPIO to text          | Board facts that do not stop the use of a pin, for example a shared SD card line.                                                                                                                                                                                                                                                                                                                    |
| `onboard`                     | list                       | The on-board parts that a project configuration can use by name. Each part has `id`, `gpio`, `type` (`led`, `button` or `adc`), `active_low` and `notes`.                                                                                                                                                                                                                                            |
| `header_left`, `header_right` | list                       | Optional. The header pins in physical order, from the antenna end to the USB end, with the board in portrait and the parts facing you. Each entry is a GPIO number, or a text label for a pin with no GPIO, for example `GND`, `3V3`, `5V` or `EN`. The Board page draws the pins in this order. Without these keys, the Board page splits the GPIOs into two columns and shows "pin order unknown". |

## Generic Boards

Each chip file also gives a generic board, `generic_<chip>`, for example `generic_esp32s3`. It has every GPIO of the chip except the reserved pins and the UART0 pins, and no board facts. Use it in a project configuration (`board: generic_esp32s3`), or with `./bench --chip esp32s3`, for a board that has no profile yet.

## Checks

The host refuses a device in the project configuration when:

- the GPIO is not in the chip `gpios` list, or not in the board `pins` list
- the GPIO is in the chip `reserved` map, or is a UART0 pin on a `uart0` board
- the GPIO is in the board `reserved` map, and the device does not set `allow_reserved: true`
- the device is an output and the GPIO is input-only
- the device is an ADC input and the GPIO has no ADC channel
- two devices use the same GPIO

The host shows a warning, but accepts the device, when the GPIO is a strapping pin, an ADC2 pin on a chip where ADC2 conflicts with Wi-Fi, or has a note.

## Add a Board

Refer to [Add a Board](adding_a_board.md).

## See also

- [Project configuration](project_config.md)
- [Wire protocol](protocol.md)

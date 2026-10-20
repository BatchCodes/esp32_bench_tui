# Using the TUI

This document describes the pages and keys of the bench TUI. The same keys work in the terminal, in the [web TUI](web_tui.md) and in the simulator. To install and start the TUI, refer to [Getting started](getting_started.md).

## Pages

The TUI opens on the Board page. One key opens each page. `←` and `→` go to the previous or next page.

| Key | Page      | What it shows                                                                                            |
| --- | --------- | -------------------------------------------------------------------------------------------------------- |
| `g` | Board     | A drawing of the board with the header pins in their physical order. Refer to [Board Page](#board-page). |
| `o` | Overview  | The board facts, the bench agent information and the pin map.                                            |
| `p` | Pins      | The configured devices and their live values.                                                            |
| `b` | Bus       | The I2C scan results and transfers, and the text of each UART.                                           |
| `w` | Wi-Fi     | The access points, the station connection and the channel activity.                                      |
| `t` | Bluetooth | The Bluetooth Low Energy devices near the board.                                                         |
| `l` | Log       | The serial log output of the board.                                                                      |
| `i` | Link      | The port, the message rate and the error counts.                                                         |

## Keys

| Key         | Action                                                                                                                                                                                                                                                                                                                                                             |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `space`     | Board, Pins, Wi-Fi and Bluetooth pages: open the detail view of the selected pin, access point or device. `space` again (or `escape`) closes it. The pin detail view has a big chart of the last 60 s.                                                                                                                                                             |
| `enter`     | Change the selected thing. A digital output: on or off. A PWM or servo output: type a value. An access point: connect to it, or disconnect when the board is connected to it. Works in the detail views too.                                                                                                                                                       |
| `z`         | Detail view: switch the chart between the fixed scale and a zoom on its own values.                                                                                                                                                                                                                                                                                |
| `←` and `→` | Go to the previous or next page. In a text input they move the cursor.                                                                                                                                                                                                                                                                                             |
| `tab`       | Board and Pins pages and the detail view: change the pin to its next mode. An ADC pin that can output cycles analog in, analog out (PWM), digital in, digital out. Another GPIO cycles digital in, digital out. An input-only ADC pin (GPIO 34 to 39 on the ESP32) cycles analog in, digital in. An output starts at 0. The pin keeps its place in the Pins table. |
| `a`         | Give the selected GPIO another type with a pin command. Refer to [Open Mode](#open-mode). In listen mode: add a log value.                                                                                                                                                                                                                                         |
| `s`         | Bus page: scan each I2C bus. Wi-Fi and Bluetooth pages: turn the scan on or off.                                                                                                                                                                                                                                                                                   |
| `n`         | Wi-Fi page: turn the channel sniffer on or off.                                                                                                                                                                                                                                                                                                                    |
| `c` and `d` | Wi-Fi page: connect the board to an access point, or disconnect it.                                                                                                                                                                                                                                                                                                |
| `/`         | Bluetooth page: filter the devices by name or address.                                                                                                                                                                                                                                                                                                             |
| `:`         | Bus page: type a command, for example `read 0x76 0xd0` or `send hello`.                                                                                                                                                                                                                                                                                            |
| `ctrl+s`    | Save the devices to the configuration file, or to `bench.yaml`. The web TUI downloads the file.                                                                                                                                                                                                                                                                    |
| `r`         | Reset the board through the RTS line of the USB-UART bridge.                                                                                                                                                                                                                                                                                                       |
| `q`         | Quit.                                                                                                                                                                                                                                                                                                                                                              |

In the value prompt, `space` or `enter` sends the value and closes the prompt. With no value, they close the prompt and send nothing. A PWM value that you type is a duty cycle when it is below 1 (`0.25` is 25 %), and a percentage from 1 to 100 (`25` is 25 %). A trailing `%` always means a percentage. A value above 100 sets 100 %, and the status bar says so.

The graphs of pins with a known range use a fixed scale: 0 to 3150 mV for an analogue input (the highest calibrated reading of the ESP32 ADC), 0 to 1 for a digital pin and a PWM duty, and 0° to 180° for a servo. The other graphs scale to their own values. A value turns grey when it is more than 2 s old, and red when it is more than 3 s old. If the TUI stops, the bench agent sets each output to its `initial` value after 2 s, and turns the Wi-Fi and Bluetooth scans off.

![The pin detail view of a potentiometer, with a chart of the last seconds](images/screenshots/pin_detail.svg)

## Board Page

The Board page draws the board in portrait, with the antenna at the top and the USB connector at the bottom, and the header pins on the left and right in their physical order. Each pin shows its label, its mode (`DI` digital in, `DO` digital out, `ADC` analog in, `PWM` analog out, `SRV` servo, `CNT` counter, `I2C`, `UART`, `1W` DS18B20, `DHT`), its device and its live value: `1` or `0` for a digital pin, and the value in its units for an analogue input or a sensor.

| Key         | Action                                                                                                           |
| ----------- | ---------------------------------------------------------------------------------------------------------------- |
| `↑` and `↓` | Move through the GPIO pins: down the left side, then down the right side. Power pins and flash pins are skipped. |
| `enter`     | Change the pin: toggle a digital output, or type a value for a PWM or servo output.                              |
| `tab`       | Change the pin to its next mode.                                                                                 |
| `space`     | Open the detail view of the pin.                                                                                 |
| `a`         | Give the selected GPIO another type with a pin command, for example `i2c 21 22`, `servo 18` or `dht22 5`.        |

The pin order comes from `header_left` and `header_right` in the board profile. The Olimex `ESP32-POE-ISO`, the LAFVIN board and the four Espressif DevKit profiles have it. The Heltec and CrowPanel profiles do not have it yet, because no reliable source was found. For these boards and the generic boards, the Board page shows the GPIOs in two columns in number order and says "pin order unknown". To add the order, refer to [Adding a board](adding_a_board.md).

## Wi-Fi and Bluetooth

The bench agent starts the radios only when you turn a feature on, on the Wi-Fi or Bluetooth page. Press `s` on the page to turn the scan on or off.

The Wi-Fi page lists the access points that the board heard in the last 60 s, the strongest first, with the channel, the signal, the security and the 802.11 modes. The panel on the right shows the number of packets on each channel when the sniffer is on (`n`). The top line shows the board's own station connection.

The Bluetooth page lists the Bluetooth Low Energy devices that the board heard in the last 60 s. The scan is active: the board asks each device for its scan response, because many devices send their name only there. A device with no name shows what its advertisement says instead, in grey, for example `Exposure Notification` (a phone with the contact tracing service), `Find My (AirTag, offline finding)` or `iBeacon`. Phones change their random address every few minutes, so one phone can show as more than one device.

| Key         | Action                                                                                                                                                                                                                     |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `↑` and `↓` | Select an access point or a device. The cursor stays on it when the list changes.                                                                                                                                          |
| `space`     | Open the detail view: all the fields, the decoded advertisement, and an RSSI chart of the last scans. `space` again closes it.                                                                                             |
| `enter`     | Wi-Fi page: connect the board to the selected access point, or disconnect when it is connected to it. The TUI asks for the password, except for an open network. It sends the password to the board and does not store it. |
| `c` and `d` | Wi-Fi page: connect by typing an SSID (for a hidden network), or disconnect.                                                                                                                                               |
| `/`         | Bluetooth page: filter by name, address or type.                                                                                                                                                                           |

On the classic ESP32, ADC2 pins cannot read while Wi-Fi is on.

## Open Mode

You do not need a configuration file. Start the TUI with no `--config`, and no `bench.yaml` in the current directory:

```bash
./bench
```

The TUI first asks which board is connected. The list has the board profiles, then a generic board for each chip, and last a generic board that follows the chip that the bench agent reports. The TUI remembers your last choice in `~/.config/bench/last_board`. `--board`, `--chip` and `--config` skip the list.

Then the TUI puts an input on each free GPIO: an analogue input (`adc`) on each ADC1 pin, and a digital input on the others. Inputs only read, so this is safe with anything connected. Pins that the board uses for its own parts, for example Ethernet on the Olimex, are left out. Add `--empty` to start with no pins. The generic board profile of a chip, for example `generic_esp32`, checks only the chip facts (flash pins, input-only pins, ADC pins). Give `--board olimex_esp32_poe_iso` to use a board profile, or `--chip esp32s3` to choose the chip.

Press `a` and type a pin command to read or drive any free GPIO at once:

| Command                      | Device                                                 |
| ---------------------------- | ------------------------------------------------------ |
| `in 34`                      | digital input on GPIO 34                               |
| `in 15 pull=up invert=true`  | button-like input with the internal pull-up            |
| `out 4`                      | digital output                                         |
| `adc 32 scale=0.001 units=V` | analogue input, shown in V                             |
| `pwm 13 freq=5000`           | PWM output                                             |
| `servo 18`                   | servo output                                           |
| `counter 35`                 | pulse counter                                          |
| `i2c 21 22`                  | I2C bus on SDA 21 and SCL 22. Scan it on the Bus page. |
| `uart 17 16 baud=115200`     | UART on TX 17 and RX 16                                |
| `ds18b20 4`, `dht22 5`       | temperature sensors                                    |

Add `name=<name>` to give the device a name. A command on a GPIO that is already in use replaces that device. The board gets the new configuration at once. The other outputs keep their values. `ctrl+s` saves the devices to the configuration file, or to `bench.yaml`.

## Listen to Any Firmware

To watch a board that runs its own firmware, use listen mode. The TUI sends nothing to the board. It shows each serial line on the Log page:

```bash
./bench --listen
./bench --listen --board olimex_esp32_poe_iso
./bench --listen --baud 9600 --port /dev/ttyUSB0
```

With no `--board`, the TUI asks which board is connected.

Press `a` and type a name and a regex with one capture group, for example `heap free heap (\d+)`. The Pins page then shows the value each time a log line matches. `x` removes the selected log value. `ctrl+s` saves the rules. Refer to [examples/log_listen.yaml](../examples/log_listen.yaml) for a saved log mode configuration.

Close other programs that use the serial port first, for example `idf.py monitor`. The TUI opens the port exclusively, so a second program gets an error. The TUI opens the port with DTR and RTS released, so most boards do not restart. Listen mode cannot read the GPIO levels of the board: it shows only what the firmware prints.

## HX711 Load Cells

The `hx711` type reads one or two HX711 load cell amplifiers on one clock, the same way as the Gaggiuino hardware scales. [examples/lafvin_hw_scales_tester.yaml](../examples/lafvin_hw_scales_tester.yaml) tests those scales on the LAFVIN board:

```bash
./bench --config examples/lafvin_hw_scales_tester.yaml
```

Power the scales from the `3V3` pin, not from 5 V. The HX711 data lines and the clock pull-up on the scales follow the supply voltage, and the ESP32 inputs take at most 3.3 V.

Each channel shows its raw count. A channel that sends no data for 400 ms shows "no data" and counts a timeout: check the power, the ground and that data wire. Press on a load cell and its count changes. `enter` tares both channels (the values are then counts since the tare), and `enter` again clears the tare. `space` shows a chart of each channel.

## See also

- [Getting started](getting_started.md)
- [Project configuration](project_config.md)
- [Web TUI](web_tui.md)
- [Board profiles](board_profiles.md)

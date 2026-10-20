# Project Configuration

A project configuration file tells the host tool which board you use and what is connected to it. You do not need one to start: the TUI also runs with no file, and saves the pins that you add in the TUI with `ctrl+s`. Refer to the Open Mode section of [Using the TUI](using_the_tui.md#open-mode). It is a YAML file. Give its path to the TUI with `--config`. The TUI loads the file again each time you save it.

Examples are in [examples](../examples):

| File                                                                     | Shows                                                                      |
| ------------------------------------------------------------------------ | -------------------------------------------------------------------------- |
| [led_button.yaml](../examples/led_button.yaml)                           | an LED and the on-board button of the Olimex `ESP32-POE-ISO`               |
| [pot_servo.yaml](../examples/pot_servo.yaml)                             | a potentiometer, a servo and a PWM output                                  |
| [lafvin_led_button.yaml](../examples/lafvin_led_button.yaml)             | the on-board LED and button of the LAFVIN board, with no wiring            |
| [log_listen.yaml](../examples/log_listen.yaml)                           | log mode on a board that runs its own firmware                             |
| [bus_sensors.yaml](../examples/bus_sensors.yaml)                         | I2C, a UART module, a DS18B20, a DHT22 and a pulse counter                 |
| [lafvin_hw_scales_tester.yaml](../examples/lafvin_hw_scales_tester.yaml) | the Gaggiuino hardware scales (two HX711 on one clock) on the LAFVIN board |

## Top-Level Keys

| Key                | Type    | Description                                                                                                                                                             |
| ------------------ | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `board`            | string  | Required. The name of a board profile in [boards](../boards), or `generic_<chip>`. Refer to [Board profiles](board_profiles.md).                                        |
| `mode`             | string  | `agent` (the board runs the bench agent) or `log` (the board runs any firmware). The default is `agent`.                                                                |
| `port`             | string  | The serial port, for example `/dev/ttyUSB0`. Optional. The `--port` option overrides it. If neither gives a port, the TUI uses the only device in `/dev/serial/by-id/`. |
| `baud`             | integer | The baud rate. The default is 115200.                                                                                                                                   |
| `report_period_ms` | integer | How often the agent sends the pin values, 20 to 10000. The default is 100.                                                                                              |
| `devices`          | list    | The devices in `agent` mode. Refer to [Devices](#devices).                                                                                                              |
| `log_values`       | list    | The values in `log` mode. Refer to [Log Values](#log-values).                                                                                                           |

## Devices

Each device uses one GPIO, except `i2c` and `uart`, which use two. You can use at most 48 devices.

```yaml
devices:
  - name: led
    type: led
    gpio: 4
```

| Key                | Types                                        | Description                                                                                                                 |
| ------------------ | -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `name`             | all                                          | Required. 1 to 23 characters: lower-case letters, digits and `_`. Starts with a letter.                                     |
| `type`             | all                                          | Required, unless `onboard` gives it. Refer to the table of types below.                                                     |
| `gpio`             | all except `i2c` and `uart`                  | Required, unless `onboard` gives it. The GPIO number, not the header pin number.                                            |
| `sda`, `scl`       | `i2c`                                        | Required. The I2C data and clock GPIOs.                                                                                     |
| `tx`, `rx`         | `uart`                                       | Required. The transmit and receive GPIOs of the board. Connect `tx` to the RX pin of the module.                            |
| `baud`             | `uart`                                       | The baud rate. The default is 9600.                                                                                         |
| `onboard`          | all                                          | The `id` of an on-board part of the board profile, for example `button`. It gives `gpio`, `type` and `invert`.              |
| `pull`             | `digital_in`, `button`                       | `none`, `up` or `down`. The default is `none`, or `up` for `button`.                                                        |
| `invert`           | `digital_in`, `digital_out`, `button`, `led` | `true` reverses the level. The default is `false`, or `true` for `button`.                                                  |
| `initial`          | `digital_out`, `led`, `pwm`, `servo`         | The value after setup and after a watchdog stop. The default is 0, or 90 for `servo`.                                       |
| `freq_hz`          | `pwm`, `i2c`                                 | The PWM frequency, default 1000. The I2C clock, default 100000.                                                             |
| `min_us`, `max_us` | `servo`                                      | The pulse width at 0° and at 180°. The defaults are 500 and 2500.                                                           |
| `scale`, `offset`  | all inputs                                   | The TUI shows `value * scale + offset`. The defaults are 1 and 0.                                                           |
| `units`            | all inputs                                   | The units that the TUI shows. The default is `mV` for `adc` and `°C` for the temperature sensors.                           |
| `allow_reserved`   | all                                          | `true` lets the device use a GPIO that the board profile reserves, for example an Ethernet pin when Ethernet is not in use. |

| Type             | Direction | Value                                                                                                                                                                                                                         |
| ---------------- | --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `digital_in`     | input     | `0` or `1`                                                                                                                                                                                                                    |
| `button`         | input     | `1` when pressed. A `digital_in` with `pull: up` and `invert: true`.                                                                                                                                                          |
| `digital_out`    | output    | `0` or `1`                                                                                                                                                                                                                    |
| `led`            | output    | `0` or `1`. A `digital_out`.                                                                                                                                                                                                  |
| `adc`            | input     | The calibrated voltage in mV.                                                                                                                                                                                                 |
| `pwm`            | output    | The duty cycle, 0.0 to 1.0. In the TUI, type a duty below 1 (`0.25`) or a percentage from 1 to 100 (`25`).                                                                                                                    |
| `servo`          | output    | The angle, 0° to 180°.                                                                                                                                                                                                        |
| `counter`        | input     | Pulses per second. A `digital_in` that counts each level change. Use it for a flow sensor or a fan tachometer.                                                                                                                |
| `i2c`            | bus       | The number of devices that the last scan found. The Bus page scans, reads and writes.                                                                                                                                         |
| `uart`           | bus       | The number of bytes received. The Bus page shows the received text and sends text.                                                                                                                                            |
| `ds18b20`        | input     | The temperature in °C. One sensor on the pin. Needs a 4.7 kΩ pull-up resistor. Read each 1 s.                                                                                                                                 |
| `dht11`, `dht22` | input     | The temperature in °C and the humidity in %. Needs a 4.7 kΩ pull-up resistor if the module has none. Read each 2 s.                                                                                                           |
| `hx711`          | input     | The raw count of an HX711 load cell amplifier. Keys `clock`, `data` and optional `data2` (a second HX711 on the same clock, as on the Gaggiuino scales), and `gain` (128, 64 or 32, default 128). Power the HX711 from 3.3 V. |

The host checks each device against the board profile before it sends the configuration. Refer to the Checks section in [Board profiles](board_profiles.md). The TUI shows the warnings in the status bar and on the Pins page.

## Log Values

In `log` mode the TUI does not send anything to the board. It reads each line of the serial output and tries each regex rule. When a rule matches, the first capture group becomes the new value. If the value is a number, the TUI applies `scale` and `offset`. If not, it shows the text.

```yaml
log_values:
  - name: free_heap
    pattern: 'free heap (\d+)'
    scale: 0.001
    units: kB
```

| Key               | Description                                                                                                                    |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `name`            | Required. The same rules as a device name.                                                                                     |
| `pattern`         | Required. A Python regular expression with at least one capture group. Use single quotes in YAML, so that `\d` stays as it is. |
| `scale`, `offset` | Optional. Apply to a numeric value.                                                                                            |
| `units`           | Optional.                                                                                                                      |

## See also

- [Board profiles](board_profiles.md)
- [Wire protocol](protocol.md)

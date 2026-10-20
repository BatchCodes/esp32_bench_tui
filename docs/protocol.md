# Bench Agent Wire Protocol

This document describes the messages between the host tool and the bench agent firmware. The host tool is in [host/bench](../host/bench). The firmware is in [firmware/bench_agent](../firmware/bench_agent). The encoder and the parser for the firmware are in [components/bench_protocol](../components/bench_protocol).

The current protocol version is `6`. Version 2 added the `i2c`, `uart`, `ds18b20`, `dht11` and `dht22` modes, and the I2C and UART messages. Version 3 added the Wi-Fi and Bluetooth messages. Version 4 raised the pin limit from 24 to 48 and the host line limit from 2048 to 6144 bytes. Version 5 added the active BLE scan and more fields in `wifi_scan_result` and `ble_devices`. Version 6 added the `hx711` mode. Increase the version for each change that an older host or an older agent cannot read. Update this document, the firmware and [host/bench/protocol.py](../host/bench/protocol.py) in the same change.

## Framing

- The link is the serial console of the board: UART0 through the USB-UART bridge on most boards, or the USB-Serial-JTAG port on boards with native USB only.
- The baud rate is 115200, the default ESP-IDF console rate. The ROM boot messages and `idf.py monitor` use the same rate.
- Each message is one JSON object on one line, terminated by `\n`. The maximum length of a host message line is 6144 bytes, newline included. An agent message line can be longer, for example a `ble_devices` message.
- Each message line starts with the exact text `{"type":"`. A line that does not start with this text is a log line. The firmware log output (`ESP_LOGI` and similar) and the ROM boot messages share the port with the protocol. The host shows log lines on the Log page.
- The agent writes each message line in one locked write. If a log line is not complete when the agent writes a message, the agent writes a `\n` first. So a message always starts at the start of a line.
- Keys are snake_case.

## Common Fields

| Field  | Type    | Description                                                                                                                                                                 |
| ------ | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `type` | string  | The message type. Always the first key.                                                                                                                                     |
| `seq`  | integer | Sequence number. The host gives each request a new number from 1. The agent copies the number into the reply. Messages that the agent sends without a request have `seq` 0. |

## Host to Agent

### `hello`

Asks the agent to identify itself. The agent replies with `hello`.

```json
{ "type": "hello", "seq": 1 }
```

### `config`

Sets the full pin configuration. The agent first releases all pins of the previous configuration. Then it sets up each pin in the list. The agent replies with `config_ack`.

```json
{
  "type": "config",
  "seq": 2,
  "report_period_ms": 100,
  "pins": [
    { "id": "led", "gpio": 2, "mode": "digital_out", "invert": false, "initial": 0 },
    { "id": "button", "gpio": 0, "mode": "digital_in", "pull": "up", "invert": true },
    { "id": "pot", "gpio": 34, "mode": "adc" },
    { "id": "fan", "gpio": 4, "mode": "pwm", "freq_hz": 25000, "initial": 0.0 },
    { "id": "servo", "gpio": 13, "mode": "servo", "min_us": 500, "max_us": 2500, "initial": 90 }
  ]
}
```

The message is shown on more than one line here for clarity. On the wire it is one line.

| Field              | Type    | Description                                                                |
| ------------------ | ------- | -------------------------------------------------------------------------- |
| `report_period_ms` | integer | Period of the `state` messages, 20 to 10000. Optional. The default is 100. |
| `pins`             | array   | The pins, at most 48. An empty array releases all pins.                    |

A pin entry uses one GPIO, in `gpio`. The `i2c` and `uart` modes use two GPIOs, in `sda` and `scl`, or `tx` and `rx`. Each GPIO can be in only one pin entry.

Fields of a pin:

| Field                    | Modes                         | Type    | Description                                                                                                         |
| ------------------------ | ----------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------- |
| `id`                     | all                           | string  | Name of the pin, 1 to 23 characters. Unique in the configuration.                                                   |
| `gpio`                   | all except `i2c` and `uart`   | integer | GPIO number. Unique in the configuration.                                                                           |
| `mode`                   | all                           | string  | `digital_in`, `digital_out`, `adc`, `pwm`, `servo`, `i2c`, `uart`, `ds18b20`, `dht11` or `dht22`.                   |
| `sda`, `scl`             | `i2c`                         | integer | The I2C data and clock GPIOs.                                                                                       |
| `tx`, `rx`               | `uart`                        | integer | The UART transmit and receive GPIOs, seen from the board.                                                           |
| `baud`                   | `uart`                        | integer | 300 to 2000000. Optional. The default is 9600.                                                                      |
| `clock`, `data`, `data2` | `hx711`                       | integer | The HX711 clock, the data of the first HX711, and the data of an optional second HX711 on the same clock.           |
| `gain`                   | `hx711`                       | integer | 128 or 64 (channel A) or 32 (channel B). Optional. The default is 128.                                              |
| `pull`                   | `digital_in`                  | string  | `none`, `up` or `down`. Optional. The default is `none`.                                                            |
| `invert`                 | `digital_in`, `digital_out`   | boolean | Reverse the logic level. Optional. The default is `false`.                                                          |
| `initial`                | `digital_out`, `pwm`, `servo` | number  | The value after setup and after a watchdog stop. Optional. The default is 0 (`digital_out`, `pwm`) or 90 (`servo`). |
| `freq_hz`                | `pwm`, `i2c`                  | integer | PWM frequency, 1 to 40000000, default 1000. I2C clock, 1000 to 1000000, default 100000. `servo` always uses 50 Hz.  |
| `min_us`                 | `servo`                       | integer | Pulse width at 0°. Optional. The default is 500.                                                                    |
| `max_us`                 | `servo`                       | integer | Pulse width at 180°. Optional. The default is 2500.                                                                 |

### `set`

Sets the value of one output pin. The agent replies with `ack` or `error`.

```json
{ "type": "set", "seq": 3, "id": "led", "value": 1 }
```

| Mode          | `value`                                       |
| ------------- | --------------------------------------------- |
| `digital_out` | `0` or `1`, the logical level before `invert` |
| `pwm`         | duty cycle, `0.0` to `1.0`                    |
| `servo`       | angle in degrees, `0` to `180`                |

### `i2c_scan`, `i2c_read` and `i2c_write`

Requests for an `i2c` pin. `i2c_scan` probes each address from 0x08 to 0x77, and the agent replies with `i2c_scan_result`. `i2c_read` writes the register number, if given, then reads `length` bytes (1 to 32), and the agent replies with `i2c_data`. `i2c_write` writes the register number, if given, then the bytes in `data`, and the agent replies with `ack`. Each request can also get an `error` reply, for example when no device answers.

```json
{"type":"i2c_scan","seq":5,"id":"bus"}
{"type":"i2c_read","seq":6,"id":"bus","address":118,"register":208,"length":1}
{"type":"i2c_write","seq":7,"id":"bus","address":60,"register":0,"data":"af"}
```

`data` is hex text, two digits for each byte.

### `uart_send`

Sends bytes on a `uart` pin. `data` is hex text of 1 to 256 bytes. The agent replies with `ack`.

```json
{ "type": "uart_send", "seq": 8, "id": "gps", "data": "24504d544b3030302a33320d0a" }
```

### `radio`

Turns the radio features on or off. The agent replies with `ack`, or with `error` if the chip or the build does not have the feature. Each field that is not given is off. All radio features are off at boot, and the agent turns them off when the watchdog trips.

```json
{ "type": "radio", "seq": 9, "wifi_scan_ms": 5000, "sniffer": false, "ble_scan": true }
```

| Field          | Type    | Description                                                                                                                                                                           |
| -------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `wifi_scan_ms` | integer | The period of the Wi-Fi scan, at least 2000. 0 turns the scan off.                                                                                                                    |
| `sniffer`      | boolean | Counts the Wi-Fi packets on each channel. The radio changes channel each 100 ms, unless the station is connected. Then it counts only the packets on the channel of the access point. |
| `ble_scan`     | boolean | Scans for Bluetooth Low Energy advertisements (passive scan).                                                                                                                         |
| `ble_active`   | boolean | Sends a scan request to each device, so it sends its scan response too. Many devices put their name only in the scan response. The default is `false`, a passive scan.                |

On the classic ESP32, ADC2 cannot read while Wi-Fi is on.

### `wifi_connect` and `wifi_disconnect`

Connects the Wi-Fi station to an access point, or disconnects it. The agent replies with `ack`, then sends `wifi_status` messages. The agent does not store the password.

```json
{"type":"wifi_connect","seq":10,"ssid":"bench","password":"secret"}
{"type":"wifi_disconnect","seq":11}
```

`ssid` has 1 to 32 characters. `password` has at most 64 characters, and is empty or missing for an open network.

### `ping`

A heartbeat. The host sends it every 500 ms. The agent replies with `pong`.

```json
{ "type": "ping", "seq": 4 }
```

## Agent to Host

### `hello`

Sent at boot with `seq` 0, and as the reply to a `hello` request.

```json
{
  "type": "hello",
  "seq": 1,
  "protocol": 6,
  "agent": "0.1.0",
  "chip": "esp32",
  "revision": 301,
  "cores": 2,
  "mac": "24:6f:28:aa:bb:cc",
  "flash_mb": 4,
  "free_heap": 281000
}
```

| Field       | Type    | Description                                                              |
| ----------- | ------- | ------------------------------------------------------------------------ |
| `protocol`  | integer | The protocol version of the agent. The host refuses a different version. |
| `agent`     | string  | The firmware version.                                                    |
| `chip`      | string  | The ESP-IDF target name, for example `esp32` or `esp32s3`.               |
| `revision`  | integer | The chip revision, as `major * 100 + minor`.                             |
| `cores`     | integer | The number of CPU cores.                                                 |
| `mac`       | string  | The base MAC address.                                                    |
| `flash_mb`  | integer | The flash size in MB.                                                    |
| `free_heap` | integer | The free heap in bytes.                                                  |

### `config_ack`

The reply to `config`. If `ok` is `false`, the agent did not set up the pins in `errors`. It did set up all other pins.

```json
{
  "type": "config_ack",
  "seq": 2,
  "ok": false,
  "errors": [{ "id": "pot", "error": "gpio 2 has no ADC channel" }]
}
```

### `state`

Sent every `report_period_ms` while a configuration is active.

```json
{
  "type": "state",
  "seq": 0,
  "uptime_ms": 123456,
  "values": { "led": 1, "button": 0, "pot": 1650, "fan": 0.25, "servo": 90 },
  "edges": { "button": 14 }
}
```

| Field       | Type    | Description                                                                                                                                                                                                                                                                                                                                                 |
| ----------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `uptime_ms` | integer | Time since boot.                                                                                                                                                                                                                                                                                                                                            |
| `values`    | object  | The value of each pin, by `id`. `digital_in` and `digital_out`: the logical level, `0` or `1`. `adc`: the calibrated voltage in mV. `pwm`: the duty cycle. `servo`: the angle. `ds18b20`, `dht11` and `dht22`: the temperature in °C. `i2c`: the number of devices that the last scan found. `uart`: the number of bytes received. A failed read is `null`. |
| `edges`     | object  | For each `digital_in` pin, the number of level changes since setup. A change shorter than the report period shows here, even when `values` does not show it.                                                                                                                                                                                                |
| `humidity`  | object  | For each `dht11` and `dht22` pin, the relative humidity in %. Only present when the configuration has a DHT pin.                                                                                                                                                                                                                                            |
| `hx711`     | object  | For each `hx711` pin: `raw2` (the raw count of the second HX711, when it has `data2`), `ready` (for each channel, `true` when it sent data in the last 400 ms), `timeouts` (for each channel, the number of 400 ms periods with no data) and `reads`. The raw count of the first HX711 is in `values`.                                                      |

A DS18B20 is read each 1000 ms, and a DHT each 2000 ms, so their values change less often than the report period.

### `i2c_scan_result` and `i2c_data`

The replies to `i2c_scan` and `i2c_read`.

```json
{"type":"i2c_scan_result","seq":5,"id":"bus","addresses":[60,118]}
{"type":"i2c_data","seq":6,"id":"bus","address":118,"register":208,"data":"60"}
```

### `uart_data`

Bytes that a `uart` pin received. The agent sends them at most each report period, at most 256 bytes for each message.

```json
{ "type": "uart_data", "seq": 0, "id": "gps", "data": "24474e524d432c" }
```

### `ack` and `error`

The reply to a `set` request. `error` can also be the reply to a message that the agent cannot parse. In this case `seq` is 0 if the agent cannot read it.

```json
{"type":"ack","seq":3}
{"type":"error","seq":3,"error":"pin 'led2' is not configured"}
```

### `wifi_scan_result`

The result of each Wi-Fi scan, at most 24 access points, the strongest first.

```json
{
  "type": "wifi_scan_result",
  "seq": 0,
  "aps": [
    { "ssid": "bench", "bssid": "24:6f:28:aa:bb:cc", "channel": 6, "rssi": -52, "auth": "wpa2" }
  ]
}
```

`auth` is `open`, `wep`, `wpa`, `wpa2`, `wpa_wpa2`, `wpa3`, `wpa2_wpa3` or `other`. `phy` lists the 802.11 modes as letters: `b`, `g`, `n`, `x` (802.11ax) and `l` (Espressif long range). `wps` is `true` when the access point has WPS on. `second` is the second channel of a 40 MHz access point: `above`, `below` or `none`.

### `wifi_status`

The state of the Wi-Fi station. The agent sends it when the state changes, and each 1 s while the station is connected.

```json
{
  "type": "wifi_status",
  "seq": 0,
  "state": "connected",
  "ssid": "bench",
  "ip": "192.168.1.20",
  "rssi": -50,
  "channel": 6,
  "reason": ""
}
```

`state` is `off`, `idle`, `connecting`, `connected` or `failed`. `reason` is the ESP-IDF disconnect reason when `state` is `failed`.

### `wifi_channels`

The number of Wi-Fi packets on each channel, 1 to 13, since the last message. The agent sends it each `period_ms` while the sniffer is on.

```json
{
  "type": "wifi_channels",
  "seq": 0,
  "period_ms": 1300,
  "counts": [4, 0, 0, 0, 0, 52, 0, 0, 0, 0, 7, 0, 0]
}
```

### `ble_devices`

The Bluetooth Low Energy devices that the scan heard in the last 30 s, at most 32, the strongest first. The agent sends it each 1 s while the scan is on.

```json
{
  "type": "ble_devices",
  "seq": 0,
  "devices": [
    { "address": "c0:01:02:03:04:05", "name": "Tag", "rssi": -70, "company_id": 76, "age_ms": 1200 }
  ]
}
```

`company_id` is the Bluetooth SIG company identifier from the manufacturer data, or -1. `age_ms` is the time since the last advertisement.

| Field          | Description                                                                                                     |
| -------------- | --------------------------------------------------------------------------------------------------------------- |
| `address_type` | 0 public, 1 random, 2 public identity, 3 random identity. Phones use random addresses that change.              |
| `connectable`  | `true` when the device sends connectable advertisements.                                                        |
| `adv_count`    | The number of advertisements and scan responses that the agent received.                                        |
| `tx_power`     | The TX power level in dBm that the device advertises. Missing when the device does not send it.                 |
| `appearance`   | The GAP appearance value, for example 0x0340 for a heart rate sensor. Missing when the device does not send it. |
| `services`     | The 16-bit service UUIDs from the advertisement and the service data, at most 6.                                |
| `manufacturer` | The first 24 bytes of the manufacturer data as hex text, company ID first.                                      |

### `pong`

The reply to `ping`.

```json
{ "type": "pong", "seq": 4, "uptime_ms": 124000, "free_heap": 280512 }
```

### `event`

A notice from the agent with no request.

```json
{ "type": "event", "seq": 0, "event": "watchdog" }
```

| `event`    | Meaning                                                                                                                                                                                                                                      |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `watchdog` | The agent got no message from the host for 2000 ms (Kconfig `BENCH_HOST_TIMEOUT_MS`). It set every output pin to its `initial` value and turned the Wi-Fi and Bluetooth scans off. The configuration and the station connection stay active. |

## Session Sequence

1. The host opens the port. Opening the port can reset the board through the DTR and RTS lines of the USB-UART bridge.
2. The host sends `hello` until the agent replies, for at most 5 s. A `hello` with `seq` 0 at boot also counts.
3. The host refuses an agent with a different `protocol` value.
4. The host sends `config`, and shows the errors from `config_ack` on the Pins page.
5. The agent sends `state` messages. The host sends `ping` every 500 ms, and `set` when the operator changes an output.
6. When the project configuration file changes, the host sends a new `config`.

## See also

- [Project configuration](project_config.md)
- [Board profiles](board_profiles.md)

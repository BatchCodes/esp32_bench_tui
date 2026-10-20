# Add a Device Type

This document tells you which files change when you add a device type, for example a DS18B20 temperature sensor or an I2C chip. A device type is the `type` of a device in a project configuration.

## Type With an Existing Pin Mode

Some device types only change the defaults of a pin mode. An example is `button`: it is a `digital_in` with `pull: up` and `invert: true`. Such a type needs no firmware change and no protocol change.

1. Add the type to `DEVICE_TYPES` in [host/bench/config.py](../host/bench/config.py). Add it to `OUTPUT_TYPES` if it is an output.
2. Map the type to its pin mode in `Device.mode`, and set its defaults in `_device_defaults`.
3. Add a test in [tests/host_python/test_config.py](../tests/host_python/test_config.py).
4. Add the type to the table of types in [project_config.md](project_config.md).

## Type With a New Pin Mode

A device type that needs new hardware access, for example a bus or a timing protocol, needs a new pin mode in the firmware and in the protocol.

1. Add the mode to [docs/protocol.md](protocol.md): its pin fields, its value in `state` messages and its `set` value, if any. Increase the protocol version if an older host or agent cannot read the new messages.
2. Add the mode to `Mode` and its rules to [components/pin_model](../components/pin_model). Keep this component free of ESP-IDF headers. Add host tests in [tests/host/main](../tests/host/main).
3. Read the new pin fields in `parse_pin` in [components/bench_protocol](../components/bench_protocol), and encode the value in `add_value`. Add host tests.
4. Set up, read, write and release the pin in [components/bench_io](../components/bench_io).
5. Add the mode to `PROTOCOL_VERSION` (if changed) in [host/bench/protocol.py](../host/bench/protocol.py), to `Device.wire_pin` and the checks in [host/bench/config.py](../host/bench/config.py), and to the value text in [host/bench/display.py](../host/bench/display.py).
6. Make the simulated agent in [host/bench/simulator.py](../host/bench/simulator.py) give values for the mode, so the TUI and the tests work with no board.
7. Run the checks:

   ```bash
   ./scripts/ci.sh
   ```

8. Test the device on a real board, and add an example configuration to [examples](../examples).

## See also

- [Wire protocol](protocol.md)
- [Project configuration](project_config.md)
- [Add a board](adding_a_board.md)

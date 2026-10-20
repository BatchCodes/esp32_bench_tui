"""Tests for the board profile and project configuration loader."""

import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.host_python import host_path  # noqa: F401
from bench.config import (
    BOARDS_DIR,
    ConfigError,
    list_boards,
    load_board,
    load_project,
)

REPO_DIR = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_DIR / "examples"


class TempConfig:
    """Writes a project configuration to a temporary file."""

    def __init__(self, text: str) -> None:
        self.text = textwrap.dedent(text)
        self.directory = tempfile.TemporaryDirectory()

    def __enter__(self) -> Path:
        path = Path(self.directory.name) / "bench.yaml"
        path.write_text(self.text)
        return path

    def __exit__(self, *args: object) -> None:
        self.directory.cleanup()


def load_text(text: str):
    with TempConfig(text) as path:
        return load_project(path)


def load_errors(text: str) -> list[str]:
    with TempConfig(text) as path:
        try:
            load_project(path)
        except ConfigError as error:
            return error.errors
    raise AssertionError("expected a ConfigError")


class BoardProfileTests(unittest.TestCase):
    def test_every_board_profile_loads(self) -> None:
        names = list_boards()
        self.assertIn("olimex_esp32_poe_iso", names)
        for name in names:
            with self.subTest(board=name):
                board = load_board(name)
                self.assertEqual(board.name, name)
                self.assertTrue(board.pins)
                blocked = board.never_usable()
                for part in board.onboard:
                    self.assertNotIn(part.gpio, blocked, f"{name}: onboard {part.id}")

    def test_all_pins_excludes_flash_and_console(self) -> None:
        board = load_board("esp32_devkitc")
        for gpio in (1, 3, 6, 7, 8, 9, 10, 11):
            self.assertNotIn(gpio, board.pins)
        self.assertIn(34, board.pins)

    def test_olimex_ethernet_pins_are_reserved(self) -> None:
        board = load_board("olimex_esp32_poe_iso")
        for gpio in (12, 17, 18, 19, 21, 22, 23, 25, 26, 27):
            self.assertIn(gpio, board.reserved)

    def test_unknown_board(self) -> None:
        with self.assertRaises(ConfigError) as context:
            load_board("no_such_board", BOARDS_DIR)
        self.assertIn("Known boards", context.exception.errors[0])


class ProjectConfigTests(unittest.TestCase):
    def test_examples_load(self) -> None:
        for path in sorted(EXAMPLES_DIR.glob("*.yaml")):
            with self.subTest(example=path.name):
                load_project(path)

    def test_button_and_led_defaults(self) -> None:
        config = load_text(
            """
            board: lafvin_esp32_devkit
            devices:
              - {name: led, onboard: led}
              - {name: boot, onboard: boot_button}
              - {name: other, type: button, gpio: 4}
            """
        )
        led = config.device("led")
        self.assertEqual((led.gpio, led.mode, led.invert), (2, "digital_out", False))
        boot = config.device("boot")
        self.assertEqual((boot.gpio, boot.mode, boot.invert, boot.pull), (0, "digital_in", True, "up"))
        other = config.device("other")
        self.assertEqual((other.pull, other.invert), ("up", True))

    def test_wire_config(self) -> None:
        config = load_project(EXAMPLES_DIR / "pot_servo.yaml")
        wire = config.wire_config()
        self.assertEqual(wire["report_period_ms"], 100)
        pins = {pin["id"]: pin for pin in wire["pins"]}
        self.assertEqual(pins["pot"], {"id": "pot", "gpio": 32, "mode": "adc"})
        self.assertEqual(pins["servo"]["initial"], 90.0)
        self.assertEqual(pins["dimmer"]["freq_hz"], 5000)

    def test_output_on_input_only_pin(self) -> None:
        errors = load_errors(
            """
            board: esp32_devkitc
            devices:
              - {name: led, type: led, gpio: 34}
            """
        )
        self.assertTrue(any("input-only" in error for error in errors), errors)

    def test_flash_pin_is_refused(self) -> None:
        errors = load_errors(
            """
            board: esp32_devkitc
            devices:
              - {name: led, type: led, gpio: 6}
            """
        )
        self.assertTrue(any("SPI flash" in error for error in errors), errors)

    def test_console_pin_is_refused(self) -> None:
        errors = load_errors(
            """
            board: esp32_devkitc
            devices:
              - {name: led, type: led, gpio: 1}
            """
        )
        self.assertTrue(any("UART0" in error for error in errors), errors)

    def test_board_reserved_pin_needs_override(self) -> None:
        # GPIO 2 is the e-paper MOSI line of the Heltec Wireless Paper.
        text = """
            board: heltec_wireless_paper_v1_2
            devices:
              - {name: led, type: led, gpio: 2%s}
            """
        errors = load_errors(text % "")
        self.assertTrue(any("allow_reserved" in error for error in errors), errors)
        config = load_text(text % ", allow_reserved: true")
        self.assertEqual(config.device("led").gpio, 2)

    def test_olimex_headers_have_no_ethernet_pins(self) -> None:
        errors = load_errors(
            """
            board: olimex_esp32_poe_iso
            devices:
              - {name: led, type: led, gpio: 23, allow_reserved: true}
            """
        )
        self.assertTrue(any("not on the headers" in error for error in errors), errors)

    def test_onboard_part_off_the_headers(self) -> None:
        config = load_text(
            """
            board: lafvin_esp32_devkit
            devices:
              - {name: boot, onboard: boot_button}
            """
        )
        self.assertEqual(config.device("boot").gpio, 0)

    def test_adc_without_channel(self) -> None:
        errors = load_errors(
            """
            board: esp32_devkitc
            devices:
              - {name: pot, type: adc, gpio: 5}
            """
        )
        self.assertTrue(any("no ADC channel" in error for error in errors), errors)

    def test_pin_and_name_conflicts(self) -> None:
        errors = load_errors(
            """
            board: esp32_devkitc
            devices:
              - {name: one, type: led, gpio: 4}
              - {name: two, type: led, gpio: 4}
              - {name: one, type: led, gpio: 5}
            """
        )
        self.assertTrue(any("both use GPIO 4" in error for error in errors), errors)
        self.assertTrue(any("more than once" in error for error in errors), errors)

    def test_strapping_and_adc2_warnings(self) -> None:
        config = load_text(
            """
            board: esp32_devkitc
            devices:
              - {name: pot, type: adc, gpio: 2}
            """
        )
        text = " ".join(config.warnings)
        self.assertIn("strapping pin", text)
        self.assertIn("ADC2", text)

    def test_bad_values(self) -> None:
        errors = load_errors(
            """
            board: esp32_devkitc
            report_period_ms: 5
            devices:
              - {name: Bad-Name, type: led, gpio: 4}
              - {name: fan, type: pwm, gpio: 5, initial: 2}
              - {name: arm, type: servo, gpio: 13, min_us: 2500, max_us: 500}
              - {name: what, type: motor, gpio: 14}
              - {name: typo, type: led, gpio: 15, intial: 1}
            """
        )
        joined = " | ".join(errors)
        for expected in ("report_period_ms", "Bad-Name", "initial duty", "servo pulse", "type must be", "unknown keys"):
            self.assertIn(expected, joined)

    def test_bus_and_sensor_devices(self) -> None:
        config = load_project(EXAMPLES_DIR / "bus_sensors.yaml")
        pins = {pin["id"]: pin for pin in config.wire_config()["pins"]}
        self.assertEqual(pins["i2c"], {"id": "i2c", "mode": "i2c", "sda": 13, "scl": 16, "freq_hz": 100000})
        self.assertEqual(pins["gps"], {"id": "gps", "mode": "uart", "tx": 4, "rx": 36, "baud": 9600})
        self.assertEqual(pins["water"], {"id": "water", "mode": "ds18b20", "gpio": 32})
        self.assertEqual(pins["flow"]["mode"], "digital_in")
        self.assertEqual(config.device("water").units, "°C")
        self.assertEqual(config.device("gps").gpios, [4, 36])
        self.assertEqual(config.device("i2c").gpio_text(), "sda 13 scl 16")

    def test_two_gpio_checks(self) -> None:
        errors = load_errors(
            """
            board: esp32_devkitc
            devices:
              - {name: bus, type: i2c, sda: 21, scl: 34}
              - {name: gps, type: uart, tx: 17}
              - {name: led, type: led, gpio: 21}
            """
        )
        joined = " | ".join(errors)
        self.assertIn("scl: GPIO 34 is input-only", joined)
        self.assertIn("tx and rx are required", joined)
        self.assertIn("both use GPIO 21", joined)
        config = load_text(
            """
            board: esp32_devkitc
            devices:
              - {name: gps, type: uart, tx: 17, rx: 34}
            """
        )
        self.assertEqual(config.device("gps").gpio2, 34)

    def test_sensor_needs_output_pin(self) -> None:
        errors = load_errors(
            """
            board: esp32_devkitc
            devices:
              - {name: water, type: ds18b20, gpio: 39}
            """
        )
        self.assertTrue(any("input-only" in error for error in errors), errors)

    def test_log_values(self) -> None:
        config = load_project(EXAMPLES_DIR / "log_listen.yaml")
        self.assertEqual(config.mode, "log")
        heap = next(value for value in config.log_values if value.name == "free_heap")
        self.assertEqual(heap.pattern.search("I (5) ros: Lost agent, free heap 1234").group(1), "1234")

    def test_log_value_needs_group(self) -> None:
        errors = load_errors(
            """
            board: esp32_devkitc
            mode: log
            log_values:
              - {name: heap, pattern: 'free heap \\d+'}
            """
        )
        self.assertTrue(any("capture group" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()

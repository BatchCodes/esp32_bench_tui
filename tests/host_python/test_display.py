"""Tests for the TUI text helpers."""

import unittest

from tests.host_python import host_path  # noqa: F401
from bench import display
from bench.config import Device


class DisplayTests(unittest.TestCase):
    def test_staleness(self) -> None:
        self.assertEqual(display.staleness(0.5), "fresh")
        self.assertEqual(display.staleness(2.5), "stale")
        self.assertEqual(display.staleness(3.0), "lost")
        self.assertEqual(display.staleness(None), "lost")

    def test_sparkline(self) -> None:
        self.assertEqual(display.sparkline([], 10), "")
        self.assertEqual(display.sparkline([1.0, 1.0], 10), "▁▁")
        self.assertEqual(display.sparkline([0.0, 7.0, 3.5], 10), "▁█▅")
        self.assertEqual(len(display.sparkline([float(index) for index in range(50)], 10)), 10)

    def test_chart_lines(self) -> None:
        rows, low, high = display.chart_lines([0.0, 4.0, 8.0], 10, 2)
        self.assertEqual((low, high), (0.0, 8.0))
        self.assertEqual(rows, ["  █", "▁██"])
        rows, _low, _high = display.chart_lines([5.0, 5.0], 10, 3)
        self.assertEqual(rows[-1], "▁▁")
        # A fixed scale keeps the axis whatever the samples are.
        rows, low, high = display.chart_lines([1500.0, 1600.0], 10, 4, (0.0, 3150.0))
        self.assertEqual((low, high), (0.0, 3150.0))
        self.assertEqual(rows[0], "  ")
        self.assertEqual(rows[-1], "██")
        rows, _low, _high = display.chart_lines([5000.0, -10.0], 10, 2, (0.0, 3150.0))
        self.assertEqual(rows, ["█ ", "█▁"])
        self.assertEqual(display.chart_lines([], 10, 3), ([], 0.0, 0.0))
        rows, _low, _high = display.chart_lines([float(index) for index in range(100)], 20, 4)
        self.assertEqual(len(rows[0]), 20)

    def test_fixed_scale(self) -> None:
        self.assertEqual(display.graph_scale(Device("pot", "adc", 32)), (0.0, 3150.0))
        self.assertEqual(display.graph_scale(Device("b", "button", 0)), (0.0, 1.0))
        self.assertEqual(display.graph_scale(Device("fan", "pwm", 4)), (0.0, 1.0))
        self.assertEqual(display.graph_scale(Device("arm", "servo", 13)), (0.0, 180.0))
        self.assertIsNone(display.graph_scale(Device("water", "ds18b20", 4)))
        self.assertIsNone(display.graph_scale(None))
        # The same values look the same in each window, not stretched.
        self.assertEqual(display.sparkline([1575.0, 1580.0], 10, (0.0, 3150.0)), "▅▅")
        self.assertEqual(display.sparkline([1575.0, 1580.0], 10), "▁█")
        self.assertEqual(display.sparkline([0.0, 1.0], 10, (0.0, 1.0)), "▁█")

    def test_format_value(self) -> None:
        self.assertEqual(display.format_value(Device("led", "led", 2), 1.0), "ON")
        self.assertEqual(display.format_value(Device("fan", "pwm", 4), 0.25), "25.0 %")
        self.assertEqual(display.format_value(Device("arm", "servo", 13), 90.0), "90.0°")
        pot = Device("pot", "adc", 32, scale=0.001, units="V")
        self.assertEqual(display.format_value(pot, 1650.0), "1.65 V")
        self.assertEqual(display.format_value(pot, None), "—")
        self.assertEqual(display.format_value(None, "up"), "up")

    def test_steps_and_toggles(self) -> None:
        fan = Device("fan", "pwm", 4)
        self.assertEqual(display.step_value(fan, 0.98, 1), 1.0)
        self.assertEqual(display.step_value(fan, 0.5, -1), 0.45)
        arm = Device("arm", "servo", 13, initial=90.0)
        self.assertEqual(display.step_value(arm, None, 1), 95.0)
        self.assertEqual(display.toggle_value(arm, 95.0), 0.0)
        led = Device("led", "led", 2)
        self.assertEqual(display.toggle_value(led, 1.0), 0.0)
        self.assertEqual(display.toggle_value(led, None), 1.0)
        with self.assertRaises(ValueError):
            display.step_value(Device("pot", "adc", 32), 1.0, 1)

    def test_parse_output_text(self) -> None:
        self.assertEqual(display.parse_output_text(Device("led", "led", 2), "on"), (1.0, None))
        self.assertEqual(display.parse_output_text(Device("arm", "servo", 13), "45°"), (45.0, None))
        with self.assertRaises(ValueError):
            display.parse_output_text(Device("arm", "servo", 13), "200")
        with self.assertRaises(ValueError):
            display.parse_output_text(Device("arm", "servo", 13), "left")

    def test_parse_pwm_text(self) -> None:
        cases = {
            "0": 0.0,
            "0.25": 0.25,
            "0.999": 0.999,
            "1": 0.01,
            "25": 0.25,
            "100": 1.0,
            "40%": 0.4,
            "0.5%": 0.005,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                value, note = display.parse_pwm_text(text)
                self.assertAlmostEqual(value, expected)
                self.assertIsNone(note)
        value, note = display.parse_pwm_text("150")
        self.assertEqual(value, 1.0)
        self.assertEqual(note, "150 is above 100, so 100 % is used")
        self.assertEqual(display.parse_output_text(Device("fan", "pwm", 4), "250%")[0], 1.0)
        for bad in ("-1", "fast", "", "nan"):
            with self.subTest(text=bad), self.assertRaises(ValueError):
                display.parse_pwm_text(bad)

    def test_format_duration(self) -> None:
        self.assertEqual(display.format_duration(5000), "5s")
        self.assertEqual(display.format_duration(65000), "1m 05s")
        self.assertEqual(display.format_duration(3_725_000), "1h 02m 05s")


if __name__ == "__main__":
    unittest.main()

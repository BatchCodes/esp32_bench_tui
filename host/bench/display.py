"""Text helpers for the TUI that need no terminal: value text, sparklines,
stale-data levels and output steps."""

from __future__ import annotations

import math

from bench.config import Device

SPARK_CHARS = "▁▂▃▄▅▆▇█"
STALE_S = 2.0
LOST_S = 3.0
PWM_STEP = 0.05
SERVO_STEP_DEG = 5.0


def staleness(age_s: float | None) -> str:
    """'fresh', 'stale' (grey, after 2 s) or 'lost' (red, after 3 s)."""
    if age_s is None or age_s >= LOST_S:
        return "lost"
    if age_s >= STALE_S:
        return "stale"
    return "fresh"


# The highest calibrated ADC reading at 12 dB attenuation on the ESP32, in mV.
# A floating or pulled-up pin reads this value.
ADC_FULL_SCALE_MV = 3150.0
FIXED_SCALES = {
    "adc": (0.0, ADC_FULL_SCALE_MV),
    "digital_in": (0.0, 1.0),
    "digital_out": (0.0, 1.0),
    "pwm": (0.0, 1.0),
    "servo": (0.0, 180.0),
}

Scale = tuple[float, float]


def graph_scale(device: Device | None) -> Scale | None:
    """The fixed graph scale of a pin, in the units that the agent sends, or
    None when the graph scales to its own values (sensors, counters, logs)."""
    if device is None:
        return None
    return FIXED_SCALES.get(device.mode)


def _scale_of(window: list[float], scale: Scale | None) -> Scale:
    if scale is not None:
        return scale
    return min(window), max(window)


def _fraction(value: float, low: float, high: float) -> float:
    span = high - low
    if span <= 0:
        return 0.0
    return min(1.0, max(0.0, (value - low) / span))


def sparkline(samples: list[float], width: int, scale: Scale | None = None) -> str:
    """The last width samples as block characters. With no scale, the graph
    scales to its own low and high values."""
    window = [value for value in samples[-width:] if not math.isnan(value)]
    if not window:
        return ""
    low, high = _scale_of(window, scale)
    top = len(SPARK_CHARS) - 1
    return "".join(SPARK_CHARS[round(_fraction(value, low, high) * top)] for value in window)


def chart_lines(
    samples: list[float], width: int, height: int, scale: Scale | None = None
) -> tuple[list[str], float, float]:
    """A bar chart of the last width samples, height rows high, top row first.
    Returns the rows and the low and high values of the scale."""
    window = [value for value in samples[-width:] if not math.isnan(value)]
    if not window or width <= 0 or height <= 0:
        return [], 0.0, 0.0
    low, high = _scale_of(window, scale)
    eighths_total = height * 8
    rows = [[" "] * len(window) for _ in range(height)]
    for column, value in enumerate(window):
        # Each sample shows at least one low bar, so the base line is visible.
        level = max(1, round(_fraction(value, low, high) * eighths_total))
        full, rest = divmod(level, 8)
        for row in range(full):
            rows[height - 1 - row][column] = "█"
        if rest and full < height:
            rows[height - 1 - full][column] = SPARK_CHARS[rest - 1]
    return ["".join(row) for row in rows], low, high


def format_value(device: Device | None, value: float | str | None) -> str:
    """A value from the board in the units of its device."""
    if value is None:
        return "—"
    if isinstance(value, str):
        return value
    if device is not None and device.mode == "i2c":
        return "not scanned" if math.isnan(value) else f"{value:.0f} devices"
    if math.isnan(value):
        return "error"
    if device is None:
        return f"{value:g}"
    mode = device.mode
    if mode == "uart":
        return f"{value:.0f} B received"
    if mode in ("digital_in", "digital_out"):
        return "ON" if value >= 0.5 else "off"
    if mode == "pwm":
        return f"{value * 100:.1f} %"
    if mode == "servo":
        return f"{value:.1f}°"
    shown = device.display_value(value)
    units = f" {device.units}" if device.units else ""
    if abs(shown) >= 100:
        return f"{shown:.0f}{units}"
    return f"{shown:.3g}{units}"


def hx711_channel_text(raw: float | None, ready: bool, timeouts: int, tare: float | None) -> str:
    """One HX711 channel: the raw count since the tare, or why there is none."""
    if raw is None or math.isnan(raw):
        return f"no data ({timeouts} timeouts)" if timeouts else "waiting"
    value = raw - (tare or 0.0)
    text = f"{value:+.0f}" if tare is not None else f"{value:.0f}"
    if not ready:
        text += f" (stale, {timeouts} timeouts)"
    return text


def hx711_text(raw1: float | None, info, tares: tuple[float | None, float | None] = (None, None)) -> str:
    """Both channels of an HX711 device on one line."""
    if info is None:
        return "waiting"
    ready = info.ready + (False, False)
    timeouts = info.timeouts + (0, 0)
    first = hx711_channel_text(raw1, ready[0], timeouts[0], tares[0])
    if len(info.ready) < 2:
        return first
    second = hx711_channel_text(info.raw2, ready[1], timeouts[1], tares[1])
    return f"1: {first} · 2: {second}"


def format_rate(rate: float | None) -> str:
    if rate is None:
        return "—"
    return f"{rate:.2f} Hz" if rate < 100 else f"{rate:.0f} Hz"


def format_sensor(device: Device, value: float | str | None, humidity: float | None) -> str:
    """A temperature, with the humidity for a DHT sensor."""
    text = format_value(device, value)
    if device.mode in ("dht11", "dht22") and humidity is not None:
        humidity_text = "error" if math.isnan(humidity) else f"{humidity:.1f} %RH"
        text = f"{text} · {humidity_text}"
    return text


def step_value(device: Device, current: float | None, direction: int) -> float:
    """The next output value for one step up (1) or down (-1)."""
    if device.mode == "digital_out":
        return 1.0 if direction > 0 else 0.0
    if device.mode == "pwm":
        base = current if current is not None else device.initial
        return round(min(1.0, max(0.0, base + direction * PWM_STEP)), 4)
    if device.mode == "servo":
        base = current if current is not None else device.initial
        return min(180.0, max(0.0, base + direction * SERVO_STEP_DEG))
    raise ValueError(f"{device.name} is not an output")


def toggle_value(device: Device, current: float | None) -> float:
    """The value for the toggle key: on and off for a digital output, 0 and
    full for PWM, 0 and 180 for a servo."""
    if device.mode == "digital_out":
        return 0.0 if (current or 0.0) >= 0.5 else 1.0
    if device.mode == "pwm":
        return 0.0 if (current or 0.0) > 0.0 else 1.0
    if device.mode == "servo":
        return 0.0 if (current or 0.0) >= 90.0 else 180.0
    raise ValueError(f"{device.name} is not an output")


PWM_PERCENT_LIMIT = 100.0


def _number(text: str, what: str) -> float:
    try:
        value = float(text)
    except ValueError as error:
        raise ValueError(f"'{text}' is not a number. Enter {what}") from error
    if value != value:
        raise ValueError(f"enter {what}")
    return value


def parse_pwm_text(text: str) -> tuple[float, str | None]:
    """A typed PWM value as a duty cycle from 0.0 to 1.0, and a note when the
    value was changed. Below 1 is a duty cycle (0.25 is 25 %). From 1 to 100
    is a percentage (25 is 25 %). Above 100 is 100 %. A trailing % always
    means a percentage."""
    what = "a duty below 1 (0.25) or a percentage from 1 to 100 (25)"
    text = text.strip()
    percent = text.endswith("%")
    value = _number(text.rstrip("%").strip(), what)
    if value < 0:
        raise ValueError(f"{text} is below 0. Enter {what}")
    if not percent and value < 1.0:
        return value, None
    if value > PWM_PERCENT_LIMIT:
        return 1.0, f"{value:g} is above 100, so 100 % is used"
    return value / 100.0, None


def parse_output_text(device: Device, text: str) -> tuple[float, str | None]:
    """A typed output value, and a note when the value was changed."""
    text = text.strip().lower()
    if device.mode == "digital_out":
        if text in ("1", "on", "high", "true"):
            return 1.0, None
        if text in ("0", "off", "low", "false"):
            return 0.0, None
        raise ValueError("enter 0 or 1")
    if device.mode == "pwm":
        return parse_pwm_text(text)
    if device.mode == "servo":
        value = _number(text.rstrip("°"), "an angle of 0 to 180")
        if not 0.0 <= value <= 180.0:
            raise ValueError("enter an angle of 0 to 180")
        return value, None
    raise ValueError(f"{device.name} is not an output")


def format_duration(milliseconds: int) -> str:
    seconds = milliseconds // 1000
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"

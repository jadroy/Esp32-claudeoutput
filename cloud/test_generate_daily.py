import unittest
from datetime import datetime

from generate_daily import TIMEZONE, build_signal


def weather(hours, temps, rain, high=68, low=53):
    return {
        "hourly": {
            "time": hours,
            "temperature_2m": temps,
            "precipitation_probability": rain,
            "weather_code": [0] * len(hours),
        },
        "daily": {"temperature_2m_max": [high], "temperature_2m_min": [low]},
    }


class SignalTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 17, 9, 30, tzinfo=TIMEZONE)
        self.hours = [f"2026-07-17T{hour:02d}:00" for hour in range(9, 19)]

    def test_rain_timing_wins(self):
        data = weather(self.hours, [60] * 10, [0, 0, 5, 10, 20, 50, 65, 70, 30, 10])
        text, source = build_signal(data, {}, self.now)
        self.assertEqual(source, "weather")
        self.assertIn("rain starts around 2pm", text)

    def test_good_air_quality(self):
        data = weather(self.hours, [60] * 10, [0] * 10)
        air = {"hourly": {"time": self.hours, "us_aqi": [22] * 10}}
        text, source = build_signal(data, air, self.now)
        self.assertEqual(source, "air-quality")
        self.assertIn("unusually good (22)", text)

    def test_outdoor_window_fallback(self):
        data = weather(self.hours, [48, 52, 55, 60, 65, 70, 73, 74, 70, 64], [0] * 10)
        text, source = build_signal(data, {}, self.now)
        self.assertEqual(source, "weather")
        self.assertIn("best outside window: 10am to 3pm", text)

    def test_cool_day_uses_warmest_window(self):
        data = weather(
            self.hours,
            [52, 53, 54, 56, 58, 58, 57, 55, 54, 53],
            [0] * 10,
            high=58,
            low=52,
        )
        text, source = build_signal(data, {}, self.now)
        self.assertEqual(source, "weather")
        self.assertEqual(text, "today stays cool: 52 to 58. warmest: 12pm to 4pm")


if __name__ == "__main__":
    unittest.main()

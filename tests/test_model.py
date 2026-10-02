"""Offline contract tests: no Home Assistant or real API required."""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import unittest

PATH = Path(__file__).resolve().parents[1] / "custom_components/kazhydromet/model.py"
spec = importlib.util.spec_from_file_location("kazhydromet_model_test", PATH)
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)

NOW = datetime(2026, 10, 2, 6, 0, tzinfo=timezone.utc)
STATION = model.Station("0-20000-0-36870", "ALMATY OGMS", 43.2, 76.9)


def reading(name, value, when=NOW, description=None):
    return {"properties": {
        "wigos_station_identifier": STATION.identifier,
        "reportTime": when.isoformat(),
        "name": name,
        "value": value,
        "units": {
            "air_temperature": "Celsius",
            "cloud_cover_total": "%",
            "wind_speed": "m/s",
            "dewpoint_temperature": "Celsius",
        }.get(name),
        "description": description,
    }}


class ModelTests(unittest.TestCase):
    def test_humidity_derived_from_measured_dewpoint(self):
        rows = [reading("air_temperature", 20), reading("dewpoint_temperature", 10)]
        result = model.parse_observations(rows, STATION, NOW, timedelta(hours=4))
        self.assertGreater(result.humidity, 50)
        self.assertLess(result.humidity, 60)

    def test_wrong_unit_is_not_interpreted_as_celsius(self):
        row = reading("air_temperature", 20)
        row["properties"]["units"] = "Fahrenheit"
        with self.assertRaises(model.DataContractError):
            model.parse_observations([row], STATION, NOW, timedelta(hours=4))

    def test_zero_temperature_and_clouds_are_valid(self):
        rows = [reading("air_temperature", 0), reading("cloud_cover_total", 0)]
        result = model.parse_observations(rows, STATION, NOW, timedelta(hours=4))
        self.assertEqual(result.temperature, 0)
        self.assertEqual(result.cloud_coverage, 0)

    def test_stale_temperature_does_not_become_current(self):
        rows = [reading("air_temperature", 15, NOW - timedelta(hours=7))]
        with self.assertRaises(model.DataContractError):
            model.parse_observations(rows, STATION, NOW, timedelta(hours=4))

    def test_different_reports_cannot_be_combined(self):
        rows = [
            reading("air_temperature", 15, NOW - timedelta(hours=1)),
            reading("wind_speed", 5, NOW),
        ]
        result = model.parse_observations(rows, STATION, NOW, timedelta(hours=4))
        self.assertIsNone(result.wind_speed)

    def test_missing_required_temperature_fails(self):
        with self.assertRaises(model.DataContractError):
            model.parse_observations([reading("humidity", 25)], STATION, NOW, timedelta(hours=4))

    def test_invalid_reading_never_becomes_zero(self):
        self.assertIsNone(model.numeric(None))
        self.assertIsNone(model.numeric(True))
        self.assertIsNone(model.numeric(float("nan")))

    def test_station_geometry_and_identifier(self):
        rows = [{"id": STATION.identifier, "geometry": {
            "type": "Point", "coordinates": [76.9, 43.2]
        }, "properties": {"name": "ALMATY OGMS", "wigos_station_identifier": STATION.identifier}}]
        self.assertEqual(model.parse_stations(rows)[0], STATION)

    def test_condition_derived_only_from_source(self):
        self.assertIsNone(model.condition(None, None, False))
        self.assertEqual(model.condition(None, 0, True), "clear-night")
        self.assertEqual(model.condition("RAIN", 0, False), "rainy")


if __name__ == "__main__":
    unittest.main()


class WrfTests(unittest.TestCase):
    """Confirm actual WRF units, geographic selection and freshness rules."""

    def payload(self):
        return {
            "meta": {
                "generated_at": "2026-10-01T18:45:40Z",
                "timestep_hours": 3,
                "units": {
                    "temp_blend": "C",
                    "wind_speed": "m/s",
                    "precip_mm": "mm",
                    "pressure_hpa": "hPa",
                    "humidity_rel": "%",
                    "cloud_fraction": "0-1",
                },
            },
            "stations": [
                {"rep_id": 36870, "name": "ALMATY", "lat": 43.239364, "lon": 76.932951}
            ],
            "forecasts": {
                "36870": [
                    {"datetime": "2026-10-02T00:00:00Z", "temp_blend": 13.39,
                     "wind_speed": 5.41, "precip_mm": 4.9, "pressure_hpa": 913.6,
                     "humidity_rel": 80.0, "cloud_fraction": 0.24},
                    {"datetime": "2026-10-02T03:00:00Z", "temp_blend": 15.92,
                     "wind_speed": 0, "precip_mm": 0, "pressure_hpa": 914.0,
                     "humidity_rel": 42, "cloud_fraction": 0},
                    {"datetime": "2026-10-02T06:00:00Z", "temp_blend": 20.45,
                     "wind_speed": 3.5, "precip_mm": 0.0, "pressure_hpa": 913.8,
                     "humidity_rel": 27, "cloud_fraction": 0},
                    {"datetime": "2026-10-02T09:00:00Z", "temp_blend": 19.0,
                     "precip_mm": 0},
                ],
            },
        }

    def test_forecast_parses_verified_wrf_schema(self):
        forecast = model.parse_wrf(self.payload(), 43.25, 76.95, NOW)
        self.assertEqual(forecast.station.identifier, "36870")
        self.assertEqual(forecast.points[0].cloud_coverage, 24)
        self.assertEqual(forecast.points[1].precipitation, 0)
        self.assertEqual(forecast.current(NOW).temperature, 20.45)

    def test_invalid_cloud_fraction_is_not_silently_clamped(self):
        payload = self.payload()
        payload["forecasts"]["36870"][0]["cloud_fraction"] = 50
        with self.assertRaises(model.DataContractError):
            model.parse_wrf(payload, 43.25, 76.95, NOW)

    def test_stale_run_is_rejected(self):
        payload = self.payload()
        payload["meta"]["generated_at"] = "2026-09-29T00:00:00Z"
        with self.assertRaises(model.DataContractError):
            model.parse_wrf(payload, 43.25, 76.95, NOW)



class WeatherConditionTests(unittest.TestCase):
    """Regression tests from real HA WRF output on 2026-10-02."""

    def point(self, precipitation, temperature=12, clouds=0):
        return model.ForecastPoint(
            NOW, temperature, precipitation, 50, 900, 2, clouds,
        )

    def test_rain_overrides_clouds_even_at_zero_cloud_cover(self):
        self.assertEqual(model.forecast_condition(12.0, 8.2, 0, False), "rainy")
        self.assertEqual(model.forecast_condition(2.7, 11.5, 23, True), "rainy")
        self.assertEqual(model.forecast_condition(0.1, 6.0, 1, False), "rainy")

    def test_dry_weather_still_uses_clouds_and_day_night(self):
        self.assertEqual(model.forecast_condition(0, 10, 0, False), "sunny")
        self.assertEqual(model.forecast_condition(0, 10, 0, True), "clear-night")
        self.assertIsNone(model.forecast_condition(None, 10, None, True))

    def test_snow_only_derived_from_subzero_air_temperature(self):
        self.assertEqual(model.forecast_condition(1.0, -3, 10, False), "snowy")

    def test_daily_rain_prioritized_over_mean_sunshine(self):
        points = [self.point(0)] * 6
        points.extend([self.point(2.7, clouds=23), self.point(12, clouds=33)])
        self.assertEqual(model.daily_forecast_condition(points, 9), "rainy")

    def test_dry_daily_preserves_cloud_based_condition(self):
        points = [self.point(0) for _ in range(8)]
        self.assertEqual(model.daily_forecast_condition(points, 0), "sunny")

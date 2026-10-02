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
        "description": description,
    }}


class ModelTests(unittest.TestCase):
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

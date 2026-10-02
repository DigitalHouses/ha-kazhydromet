"""Strict WRF forecast adapter tests, without Home Assistant runtime."""

import importlib.util
import pathlib
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone

PATH = pathlib.Path(__file__).resolve().parents[1] / "custom_components/kazhydromet"
pkg = types.ModuleType("kazhydromet")
pkg.__path__ = [str(PATH)]
sys.modules.setdefault("kazhydromet", pkg)
for name in ("model", "forecast"):
    spec = importlib.util.spec_from_file_location("kazhydromet." + name, PATH / (name + ".py"))
    obj = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = obj
    spec.loader.exec_module(obj)
from kazhydromet.forecast import parse_wrf
from kazhydromet.model import DataContractError

NOW = datetime(2026, 10, 2, 6, 0, tzinfo=timezone.utc)


def forecast_data():
    timestamps = [
        (NOW + timedelta(hours=i * 3)).isoformat() for i in range(73)
    ]
    return {
        "meta": {
            "generated_at": (NOW - timedelta(hours=12)).isoformat(),
            "timestep_hours": 3,
            "units": {
                "temp_blend": "C", "wind_speed": "m/s",
                "precip_mm": "mm", "pressure_hpa": "hPa",
                "humidity_rel": "%", "cloud_fraction": "0-1"
            }
        },
        "stations": [{"rep_id": 36870, "name": "ALMATY", "lat": 43.23, "lon": 76.93}],
        "forecasts": {"36870": [
            {"datetime": t, "temp_blend": 20, "wind_speed": 2,
             "precip_mm": 0.5, "pressure_hpa": 913, "humidity_rel": 45,
             "cloud_fraction": 0.4} for t in timestamps
        ]}
    }


class ForecastTests(unittest.TestCase):
    def test_valid_three_hour_forecast_and_daily(self):
        result = parse_wrf(forecast_data(), 43.2, 76.9, "Asia/Almaty", NOW)
        self.assertEqual(len(result.hourly), 73)
        self.assertEqual(result.station_name, "ALMATY")
        self.assertEqual(result.hourly[0]["native_temperature"], 20)
        self.assertTrue(len(result.daily) >= 9)

    def test_required_measurement_must_exist(self):
        data = forecast_data()
        data["forecasts"]["36870"][0].pop("temp_blend")
        with self.assertRaises(DataContractError):
            parse_wrf(data, 43.2, 76.9, "Asia/Almaty", NOW)

    def test_outdated_forecast_is_rejected(self):
        data = forecast_data()
        data["meta"]["generated_at"] = (NOW - timedelta(days=4)).isoformat()
        with self.assertRaises(DataContractError):
            parse_wrf(data, 43.2, 76.9, "Asia/Almaty", NOW)

    def test_invalid_cloud_fraction_is_rejected(self):
        data = forecast_data()
        data["forecasts"]["36870"][0]["cloud_fraction"] = 200
        with self.assertRaises(DataContractError):
            parse_wrf(data, 43.2, 76.9, "Asia/Almaty", NOW)


if __name__ == "__main__":
    unittest.main()

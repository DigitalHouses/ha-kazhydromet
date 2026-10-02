"""Verify diagnostic translation keys and locale contracts without HA runtime."""

import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/kazhydromet"
DIAGNOSTICS = {
    "observed_at",
    "station",
    "source",
    "model_run",
    "forecast_location",
}
SOURCE_STATES = {"wis2_observation", "wrf_model"}


class DiagnosticTranslationTests(unittest.TestCase):
    def test_locales_and_strings_cover_every_diagnostic(self):
        for file in ("strings.json", "translations/en.json", "translations/ru.json"):
            data = json.loads((ROOT / file).read_text(encoding="utf-8"))
            sensors = data["entity"]["sensor"]
            self.assertEqual(set(sensors), DIAGNOSTICS, file)
            self.assertEqual(
                set(sensors["source"]["state"]), SOURCE_STATES, file,
            )
            self.assertTrue(all(sensors[k].get("name") for k in DIAGNOSTICS))

    def test_sensor_entities_use_localized_name_not_hardcoded_english(self):
        tree = ast.parse((ROOT / "sensor.py").read_text(encoding="utf-8"))
        attributes = {
            target.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        }
        self.assertIn("_attr_translation_key", attributes)
        self.assertNotIn("_attr_name", attributes)


if __name__ == "__main__":
    unittest.main()

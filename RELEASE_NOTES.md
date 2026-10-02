# Kazhydromet 0.1.0

First HACS release of the native Home Assistant Kazhydromet integration.

- Official WIS2 SYNOP station observations with source timestamps.
- Official WRF forecast, native 3-hour hourly data and complete-day daily high/low summaries.
- Weather conditions prioritize actual forecast precipitation over cloud cover.
- Automatic nearby station selection or manual WIGOS station selection.
- Diagnostic sensors with Russian and English localized names.
- Separate provenance of WIS2 observations and WRF model fallback.
- No additional App, MQTT broker, or third-party weather proxy needed.

**Limitations:** The official WRF grid has a 3-hour interval and does not align with every local midnight. The daily precipitation total is intentionally not estimated for Asia/Almaty. Do not rely on the integration for safety-critical automation before further operational testing. Official API data use conditions remain subject to the provider.

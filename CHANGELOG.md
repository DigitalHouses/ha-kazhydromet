# Changelog

## 0.1.0 (pre-release)

- Added HACS-ready native Home Assistant WeatherEntity and UI Config Flow.
- Integrated official WIS2 SYNOP measurements and WRF forecasts.
- Added native 3-hour forecast points and complete-day summaries.
- Validated public WRF source units, timestamp schema and station coordinates.
- Added station selection, source/freshness diagnostics and strict data contracts.
- Added WRF caching, Russian/English translations, upstream probes and offline tests.
- Fixed rain being classified as sunny/clear-night, including daily conditions.
- Fixed current dew-point access and documented why exact daily precipitation cannot be summed for UTC+5.

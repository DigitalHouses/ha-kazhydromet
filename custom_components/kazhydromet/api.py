"""Minimal async WIS2 OGC API Features client."""

from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urljoin, urlsplit

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import LOOKBACK, MAX_AGE, SYNOP_COLLECTION, WIS2_BASE, WRF_CACHE_INTERVAL, WRF_URL
from .model import (
    DataContractError,
    ForecastData,
    Observation,
    Station,
    parse_observations,
    parse_stations,
    parse_wrf,
)


class APIError(Exception):
    """WIS2 network, availability or document contract problem."""


class KazhydrometAPI:
    """Fetch Kazhydromet stations and time-bounded SYNOP reports."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session
        self._forecast_cache: ForecastData | None = None
        self._forecast_received: datetime | None = None

    async def _features(self, path: str, params: dict) -> list[dict]:
        url = f"{WIS2_BASE}/{path}"
        features: list[dict] = []
        visited: set[str] = set()
        # Explicitly fail rather than silently using a truncated collection.
        for _ in range(12):
            if url in visited:
                raise APIError("WIS2 pagination loop")
            visited.add(url)
            try:
                async with self._session.get(
                    url, params=params, timeout=ClientTimeout(total=35)
                ) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
            except (ClientError, TimeoutError, ValueError) as exc:
                raise APIError(f"WIS2 request failed: {type(exc).__name__}") from exc
            if (
                not isinstance(payload, dict)
                or payload.get("type") != "FeatureCollection"
                or not isinstance(payload.get("features"), list)
            ):
                raise APIError("Unexpected WIS2 FeatureCollection schema")
            features.extend(payload["features"])
            next_href = next(
                (
                    link.get("href")
                    for link in payload.get("links", [])
                    if isinstance(link, dict) and link.get("rel") == "next"
                ),
                None,
            )
            if not next_href:
                return features
            url = urljoin(url, next_href)
            if urlsplit(url).hostname != "wis2box.kazhydromet.kz":
                raise APIError("WIS2 pagination redirected to an unknown host")
            params = {}
        raise APIError("WIS2 result exceeded pagination safety limit")

    async def forecast(self, latitude: float, longitude: float) -> ForecastData:
        """Fetch and cache the official WRF run (about 8.5 MB, 3-hour cache)."""
        now = datetime.now(timezone.utc)
        if (
            self._forecast_cache is not None
            and self._forecast_received is not None
            and now - self._forecast_received < WRF_CACHE_INTERVAL
        ):
            # Keep verifying the model run freshness even while cached.
            if now - self._forecast_cache.generated_at <= timedelta(hours=36):
                return self._forecast_cache
        try:
            async with self._session.get(
                WRF_URL, timeout=ClientTimeout(total=75)
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
        except (ClientError, TimeoutError, ValueError) as exc:
            raise APIError(f"WRF request failed: {type(exc).__name__}") from exc
        try:
            forecast = parse_wrf(payload, latitude, longitude, now)
        except DataContractError as exc:
            raise APIError(str(exc)) from exc
        self._forecast_cache = forecast
        self._forecast_received = now
        return forecast

    async def stations(self) -> list[Station]:
        """Return all available stations, including pagination."""
        items = await self._features("collections/stations/items", {"f": "json", "limit": 500})
        try:
            return parse_stations(items)
        except DataContractError as exc:
            raise APIError(str(exc)) from exc

    async def observation(self, station: Station) -> Observation:
        """Fetch observations for one station and validate report freshness."""
        now = datetime.now(timezone.utc)
        earliest = now - LOOKBACK
        iso = lambda value: value.isoformat().replace("+00:00", "Z")
        path = (
            "collections/"
            + quote(SYNOP_COLLECTION, safe="")
            + "/items"
        )
        items = await self._features(
            path,
            {
                "f": "json",
                "wigos_station_identifier": station.identifier,
                "datetime": f"{iso(earliest)}/{iso(now)}",
                "limit": 500,
            },
        )
        return parse_observations(items, station, now, MAX_AGE)

"""Keyless context adapters. Context never enters model features automatically."""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import math
import os
import re
import threading
import time
from typing import Any
from urllib.parse import urlparse

import requests

SPORT_PATHS = {
    "NFL": "football/nfl", "NBA": "basketball/nba",
    "MLB": "baseball/mlb", "NHL": "hockey/nhl",
}
_CACHE: OrderedDict[tuple, tuple[float, dict, str]] = OrderedDict()
_LOCK = threading.Lock()
_MAX_CACHE_ENTRIES = 256
USER_AGENT = "PhilthySports/1.5 public-context (https://github.com/filthycashout/betp-app-)"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _json(url: str, *, params: dict | None = None, ttl: int = 600) -> tuple[dict, str]:
    """Bounded cache preserves the original retrieval timestamp on cache hits."""
    key = (url, tuple(sorted((params or {}).items())))
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            _CACHE.move_to_end(key)
            return hit[1], hit[2]
    response = requests.get(
        url, params=params, headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=(3, 8), allow_redirects=False,
    )
    response.raise_for_status()
    if response.status_code != 200:
        raise ValueError("unexpected provider status")
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("provider response must be an object")
    retrieved_at = utc_now().isoformat()
    with _LOCK:
        _CACHE[key] = (time.monotonic(), data, retrieved_at)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _MAX_CACHE_ENTRIES:
            _CACHE.popitem(last=False)
    return data, retrieved_at


def _unavailable(provider: str | None, reason: str) -> dict:
    return {"available": False, "provider": provider, "reason": reason,
            "credential_required": False, "used_in_prediction": False,
            "historical_training_eligible": False}


def _nws(lat: float, lon: float, target: datetime) -> dict:
    point, _ = _json(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}", ttl=86400)
    props = point.get("properties") or {}
    forecast_url = props.get("forecastHourly") or ""
    # Only follow the documented provider path; never an arbitrary upstream URL.
    parsed = urlparse(forecast_url)
    if (parsed.scheme != "https" or parsed.netloc != "api.weather.gov"
            or not re.fullmatch(r"/gridpoints/[A-Z]{3}/-?\d+,-?\d+/forecast/hourly", parsed.path)
            or parsed.query or parsed.fragment):
        return _unavailable("NWS", "NO_SUPPORTED_NWS_GRID")
    data, retrieved = _json(forecast_url, params={"units": "si"})
    props = data.get("properties") or {}
    issued = props.get("updateTime") or props.get("generatedAt")
    try:
        age = utc_now() - timestamp(issued)
        if age < timedelta(seconds=-60) or age > timedelta(hours=12):
            return _unavailable("NWS", "STALE_OR_FUTURE_FORECAST")
    except (ValueError, TypeError):
        return _unavailable("NWS", "MISSING_FORECAST_ISSUE_TIME")
    for period in props.get("periods") or []:
        try:
            start, end = timestamp(period.get("startTime")), timestamp(period.get("endTime"))
        except (ValueError, TypeError):
            continue
        if not start <= target < end:
            continue
        temperature = _number(period.get("temperature"))
        unit = period.get("temperatureUnit")
        if unit == "F" and temperature is not None:
            temperature = (temperature - 32) * 5 / 9
        elif unit != "C":
            temperature = None
        if temperature is None:
            return _unavailable("NWS", "INVALID_TEMPERATURE")
        wind_text = str(period.get("windSpeed") or "")
        wind = re.fullmatch(r"(\d+(?:\.\d+)?)(?: to (\d+(?:\.\d+)?))? (km/h|mph)", wind_text)
        wind_low = wind_high = None
        if wind:
            factor = 1.609344 if wind[3] == "mph" else 1
            wind_low, wind_high = float(wind[1]) * factor, float(wind[2] or wind[1]) * factor
        rain = _number((period.get("probabilityOfPrecipitation") or {}).get("value"))
        if rain is not None and not 0 <= rain <= 100:
            rain = None
        return {
            "available": True, "provider": "NWS", "credential_required": False,
            "target_time": target.isoformat(), "valid_from": start.isoformat(),
            "valid_until": end.isoformat(), "provider_issued_at": issued,
            "retrieved_at": retrieved, "temperature_c": round(temperature, 1),
            "wind_kmh_min": round(wind_low, 1) if wind_low is not None else None,
            "wind_kmh_max": round(wind_high, 1) if wind_high is not None else None,
            "precipitation_probability_pct": rain,
            "summary": str(period.get("shortForecast") or "")[:200],
            "attribution": "US National Weather Service", "source_url": forecast_url,
            "used_in_prediction": False, "historical_training_eligible": False,
        }
    return _unavailable("NWS", "OUTSIDE_FORECAST_COVERAGE")


def _open_meteo(lat: float, lon: float, target: datetime) -> dict:
    # Public service is for non-commercial use. Never silently select a paid route.
    if os.getenv("OPEN_METEO_ACCESS", "disabled").lower() != "noncommercial":
        return _unavailable("Open-Meteo", "NONCOMMERCIAL_USE_OPT_IN_REQUIRED")
    data, retrieved = _json("https://api.open-meteo.com/v1/forecast", params={
        "latitude": round(lat, 4), "longitude": round(lon, 4), "timezone": "UTC",
        "hourly": "temperature_2m,precipitation_probability,wind_speed_10m",
        "temperature_unit": "celsius", "wind_speed_unit": "kmh", "forecast_days": 8,
    })
    hourly, units = data.get("hourly") or {}, data.get("hourly_units") or {}
    if (data.get("utc_offset_seconds") != 0 or units.get("temperature_2m") != "°C"
            or units.get("wind_speed_10m") != "km/h"
            or units.get("precipitation_probability") != "%"):
        return _unavailable("Open-Meteo", "UNEXPECTED_UNITS_OR_TIMEZONE")
    times = hourly.get("time") or []
    for i, value in enumerate(times):
        try:
            start = timestamp(value + "Z" if len(value) == 16 else value)
            end = start + timedelta(hours=1)
            if not start <= target < end:
                continue
            temp = _number(hourly["temperature_2m"][i])
            wind = _number(hourly["wind_speed_10m"][i])
            rain = _number(hourly["precipitation_probability"][i])
        except (ValueError, KeyError, IndexError, TypeError):
            continue
        if temp is None or wind is None or wind < 0 or rain is None or not 0 <= rain <= 100:
            return _unavailable("Open-Meteo", "INVALID_FORECAST_VALUES")
        return {
            "available": True, "provider": "Open-Meteo", "credential_required": False,
            "target_time": target.isoformat(), "valid_from": start.isoformat(),
            "valid_until": end.isoformat(), "provider_issued_at": None,
            "retrieved_at": retrieved, "temperature_c": temp,
            "wind_kmh_min": wind, "wind_kmh_max": wind,
            "precipitation_probability_pct": rain,
            "attribution": "Weather data by Open-Meteo.com (CC BY 4.0)",
            "source_url": "https://open-meteo.com/", "usage": "noncommercial",
            "used_in_prediction": False, "historical_training_eligible": False,
        }
    return _unavailable("Open-Meteo", "OUTSIDE_FORECAST_COVERAGE")


def weather_context(lat: float, lon: float, at: str | None = None, provider: str = "nws") -> dict:
    latitude, longitude = _number(lat), _number(lon)
    if latitude is None or longitude is None or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("invalid coordinates")
    if provider not in {"nws", "open_meteo"}:
        raise ValueError("provider must be nws or open_meteo")
    now = utc_now()
    target = timestamp(at) if at else now
    if target < now - timedelta(seconds=30):
        return _unavailable(provider, "PAST_EVENT_REQUIRES_ARCHIVED_PREGAME_FORECAST")
    if target > now + timedelta(days=7):
        return _unavailable(provider, "OUTSIDE_FORECAST_COVERAGE")
    try:
        result = _nws(latitude, longitude, target) if provider == "nws" else _open_meteo(latitude, longitude, target)
    except Exception as exc:
        result = _unavailable(provider, "UPSTREAM_UNAVAILABLE")
        result["error_type"] = type(exc).__name__
    result.update({"latitude": latitude, "longitude": longitude})
    return result


def game_weather_context(game: dict) -> dict:
    venue = game.get("venue") or {}
    if game.get("sport") not in {"MLB", "NFL"}:
        return _unavailable(None, "INDOOR_SPORT")
    if venue.get("outdoor") is not True:
        return _unavailable(None, "OUTDOOR_VENUE_NOT_CONFIRMED")
    if _number(venue.get("latitude")) is None or _number(venue.get("longitude")) is None:
        return _unavailable(None, "VENUE_COORDINATES_UNAVAILABLE")
    if not game.get("event_time"):
        return _unavailable(None, "EVENT_TIME_UNAVAILABLE")
    try:
        result = weather_context(venue["latitude"], venue["longitude"], game["event_time"])
    except ValueError:
        return _unavailable(None, "INVALID_VENUE_OR_EVENT_TIME")
    result["venue"] = venue.get("name")
    return result


def sports_news(sport: str, limit: int = 5) -> dict:
    if sport not in SPORT_PATHS:
        raise ValueError("unsupported sport")
    source = f"https://site.api.espn.com/apis/site/v2/sports/{SPORT_PATHS[sport]}/news"
    try:
        data, retrieved = _json(source, params={"limit": 20}, ttl=180)
        articles = data.get("articles")
        if not isinstance(articles, list):
            raise ValueError("missing articles")
        now, rows, seen = utc_now(), [], set()
        for item in articles:
            if not isinstance(item, dict):
                continue
            try:
                published = timestamp(item.get("published"))
            except (ValueError, TypeError):
                continue
            if not timedelta(seconds=-60) <= now - published <= timedelta(days=7):
                continue
            link = ((item.get("links") or {}).get("web") or {}).get("href") or ""
            parsed = urlparse(link)
            if parsed.scheme != "https" or parsed.hostname not in {"espn.com", "www.espn.com"}:
                continue
            title = str(item.get("headline") or "").strip()
            if not title or link in seen:
                continue
            seen.add(link)
            rows.append({"title": title[:300], "url": link, "published_at": published.isoformat()})
        rows.sort(key=lambda row: row["published_at"], reverse=True)
        return {"available": bool(rows), "provider": "ESPN", "sport": sport,
                "credential_required": False, "retrieved_at": retrieved,
                "articles": rows[:limit], "used_in_prediction": False,
                "historical_training_eligible": False,
                "note": "Current headlines only; not a verified injury or historical feature feed."}
    except Exception as exc:
        return {**_unavailable("ESPN", "UPSTREAM_UNAVAILABLE"), "sport": sport,
                "articles": [], "error_type": type(exc).__name__}

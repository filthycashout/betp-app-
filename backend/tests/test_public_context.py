from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import app as runtime
import public_context as context

NOW = datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(context, "utc_now", lambda: NOW)
    context._CACHE.clear()


def nws_json(url, **kwargs):
    if "/points/" in url:
        return {"properties": {"forecastHourly": "https://api.weather.gov/gridpoints/SGX/57,14/forecast/hourly"}}, NOW.isoformat()
    return {"properties": {"updateTime": NOW.isoformat(), "periods": [{
        "startTime": NOW.isoformat(), "endTime": (NOW + timedelta(hours=1)).isoformat(),
        "temperature": 20, "temperatureUnit": "C", "windSpeed": "10 to 15 km/h",
        "probabilityOfPrecipitation": {"value": 25}, "shortForecast": "Partly cloudy",
    }]}}, NOW.isoformat()


def test_nws_units_period_and_non_model_contract(monkeypatch):
    monkeypatch.setattr(context, "_json", nws_json)
    row = context.weather_context(32.7, -117.1)
    assert row["available"] and row["temperature_c"] == 20
    assert row["wind_kmh_min"] == 10 and row["wind_kmh_max"] == 15
    assert row["provider_issued_at"] == NOW.isoformat()
    assert row["used_in_prediction"] is False
    assert row["historical_training_eligible"] is False


def test_past_weather_never_fetches_current_forecast(monkeypatch):
    monkeypatch.setattr(context, "_json", lambda *a, **k: pytest.fail("must not fetch"))
    result = context.weather_context(32.7, -117.1, (NOW-timedelta(days=1)).isoformat())
    assert result["reason"] == "PAST_EVENT_REQUIRES_ARCHIVED_PREGAME_FORECAST"


@pytest.mark.parametrize("issued", [NOW-timedelta(days=1), NOW+timedelta(hours=1)])
def test_stale_or_future_provider_timestamp_rejected(monkeypatch, issued):
    def fetch(url, **kwargs):
        data, fetched = nws_json(url, **kwargs)
        if "/gridpoints/" in url:
            data["properties"]["updateTime"] = issued.isoformat()
        return data, fetched
    monkeypatch.setattr(context, "_json", fetch)
    assert context.weather_context(32, -117)["reason"] == "STALE_OR_FUTURE_FORECAST"


def test_untrusted_forecast_url_never_followed(monkeypatch):
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        return {"properties": {"forecastHourly": "https://example.com/private"}}, NOW.isoformat()
    monkeypatch.setattr(context, "_json", fetch)
    assert context.weather_context(32, -117)["reason"] == "NO_SUPPORTED_NWS_GRID"
    assert len(calls) == 1


def test_open_meteo_requires_explicit_noncommercial_opt_in(monkeypatch):
    monkeypatch.delenv("OPEN_METEO_ACCESS", raising=False)
    monkeypatch.setattr(context, "_json", lambda *a, **k: pytest.fail("must not fetch"))
    assert context.weather_context(51.5, -0.1, provider="open_meteo")["reason"] == "NONCOMMERCIAL_USE_OPT_IN_REQUIRED"


def test_open_meteo_has_no_invented_issued_at(monkeypatch):
    monkeypatch.setenv("OPEN_METEO_ACCESS", "noncommercial")
    def fetch(*a, **k):
        return {"utc_offset_seconds": 0,
                "hourly_units": {"temperature_2m": "°C", "wind_speed_10m": "km/h", "precipitation_probability": "%"},
                "hourly": {"time": ["2026-10-03T18:00"], "temperature_2m": [17], "wind_speed_10m": [12], "precipitation_probability": [30]}}, NOW.isoformat()
    monkeypatch.setattr(context, "_json", fetch)
    row = context.weather_context(51.5, -0.1, provider="open_meteo")
    assert row["available"] and row["provider_issued_at"] is None
    assert row["historical_training_eligible"] is False


def test_cache_preserves_original_retrieval_timestamp(monkeypatch):
    calls = []
    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"ok": True}
    def get(*a, **k):
        calls.append(a)
        return Response()
    monkeypatch.setattr(context.requests, "get", get)
    first = context._json("https://api.weather.gov/points/32,-117")
    monkeypatch.setattr(context, "utc_now", lambda: NOW+timedelta(minutes=1))
    second = context._json("https://api.weather.gov/points/32,-117")
    assert first == second and len(calls) == 1


def test_upstream_failure_has_no_raw_url_or_secret(monkeypatch):
    def fail(*a, **k):
        raise RuntimeError("https://provider.invalid?apikey=do-not-expose")
    monkeypatch.setattr(context, "_json", fail)
    result = context.weather_context(32, -117)
    assert result["reason"] == "UPSTREAM_UNAVAILABLE"
    assert "do-not-expose" not in str(result)


def test_indoor_and_unknown_venues_never_fetch_weather(monkeypatch):
    monkeypatch.setattr(context, "_json", lambda *a, **k: pytest.fail("must not fetch"))
    assert not context.game_weather_context({"sport": "NBA"})["available"]
    assert not context.game_weather_context({"sport": "MLB", "venue": {"outdoor": False}})["available"]
    assert not context.game_weather_context({"sport": "MLB", "venue": {"outdoor": True}})["available"]


def test_news_excludes_future_old_unsafe_and_duplicate_rows(monkeypatch):
    def article(title, dt, url="https://www.espn.com/nfl/story/1"):
        return {"headline": title, "published": dt.isoformat(), "links": {"web": {"href": url}}}
    data = {"articles": [article("Current", NOW), article("Duplicate", NOW),
                         article("Future", NOW+timedelta(hours=1)),
                         article("Old", NOW-timedelta(days=8)),
                         article("Unsafe", NOW, "javascript:alert(1)")]}
    monkeypatch.setattr(context, "_json", lambda *a, **k: (data, NOW.isoformat()))
    result = context.sports_news("NFL")
    assert [r["title"] for r in result["articles"]] == ["Current"]
    assert result["used_in_prediction"] is False


def test_api_validation_and_inventory(monkeypatch):
    client = TestClient(runtime.app)
    assert client.get("/v1/context/weather?lat=100&lon=0").status_code == 422
    assert client.get("/v1/context/weather?lat=0&lon=0&at=2026-10-03T19:00:00").status_code == 400
    assert client.get("/v1/context/weather?lat=0&lon=0&provider=unknown").status_code == 400
    assert client.get("/v1/context/news/SOCCER").status_code == 404
    assert client.get("/v1/context/news/NFL?limit=1000").status_code == 422
    monkeypatch.delenv("OPEN_METEO_ACCESS", raising=False)
    result = client.get("/v1/data/providers").json()
    assert result["runtime"]["weather_default"] == "NWS"
    assert result["runtime"]["open_meteo_noncommercial_enabled"] is False
    assert result["governance"]["model_promotion_changed"] is False


def test_mlb_venue_coordinates_are_from_provider(monkeypatch):
    raw = {"dates": [{"games": [{"gamePk": 1, "gameDate": "2026-10-03T19:00:00Z",
        "teams": {"home": {"team": {"name": "Home"}}, "away": {"team": {"name": "Away"}}},
        "venue": {"name": "Venue", "location": {"defaultCoordinates": {"latitude": 32, "longitude": -117}}, "fieldInfo": {"roofType": "Open"}}}]}]}
    monkeypatch.setattr(runtime, "_json", lambda *a, **k: raw)
    venue = runtime._mlb_schedule("2026-10-03")[0]["venue"]
    assert venue["latitude"] == 32 and venue["outdoor"] is True

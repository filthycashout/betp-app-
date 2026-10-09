from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app.py"
REQ = ROOT / "backend" / "requirements.txt"
DOCKER = ROOT / "backend" / "Dockerfile"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"{label}: expected anchor not found")
    return text.replace(old, new, 1)


def patch_app() -> None:
    text = APP.read_text(encoding="utf-8")
    import_anchor = '''from odds_api_net import (
    configured as odds_api_net_configured,
    events_for_date as odds_api_net_events_for_date,
    status as odds_api_net_status,
)
'''
    import_new = import_anchor + '''from free_odds_gateway import (
    game_events as free_odds_game_events,
    prop_event as free_odds_prop_event,
    status as free_odds_gateway_status,
)
'''
    text = replace_once(text, import_anchor, import_new, "FreeOddsGateway import")
    text = text.replace('APP_VERSION = "1.6.8"', 'APP_VERSION = "1.6.9"', 1)

    odds_pattern = re.compile(r"def _odds\(sport: str, d: date_cls\) -> list\[dict\]:\n.*?(?=\ndef _norm\()", re.S)
    odds_replacement = '''def _odds(sport: str, d: date_cls) -> list[dict]:
    # PhilthySports FreeOddsGateway order:
    # ESPN keyless primary -> oddswrap verification -> free fallbacks -> SX signal.
    try:
        espn = _timed(
            f"{sport}.odds.espn_keyless_primary",
            lambda: _espn_market_events(sport, d),
        )
    except Exception:
        espn = []
    try:
        gateway = _timed(
            f"{sport}.odds.free_gateway",
            lambda: free_odds_game_events(sport, d, espn),
        )
    except Exception:
        gateway = list(espn)

    # Legacy credentialed providers remain fail-available fallbacks. They are not
    # allowed to outrank a validated composite FreeOddsGateway event.
    fallback: list[dict[str, Any]] = []
    key = os.getenv("ODDS_API_KEY", "").strip()
    rotation = os.getenv("CREDENTIAL_ROTATION_CONFIRMED", "").strip().lower() == "true"
    if key and rotation:
        try:
            start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
            end = start + timedelta(hours=36)
            params = {
                "apiKey": key, "regions": "us", "markets": "h2h,spreads,totals",
                "oddsFormat": "american", "dateFormat": "iso",
                "commenceTimeFrom": start.isoformat().replace("+00:00", "Z"),
                "commenceTimeTo": end.isoformat().replace("+00:00", "Z"),
            }
            rows = _timed(
                f"{sport}.odds.the_odds_api_fallback",
                lambda: _json(
                    f"https://api.the-odds-api.com/v4/sports/{SPORT_KEYS[sport]}/odds/",
                    params=params, timeout=12,
                ),
            )
            if isinstance(rows, list):
                fallback.extend({**row, "market_source": "THE_ODDS_API_V4_FALLBACK", "data_quality": "PREGAME_CREDENTIALLED"} for row in rows if isinstance(row, dict))
        except Exception:
            pass
    if odds_api_net_configured():
        try:
            fallback.extend(_timed(
                f"{sport}.odds.odds_api_net_fallback",
                lambda: odds_api_net_events_for_date(sport, d),
            ))
        except Exception:
            pass
    return [*gateway, *fallback]
'''
    text, count = odds_pattern.subn(odds_replacement, text, count=1)
    if count != 1:
        raise RuntimeError("_odds router patch failed")

    rank_pattern = re.compile(r"def _market_source_rank\(event: dict\[str, Any\]\) -> int:\n.*?(?=\n\ndef _match_odds)", re.S)
    rank_replacement = '''def _market_source_rank(event: dict[str, Any]) -> int:
    source = str(event.get("market_source") or "").upper()
    if "PHILTHY_FREE_ODDS_GATEWAY" in source:
        return 100
    if "ESPN" in source:
        return 90
    if "ODDSWRAP" in source:
        return 80
    if "PROPLINE" in source:
        return 70
    if "ODDS_API_IO" in source:
        return 60
    if "THE_ODDS" in source:
        return 40
    if "ODDS_API_NET" in source:
        return 35
    return 0
'''
    text, count = rank_pattern.subn(rank_replacement, text, count=1)
    if count != 1:
        raise RuntimeError("market source rank patch failed")

    props_pattern = re.compile(r"def _props_for_game\(\n.*?(?=\ndef _matches_search_query)", re.S)
    props_replacement = '''def _props_for_game(
    sport: str,
    game: dict[str, Any],
    matched_odds_event: dict[str, Any] | None = None,
    requested: str | None = None,
) -> dict[str, Any]:
    markets = _requested_prop_markets(sport, requested)
    try:
        gateway_event = _timed(
            f"{sport}.props.free_gateway",
            lambda: free_odds_prop_event(sport, game, markets),
        )
    except Exception:
        gateway_event = None
    if gateway_event is not None:
        parsed = parse_props(gateway_event, sport, markets)
        if parsed.get("props"):
            return {
                "sport": sport,
                "event_id": game.get("event_id"),
                "provider_event_id": gateway_event.get("id"),
                "provider": str(gateway_event.get("market_source") or "PhilthySports FreeOddsGateway"),
                "credential_required": False,
                "configured_markets": PROP_MARKETS[sport],
                "alternate_markets": PROP_ALTERNATE_MARKETS[sport],
                "default_live_markets": PROP_DEFAULT_LIVE_MARKETS[sport],
                "requested_markets": markets,
                **parsed,
            }

    if _primary_prop_provider_ready() and matched_odds_event is not None:
        provider_event_id = matched_odds_event.get("id")
        if provider_event_id:
            try:
                payload = _prop_payload(sport, str(provider_event_id), requested)
                payload["provider"] = "The Odds API v4 fallback"
                payload["credential_required"] = True
                return payload
            except Exception:
                pass
    try:
        return _keyless_prop_payload_for_game(sport, game, requested)
    except ValueError:
        raise
    except Exception as exc:
        return {
            "sport": sport,
            "event_id": game.get("event_id"),
            "provider": "public keyless sportsbook fallback",
            "credential_required": False,
            "configured_markets": PROP_MARKETS[sport],
            "alternate_markets": PROP_ALTERNATE_MARKETS[sport],
            "default_live_markets": PROP_DEFAULT_LIVE_MARKETS[sport],
            "requested_markets": markets,
            "props": [],
            "status": "FREE_ODDS_GATEWAY_UNAVAILABLE",
            "message": f"No validated player-prop board was available ({type(exc).__name__}). No prop was fabricated.",
        }

'''
    text, count = props_pattern.subn(props_replacement, text, count=1)
    if count != 1:
        raise RuntimeError("props gateway patch failed")

    status_anchor = '        "odds_api_net": odds_api_net_status(),\n'
    status_new = '        "free_odds_gateway": free_odds_gateway_status(),\n' + status_anchor
    if status_anchor in text:
        text = replace_once(text, status_anchor, status_new, "provider status")

    APP.write_text(text, encoding="utf-8")


def patch_requirements() -> None:
    text = REQ.read_text(encoding="utf-8")
    dep = "oddswrap @ https://github.com/sjhouston23/oddswrap/archive/b4b8b65bc4be45d855824ca70e3230f3f4d7ca9f.zip"
    if dep not in text:
        text = text.rstrip() + "\n" + dep + "\n"
    REQ.write_text(text, encoding="utf-8")


def patch_docker() -> None:
    text = DOCKER.read_text(encoding="utf-8")
    old = "RUN python -m py_compile app.py selftest.py evidence/runtime.py odds_api_net.py"
    new = "RUN python -m py_compile app.py selftest.py evidence/runtime.py evidence/market_snapshot_store.py odds_api_net.py free_odds_gateway.py outcome_validation.py training/free_odds_evidence.py"
    text = replace_once(text, old, new, "Docker compile contract")
    DOCKER.write_text(text, encoding="utf-8")


def main() -> None:
    current = APP.read_text(encoding="utf-8")
    if 'APP_VERSION = "1.6.10"' in current and 'market_snapshot_evidence' in current:
        print("FreeOddsGateway 1.6.10 is already integrated; legacy mutating patch skipped")
        return
    patch_app()
    patch_requirements()
    patch_docker()
    print("PhilthySports FreeOddsGateway patch applied")


if __name__ == "__main__":
    main()

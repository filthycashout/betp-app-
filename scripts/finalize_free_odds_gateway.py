from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "backend" / "free_odds_gateway.py"
SNAPSHOT = ROOT / "backend" / "evidence" / "market_snapshot_store.py"
EVIDENCE_RUNTIME = ROOT / "backend" / "evidence" / "runtime.py"
EVIDENCE_PIPELINE = ROOT / "backend" / "training" / "evidence_pipeline.py"
PRODUCTION_GUARD = ROOT / "backend" / "ops" / "production_guard.py"
SIGN_PROMOTED = ROOT / "backend" / "training" / "sign_promoted.py"
CI_SECURITY = ROOT / "backend" / "ci_security.py"
APP = ROOT / "backend" / "app.py"
GATEWAY_TESTS = ROOT / "backend" / "tests" / "test_free_odds_gateway.py"
VALIDATION_TESTS = ROOT / "backend" / "tests" / "test_validation.py"
DOCS = ROOT / "docs" / "FREE_ODDS_GATEWAY.md"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"{label}: expected anchor not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_regex(path: Path, pattern: str, replacement: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, lambda _: replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match in {path}, got {count}")
    path.write_text(updated, encoding="utf-8")


def patch_snapshot_store() -> None:
    replace_once(
        SNAPSHOT,
        "_DB_READY = False\n_DEFAULT_ROOT",
        "_DB_READY = False\n_DB_ERROR_TYPE: str | None = None\n_DEFAULT_ROOT",
        "snapshot db error state",
    )
    replace_regex(
        SNAPSHOT,
        r"def _ensure_database\(\) -> bool:.*?(?=\n\ndef record_market_snapshot)",
        '''def _mark_db_failed(exc: Exception) -> None:
    global _DB_READY, _DB_ERROR_TYPE
    _DB_READY = False
    _DB_ERROR_TYPE = type(exc).__name__


def _ensure_database() -> bool:
    global _DB_READY, _DB_ERROR_TYPE
    if _DB_READY:
        return True
    url = _database_url()
    if not url:
        _DB_ERROR_TYPE = "DATABASE_URL_MISSING"
        return False
    if psycopg is None or Jsonb is None:
        _DB_ERROR_TYPE = "PSYCOPG_UNAVAILABLE"
        return False
    with _DB_LOCK:
        if _DB_READY:
            return True
        try:
            with psycopg.connect(url, autocommit=True, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS philthy_market_snapshots (
                            record_sha256 TEXT PRIMARY KEY,
                            event_date DATE NOT NULL,
                            sport TEXT NOT NULL,
                            event_id TEXT,
                            fetched_at TIMESTAMPTZ NOT NULL,
                            event_time TIMESTAMPTZ NOT NULL,
                            payload JSONB NOT NULL,
                            created_at TIMESTAMPTZ DEFAULT NOW()
                        )
                        """
                    )
                    cur.execute(
                        "CREATE INDEX IF NOT EXISTS philthy_market_snapshots_lookup_idx "
                        "ON philthy_market_snapshots (sport, event_date, fetched_at DESC)"
                    )
            _DB_READY = True
            _DB_ERROR_TYPE = None
            return True
        except Exception as exc:
            _mark_db_failed(exc)
            return False


def storage_status() -> dict[str, Any]:
    durable = _ensure_database()
    return {
        "mode": "postgres" if durable else "server_runtime_fallback",
        "durable": durable,
        "database_configured": bool(_database_url()),
        "database_error_type": _DB_ERROR_TYPE,
    }
''',
        "snapshot storage status",
    )
    replace_once(
        SNAPSHOT,
        '''            return record
        except Exception:
            pass

    path = SNAPSHOT_ROOT''',
        '''            return record
        except Exception as exc:
            _mark_db_failed(exc)

    path = SNAPSHOT_ROOT''',
        "snapshot insert failure state",
    )


def patch_gateway() -> None:
    replace_once(
        GATEWAY,
        "from evidence.market_snapshot_store import record_market_snapshot",
        "from evidence.market_snapshot_store import record_market_snapshot, storage_status as market_snapshot_storage_status",
        "snapshot storage import",
    )
    replace_once(
        GATEWAY,
        '''def _align_bookmaker(book: dict[str, Any], source: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:''',
        '''_REQUIRED_GAME_MARKETS = {"h2h", "spreads", "totals"}


def _market_fingerprint(market: dict[str, Any]) -> tuple[Any, ...]:
    outcomes = []
    for outcome in market.get("outcomes") or []:
        if not isinstance(outcome, dict):
            continue
        outcomes.append((
            _norm(outcome.get("name")),
            outcome.get("point"),
            outcome.get("description"),
        ))
    return (str(market.get("key") or "").lower(), tuple(outcomes))


def _event_market_keys(event: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for book in event.get("bookmakers") or []:
        if not isinstance(book, dict):
            continue
        for market in book.get("markets") or []:
            if isinstance(market, dict) and market.get("key"):
                keys.add(str(market["key"]).lower())
    return keys


def _primary_market_coverage_complete(
    primary: list[dict[str, Any]], candidates: list[dict[str, Any]]
) -> bool:
    if not primary:
        return bool(candidates)
    for base in primary:
        covered: set[str] = set()
        for candidate in candidates:
            if _same_event(base, candidate):
                covered.update(_event_market_keys(candidate))
        if not _REQUIRED_GAME_MARKETS.issubset(covered):
            return False
    return True


def _align_bookmaker(book: dict[str, Any], source: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:''',
        "market coverage helpers",
    )
    replace_regex(
        GATEWAY,
        r"            existing_keys = \{.*?                existing_keys.add\(key\)\n",
        '''            book_index = {
                str(book.get("key") or book.get("title") or "").lower(): book
                for book in target.get("bookmakers") or []
                if isinstance(book, dict)
            }
            for book in event.get("bookmakers") or []:
                if not isinstance(book, dict):
                    continue
                aligned = _align_bookmaker(book, event, target)
                key = str(aligned.get("key") or aligned.get("title") or "").lower()
                if not key:
                    continue
                existing = book_index.get(key)
                if existing is None:
                    target.setdefault("bookmakers", []).append(aligned)
                    book_index[key] = aligned
                    continue
                fingerprints = {
                    _market_fingerprint(market)
                    for market in existing.get("markets") or []
                    if isinstance(market, dict)
                }
                for market in aligned.get("markets") or []:
                    if not isinstance(market, dict):
                        continue
                    fingerprint = _market_fingerprint(market)
                    if fingerprint not in fingerprints:
                        existing.setdefault("markets", []).append(market)
                        fingerprints.add(fingerprint)
''',
        "merge same-book missing markets",
    )
    replace_regex(
        GATEWAY,
        r"    def missing_primary\(candidates: list\[dict\[str, Any\]\]\) -> bool:.*?    coverage = list\(verification\)\n    if missing_primary\(coverage\):",
        '''    coverage = list(verification)
    if not _primary_market_coverage_complete(primary, coverage):''',
        "market-level fallback coverage",
    )
    replace_once(
        GATEWAY,
        "    if missing_primary(coverage):\n        odds_io = _odds_io_game_events(sport, target_date)",
        "    if not _primary_market_coverage_complete(primary, coverage):\n        odds_io = _odds_io_game_events(sport, target_date)",
        "odds-api.io market-level fallback",
    )
    replace_once(
        GATEWAY,
        '''        snapshot = record_market_snapshot(event, fetched_at=now)
        event["snapshot_evidence"] = (
            {
                "status": "RECORDED",
                "record_sha256": snapshot["record_sha256"],
                "fetched_at_utc": snapshot["fetched_at_utc"],
                "event_time_utc": snapshot["event_time_utc"],
                "chronology_valid": True,
                "sport": snapshot.get("sport") or sport,
            }
            if snapshot else
            {"status": "NOT_RECORDED", "chronology_valid": False, "sport": sport}
        )''',
        '''        snapshot = record_market_snapshot(event, fetched_at=now)
        storage = market_snapshot_storage_status()
        event["snapshot_evidence"] = (
            {
                "status": "RECORDED" if storage.get("durable") is True else "RECORDED_NON_DURABLE",
                "record_sha256": snapshot["record_sha256"],
                "fetched_at_utc": snapshot["fetched_at_utc"],
                "event_time_utc": snapshot["event_time_utc"],
                "chronology_valid": True,
                "sport": snapshot.get("sport") or sport,
                "durable": storage.get("durable") is True,
                "storage_mode": storage.get("mode"),
            }
            if snapshot else
            {
                "status": "NOT_RECORDED",
                "chronology_valid": False,
                "sport": sport,
                "durable": False,
                "storage_mode": storage.get("mode"),
            }
        )''',
        "durable snapshot evidence",
    )
    replace_once(
        GATEWAY,
        '''def prop_event(sport: str, game: dict[str, Any], requested_markets: list[str]) -> dict[str, Any] | None:
    event = _oddswrap_prop_event(sport, game, requested_markets)
    if event is not None:
        return event
    event = _propline_prop_event(sport, game, requested_markets)
    if event is not None:
        return event
    event = _odds_io_prop_event(sport, game, requested_markets)
    if event is not None:
        return event
    return None
''',
        '''def _clone_prop_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        **event,
        "bookmakers": [
            {
                **book,
                "markets": [dict(market) for market in book.get("markets") or [] if isinstance(market, dict)],
            }
            for book in event.get("bookmakers") or []
            if isinstance(book, dict)
        ],
    }


def _merge_prop_event(base: dict[str, Any] | None, addition: dict[str, Any]) -> dict[str, Any]:
    if base is None:
        return _clone_prop_event(addition)
    book_index = {
        str(book.get("key") or book.get("title") or "").lower(): book
        for book in base.get("bookmakers") or []
        if isinstance(book, dict)
    }
    for book in addition.get("bookmakers") or []:
        if not isinstance(book, dict):
            continue
        key = str(book.get("key") or book.get("title") or "").lower()
        if not key:
            continue
        existing = book_index.get(key)
        if existing is None:
            cloned = {**book, "markets": [dict(m) for m in book.get("markets") or [] if isinstance(m, dict)]}
            base.setdefault("bookmakers", []).append(cloned)
            book_index[key] = cloned
            continue
        fingerprints = {
            _market_fingerprint(market)
            for market in existing.get("markets") or []
            if isinstance(market, dict)
        }
        for market in book.get("markets") or []:
            if not isinstance(market, dict):
                continue
            fingerprint = _market_fingerprint(market)
            if fingerprint not in fingerprints:
                existing.setdefault("markets", []).append(dict(market))
                fingerprints.add(fingerprint)
    return base


def prop_event(sport: str, game: dict[str, Any], requested_markets: list[str]) -> dict[str, Any] | None:
    requested = list(dict.fromkeys(requested_markets))
    composite: dict[str, Any] | None = None
    sources_seen: list[str] = []

    oddswrap = _oddswrap_prop_event(sport, game, requested)
    if oddswrap is not None:
        composite = _merge_prop_event(composite, oddswrap)
        sources_seen.append("ODDSWRAP")

    covered = _event_market_keys(composite or {})
    missing = [market for market in requested if market not in covered]
    if missing:
        propline = _propline_prop_event(sport, game, missing)
        if propline is not None:
            composite = _merge_prop_event(composite, propline)
            sources_seen.append("PROPLINE")

    covered = _event_market_keys(composite or {})
    missing = [market for market in requested if market not in covered]
    if missing:
        odds_io = _odds_io_prop_event(sport, game, missing)
        if odds_io is not None:
            composite = _merge_prop_event(composite, odds_io)
            sources_seen.append("ODDS_API_IO")

    if composite is None:
        return None
    covered = _event_market_keys(composite)
    composite["market_source"] = "PHILTHY_FREE_ODDS_GATEWAY_PROPS"
    composite["gateway"] = {
        "sources_seen": sources_seen,
        "requested_markets": requested,
        "covered_markets": sorted(covered.intersection(requested)),
        "complete": all(market in covered for market in requested),
    }
    return composite
''',
        "prop coverage merge",
    )
    replace_once(
        GATEWAY,
        '''        "snapshot_gate": "fetched_at < event_time",
        "event_match_tolerance_seconds": 1800,''',
        '''        "snapshot_gate": "fetched_at < event_time",
        "snapshot_storage": market_snapshot_storage_status(),
        "event_match_tolerance_seconds": 1800,''',
        "gateway snapshot storage status",
    )


def patch_evidence_pipeline() -> None:
    replace_once(
        EVIDENCE_PIPELINE,
        '''            "schedule_source": game.get("schedule_source"),
            "injury_home_count": (''',
        '''            "schedule_source": game.get("schedule_source"),
            "market_source": game.get("market_source"),
            "market_snapshot_sha256": (game.get("market_snapshot_evidence") or {}).get("record_sha256"),
            "market_snapshot_chronology_valid": (game.get("market_snapshot_evidence") or {}).get("chronology_valid"),
            "market_snapshot_durable": (game.get("market_snapshot_evidence") or {}).get("durable"),
            "injury_home_count": (''',
        "capture snapshot provenance",
    )
    replace_once(
        EVIDENCE_PIPELINE,
        '''        "chronology_rule": "as_of < event_time",
        "secrets_embedded": False,''',
        '''        "chronology_rule": "as_of < event_time",
        "gateway_snapshot_rule": "FreeOddsGateway rows require durable chronology-valid snapshot SHA-256 before canonical training inclusion",
        "secrets_embedded": False,''',
        "capture manifest snapshot rule",
    )
    replace_once(
        EVIDENCE_PIPELINE,
        '''        key = (row["sport"], row["event_id"])
        existing = latest.get(key)''',
        '''        if row.get("market_source") == "PHILTHY_FREE_ODDS_GATEWAY":
            digest = str(row.get("market_snapshot_sha256") or "").lower()
            digest_valid = len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest)
            if (
                not digest_valid
                or row.get("market_snapshot_chronology_valid") is not True
                or row.get("market_snapshot_durable") is not True
            ):
                continue
        key = (row["sport"], row["event_id"])
        existing = latest.get(key)''',
        "canonical snapshot gate",
    )
    replace_once(
        EVIDENCE_PIPELINE,
        '''        "consensus_total",
    ]''',
        '''        "consensus_total",
        "market_source",
        "market_snapshot_sha256",
        "market_snapshot_chronology_valid",
        "market_snapshot_durable",
    ]''',
        "canonical provenance columns",
    )
    replace_once(
        EVIDENCE_PIPELINE,
        '''                "consensus_total": row.get("consensus_total"),
            })''',
        '''                "consensus_total": row.get("consensus_total"),
                "market_source": row.get("market_source"),
                "market_snapshot_sha256": row.get("market_snapshot_sha256"),
                "market_snapshot_chronology_valid": row.get("market_snapshot_chronology_valid"),
                "market_snapshot_durable": row.get("market_snapshot_durable"),
            })''',
        "canonical provenance values",
    )
    replace_once(
        EVIDENCE_PIPELINE,
        '''        schema = {
            "schema_version": 1,
            "columns": columns,''',
        '''        schema = {
            "schema_version": 2,
            "columns": columns,
            "provenance_fields": [
                "market_source",
                "market_snapshot_sha256",
                "market_snapshot_chronology_valid",
                "market_snapshot_durable",
            ],''',
        "canonical schema provenance",
    )
    replace_once(
        EVIDENCE_PIPELINE,
        '''    capture_p.add_argument("--base-url", default="https://philthysports-powerhouse-v8.onrender.com")''',
        '''    capture_p.add_argument("--base-url", required=True)''',
        "remove obsolete evidence default",
    )


def patch_evidence_runtime() -> None:
    text = EVIDENCE_RUNTIME.read_text(encoding="utf-8")
    text = text.replace('"render_postgres"', '"postgres"')
    EVIDENCE_RUNTIME.write_text(text, encoding="utf-8")


def patch_production_guard() -> None:
    replace_once(
        PRODUCTION_GUARD,
        '''        gateway = providers.get("free_odds_gateway") or {}
        checks = {''',
        '''        gateway = providers.get("free_odds_gateway") or {}
        snapshot_storage = gateway.get("snapshot_storage") or {}
        checks = {''',
        "production guard snapshot storage",
    )
    replace_once(
        PRODUCTION_GUARD,
        '''            "free_odds_gateway_snapshot_gate": gateway.get("snapshot_gate") == "fetched_at < event_time",
            "free_odds_gateway_props_chain": gateway.get("player_props_order") == ["ODDSWRAP", "PROPLINE", "ODDS_API_IO"],''',
        '''            "free_odds_gateway_snapshot_gate": gateway.get("snapshot_gate") == "fetched_at < event_time",
            "free_odds_gateway_snapshot_database_configured": snapshot_storage.get("database_configured") is True,
            "free_odds_gateway_snapshot_storage_durable": snapshot_storage.get("durable") is True,
            "free_odds_gateway_snapshot_storage_postgres": snapshot_storage.get("mode") in {"postgres", "render_postgres"},
            "free_odds_gateway_props_chain": gateway.get("player_props_order") == ["ODDSWRAP", "PROPLINE", "ODDS_API_IO"],''',
        "production snapshot durability gates",
    )
    replace_once(
        PRODUCTION_GUARD,
        '''            "evidence_render_postgres": storage.get("mode") == "render_postgres",''',
        '''            "evidence_postgres": storage.get("mode") in {"postgres", "render_postgres"},''',
        "provider-neutral evidence storage gate",
    )
    replace_once(
        PRODUCTION_GUARD,
        '''            free_odds_gateway=gateway,
            evidence_storage={''',
        '''            free_odds_gateway=gateway,
            market_snapshot_storage=snapshot_storage,
            evidence_storage={''',
        "production guard snapshot report",
    )


def patch_signing() -> None:
    replace_once(
        SIGN_PROMOTED,
        '''    parser.add_argument(
        "--signer-url",
        default="https://philthysports-powerhouse-v8.onrender.com/v1/ci/sign-model-artifact",
    )
    args = parser.parse_args()
''',
        '''    parser.add_argument(
        "--signer-url",
        default=os.getenv("PHILTHY_SIGNER_URL", "").strip(),
    )
    args = parser.parse_args()
    if not args.signer_url:
        raise SystemExit("Signer URL is not configured; set PHILTHY_SIGNER_URL or pass --signer-url")
    if not str(args.signer_url).startswith("https://"):
        raise SystemExit("Signer URL must use HTTPS")
''',
        "promotion signer fail-closed",
    )
    replace_once(
        CI_SECURITY,
        'DEFAULT_ANDROID_SIGNING_FALLBACK = "https://philthysports-powerhouse-v8.onrender.com"',
        'DEFAULT_ANDROID_SIGNING_FALLBACK = ""',
        "remove obsolete Android signer fallback",
    )
    replace_once(
        CI_SECURITY,
        '''    current_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip().lower()''',
        '''    current_host = (
        os.getenv("PHILTHY_PUBLIC_HOST", "").strip()
        or os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
    ).lower()''',
        "provider-neutral current host",
    )


def patch_app() -> None:
    replace_once(APP, 'APP_VERSION = "1.6.10"', 'APP_VERSION = "1.6.11"', "backend version")
    replace_once(
        APP,
        '''        "provider": (
            "The Odds API v4"
            if os.getenv("ODDS_API_KEY", "").strip()
            and os.getenv("CREDENTIAL_ROTATION_CONFIRMED", "").strip().lower() == "true"
            else "ESPN scoreboard odds"
        ),
        "events": events,''',
        '''        "provider": "PhilthySports FreeOddsGateway",
        "provider_status": free_odds_gateway_status(),
        "events": events,''',
        "legacy odds provider identity",
    )


def patch_tests() -> None:
    text = GATEWAY_TESTS.read_text(encoding="utf-8")
    marker = "def test_game_fallback_fills_missing_market_coverage"
    if marker not in text:
        text += '''


def _add_market(event, key):
    row = {**event, "bookmakers": [{**event["bookmakers"][0], "markets": list(event["bookmakers"][0]["markets"])}]}
    if key == "spreads":
        row["bookmakers"][0]["markets"].append({
            "key": "spreads",
            "outcomes": [
                {"name": row["home_team"], "point": -2.5, "price": -110},
                {"name": row["away_team"], "point": 2.5, "price": -110},
            ],
        })
    elif key == "totals":
        row["bookmakers"][0]["markets"].append({
            "key": "totals",
            "outcomes": [
                {"name": "Over", "point": 44.5, "price": -110},
                {"name": "Under", "point": 44.5, "price": -110},
            ],
        })
    return row


def test_game_fallback_fills_missing_market_coverage(monkeypatch):
    when = datetime.now(timezone.utc) + timedelta(hours=12)
    espn = _event("ESPN_SCOREBOARD_ODDS", "espn", when)
    wrap = _event("ODDSWRAP", "draftkings", when)
    fallback = _add_market(_add_market(_event("PROPLINE", "draftkings", when), "spreads"), "totals")
    calls = []
    monkeypatch.setattr(gateway, "_oddswrap_game_events", lambda sport, day: [wrap])
    monkeypatch.setattr(gateway, "_propline_game_events", lambda sport, day: calls.append("propline") or [fallback])
    monkeypatch.setattr(gateway, "_odds_io_game_events", lambda sport, day: calls.append("odds_io") or [])
    monkeypatch.setattr(gateway, "_sx_market_snapshot", lambda sport: {"available": False, "markets": []})
    monkeypatch.setattr(gateway, "record_market_snapshot", lambda event, fetched_at=None: None)
    monkeypatch.setattr(gateway, "market_snapshot_storage_status", lambda: {"mode": "server_runtime_fallback", "durable": False, "database_configured": False})
    rows = gateway.game_events("NFL", when.astimezone(gateway.PACIFIC).date(), [espn])
    assert calls == ["propline"]
    draftkings = next(book for book in rows[0]["bookmakers"] if book["key"] == "draftkings")
    assert {market["key"] for market in draftkings["markets"]} == {"h2h", "spreads", "totals"}


def test_prop_fallback_merges_missing_requested_markets(monkeypatch):
    when = datetime.now(timezone.utc) + timedelta(hours=12)
    game = {"event_id": "1", "home": "Home", "away": "Away", "event_time": when.isoformat()}
    def prop_event(source, book, market):
        return {
            "id": "1", "home_team": "Home", "away_team": "Away", "commence_time": when.isoformat(),
            "market_source": source,
            "bookmakers": [{"key": book, "markets": [{"key": market, "outcomes": [
                {"name": "Over", "description": "Player", "point": 1.5, "price": -110},
                {"name": "Under", "description": "Player", "point": 1.5, "price": -110},
            ]}]}],
        }
    monkeypatch.setattr(gateway, "_oddswrap_prop_event", lambda sport, game, markets: prop_event("ODDSWRAP_PROPS", "draftkings", "player_pass_yds"))
    monkeypatch.setattr(gateway, "_propline_prop_event", lambda sport, game, markets: prop_event("PROPLINE_PROPS", "fanduel", "player_rush_yds"))
    monkeypatch.setattr(gateway, "_odds_io_prop_event", lambda sport, game, markets: None)
    row = gateway.prop_event("NFL", game, ["player_pass_yds", "player_rush_yds"])
    assert row is not None
    assert row["market_source"] == "PHILTHY_FREE_ODDS_GATEWAY_PROPS"
    assert row["gateway"]["complete"] is True
    assert row["gateway"]["sources_seen"] == ["ODDSWRAP", "PROPLINE"]


def test_snapshot_evidence_marks_runtime_fallback_non_durable(monkeypatch):
    when = datetime.now(timezone.utc) + timedelta(hours=12)
    espn = _event("ESPN_SCOREBOARD_ODDS", "espn", when)
    monkeypatch.setattr(gateway, "_oddswrap_game_events", lambda sport, day: [])
    monkeypatch.setattr(gateway, "_propline_game_events", lambda sport, day: [])
    monkeypatch.setattr(gateway, "_odds_io_game_events", lambda sport, day: [])
    monkeypatch.setattr(gateway, "_sx_market_snapshot", lambda sport: {"available": False, "markets": []})
    monkeypatch.setattr(gateway, "record_market_snapshot", lambda event, fetched_at=None: {
        "record_sha256": "c" * 64,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "event_time_utc": when.isoformat(),
        "sport": "NFL",
    })
    monkeypatch.setattr(gateway, "market_snapshot_storage_status", lambda: {
        "mode": "server_runtime_fallback", "durable": False, "database_configured": False,
    })
    row = gateway.game_events("NFL", when.astimezone(gateway.PACIFIC).date(), [espn])[0]
    assert row["snapshot_evidence"]["status"] == "RECORDED_NON_DURABLE"
    assert row["snapshot_evidence"]["durable"] is False
'''
        GATEWAY_TESTS.write_text(text, encoding="utf-8")

    text = VALIDATION_TESTS.read_text(encoding="utf-8")
    marker = "def test_capture_retains_gateway_snapshot_provenance"
    if marker not in text:
        text += '''


def test_capture_retains_gateway_snapshot_provenance(tmp_path, monkeypatch):
    event_time = datetime.now(timezone.utc) + timedelta(hours=6)
    payload = {
        "games": [{
            "sport": "NFL",
            "event_id": "snapshot-1",
            "event_time": event_time.isoformat(),
            "home": "Home",
            "away": "Away",
            "market": {"home_probability": 0.55, "home_spread": -2.5, "total": 44.5},
            "market_source": "PHILTHY_FREE_ODDS_GATEWAY",
            "market_snapshot_evidence": {
                "record_sha256": "d" * 64,
                "chronology_valid": True,
                "durable": True,
            },
        }]
    }
    monkeypatch.setattr(ep, "_json", lambda _: payload)
    ep.capture("https://example.invalid", tmp_path, days=1)
    path = next(tmp_path.glob("pregame_*.jsonl"))
    row = json.loads(path.read_text().splitlines()[0])
    assert row["market_snapshot_sha256"] == "d" * 64
    assert row["market_snapshot_chronology_valid"] is True
    assert row["market_snapshot_durable"] is True
'''
        VALIDATION_TESTS.write_text(text, encoding="utf-8")


def patch_docs() -> None:
    text = DOCS.read_text(encoding="utf-8")
    marker = "## Final evidence hardening — 1.6.11"
    if marker not in text:
        text += '''

## Final evidence hardening — 1.6.11

Game fallback is now market-coverage-aware rather than merely event-aware: missing h2h, spread, or total verification can be filled by later providers, including within an already-present sportsbook. Player-prop fallbacks merge missing requested markets across oddswrap, PropLine, and odds-api.io instead of stopping at the first partial provider.

FreeOddsGateway snapshots report whether their backing storage is durable. A local runtime JSONL write is explicitly marked `RECORDED_NON_DURABLE`; strict prediction-ledger and canonical-training evidence require a durable, chronology-valid SHA-256 snapshot for FreeOddsGateway rows.

Canonical training rows now retain the gateway market source and snapshot provenance. The active production/evidence workflows no longer hard-code a retired Render host; repository variables select the active HTTPS backend and fail closed when no current backend has been configured. Model and Android signing fallbacks likewise no longer silently target a retired host.
'''
        DOCS.write_text(text, encoding="utf-8")


def main() -> None:
    patch_snapshot_store()
    patch_gateway()
    patch_evidence_pipeline()
    patch_evidence_runtime()
    patch_production_guard()
    patch_signing()
    patch_app()
    patch_tests()
    patch_docs()
    print("Final FreeOddsGateway hardening applied")


if __name__ == "__main__":
    main()

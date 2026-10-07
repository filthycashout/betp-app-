from pathlib import Path


def replace_once(path: str, old: str, new: str) -> bool:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if new in text:
        return False
    if old not in text:
        raise RuntimeError(f"patch anchor not found in {path}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def patch_runtime() -> None:
    path = Path("backend/evidence/runtime.py")
    text = path.read_text(encoding="utf-8")
    start = text.index("def _ensure_database() -> bool:")
    end = text.index("\n\ndef storage_status()", start)
    replacement = '''def _ensure_database() -> bool:
    global _DB_READY, _DB_ERROR_TYPE
    if _DB_READY:
        return True
    url = _database_url()
    if not url:
        _DB_ERROR_TYPE = "DATABASE_URL_MISSING"
        _log_storage_state("server_runtime_fallback:DATABASE_URL_MISSING")
        return False
    if psycopg is None or Jsonb is None:
        _DB_ERROR_TYPE = "PSYCOPG_UNAVAILABLE"
        _log_storage_state("server_runtime_fallback:PSYCOPG_UNAVAILABLE")
        return False
    with _DB_LOCK:
        if _DB_READY:
            return True
        try:
            with psycopg.connect(url, autocommit=True, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    # CREATE TABLE IF NOT EXISTS does not migrate an older table.
                    # Create the current shape and then add columns introduced by
                    # later releases before an index or query can reference them.
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS philthy_evidence_signals (
                            signal_id TEXT PRIMARY KEY,
                            event_date DATE,
                            league TEXT,
                            payload JSONB,
                            created_at TIMESTAMPTZ DEFAULT NOW()
                        )
                        """
                    )
                    for ddl in (
                        "ALTER TABLE philthy_evidence_signals ADD COLUMN IF NOT EXISTS signal_id TEXT",
                        "ALTER TABLE philthy_evidence_signals ADD COLUMN IF NOT EXISTS event_date DATE",
                        "ALTER TABLE philthy_evidence_signals ADD COLUMN IF NOT EXISTS league TEXT",
                        "ALTER TABLE philthy_evidence_signals ADD COLUMN IF NOT EXISTS payload JSONB",
                        "ALTER TABLE philthy_evidence_signals ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
                    ):
                        cur.execute(ddl)
                    cur.execute(
                        "CREATE INDEX IF NOT EXISTS philthy_evidence_signals_date_idx "
                        "ON philthy_evidence_signals (event_date DESC, league, created_at DESC)"
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS philthy_evidence_manifests (
                            id BIGSERIAL PRIMARY KEY,
                            evidence_date DATE,
                            merkle_root TEXT,
                            payload JSONB,
                            created_at TIMESTAMPTZ DEFAULT NOW(),
                            UNIQUE (evidence_date, merkle_root)
                        )
                        """
                    )
                    for ddl in (
                        "ALTER TABLE philthy_evidence_manifests ADD COLUMN IF NOT EXISTS evidence_date DATE",
                        "ALTER TABLE philthy_evidence_manifests ADD COLUMN IF NOT EXISTS merkle_root TEXT",
                        "ALTER TABLE philthy_evidence_manifests ADD COLUMN IF NOT EXISTS payload JSONB",
                        "ALTER TABLE philthy_evidence_manifests ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
                    ):
                        cur.execute(ddl)
            _DB_READY = True
            _DB_ERROR_TYPE = None
            _log_storage_state("render_postgres")
            return True
        except Exception as exc:
            _mark_db_failed(exc)
            return False
'''.rstrip("\n")
    if text[start:end] != replacement:
        text = text[:start] + replacement + text[end:]
    # Compatibility with a legacy manifest table that predates the composite
    # unique constraint. Targetless DO NOTHING remains safe on current tables.
    text = text.replace(
        "ON CONFLICT (evidence_date, merkle_root) DO NOTHING",
        "ON CONFLICT DO NOTHING",
    )
    path.write_text(text, encoding="utf-8")


def patch_provider_canary() -> None:
    path = Path("backend/provider_canary.py")
    text = path.read_text(encoding="utf-8")
    if "import threading\n" not in text:
        text = text.replace("import os\n", "import os\nimport threading\nimport time\n", 1)
    if "def _live_provider_canaries_uncached(" not in text:
        marker = "def live_provider_canaries(*, historical_probe: bool = False) -> dict[str, Any]:"
        if marker not in text:
            raise RuntimeError("provider canary function anchor not found")
        text = text.replace(
            marker,
            "def _live_provider_canaries_uncached(*, historical_probe: bool = False) -> dict[str, Any]:",
            1,
        )
        text += '''

_CANARY_CACHE_LOCK = threading.Lock()
_CANARY_CACHE_VALUE: dict[str, Any] | None = None
_CANARY_CACHE_AT = 0.0
_CANARY_TTL_SECONDS = 300.0


def live_provider_canaries(*, historical_probe: bool = False) -> dict[str, Any]:
    """Return a fresh historical probe or a short-lived cached live canary."""
    global _CANARY_CACHE_VALUE, _CANARY_CACHE_AT
    if historical_probe:
        return _live_provider_canaries_uncached(historical_probe=True)
    now = time.monotonic()
    with _CANARY_CACHE_LOCK:
        if (
            _CANARY_CACHE_VALUE is not None
            and now - _CANARY_CACHE_AT < _CANARY_TTL_SECONDS
        ):
            return dict(_CANARY_CACHE_VALUE)
    value = _live_provider_canaries_uncached(historical_probe=False)
    with _CANARY_CACHE_LOCK:
        _CANARY_CACHE_VALUE = dict(value)
        _CANARY_CACHE_AT = time.monotonic()
    return dict(value)
'''
    path.write_text(text, encoding="utf-8")


def patch_app() -> None:
    path = Path("backend/app.py")
    text = path.read_text(encoding="utf-8")
    text = text.replace('APP_VERSION = "1.6.7"', 'APP_VERSION = "1.6.8"', 1)
    old = '''            "credential_live_odds_props": (
                "Canary pending" if rotation and odds_key else
                "Rotation confirmation pending" if odds_key else
                "Fresh credential pending"
            ),'''
    new = '''            "credential_live_odds_props": (
                "Passed" if rotation and odds_key and live_provider_canaries().get("credentialled_live_provider_verified") is True else
                "Canary pending" if rotation and odds_key else
                "Rotation confirmation pending" if odds_key else
                "Fresh credential pending"
            ),'''
    if new not in text:
        if old not in text:
            raise RuntimeError("app credential status anchor not found")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")


def patch_schedules() -> None:
    replace_once(
        ".github/workflows/live-provider-proof.yml",
        "  workflow_dispatch:\n",
        '  schedule:\n    - cron: "7 * * * *"\n  workflow_dispatch:\n',
    )
    replace_once(
        ".github/workflows/historical-access-probe.yml",
        "  workflow_dispatch:\n",
        '  schedule:\n    - cron: "17 9 * * *"\n  workflow_dispatch:\n',
    )


def main() -> None:
    patch_runtime()
    patch_provider_canary()
    patch_app()
    patch_schedules()


if __name__ == "__main__":
    main()

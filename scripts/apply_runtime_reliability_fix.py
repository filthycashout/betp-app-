from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"patch marker not found: {label}")
    return text.replace(old, new, 1)


# 1) Durable evidence storage: prefer Render Postgres when DATABASE_URL (or the
# project-specific alias) is configured, while retaining the existing JSONL
# fallback so the API stays available if the database is unavailable.
runtime = Path("backend/evidence/runtime.py")
s = runtime.read_text()
s = replace_once(
    s,
    "import json\nimport os\nimport threading\nimport time\nimport uuid\n",
    "import json\nimport os\nimport threading\nimport time\nimport uuid\n\ntry:\n    import psycopg\n    from psycopg.types.json import Jsonb\nexcept Exception:  # optional until backend requirements are installed\n    psycopg = None\n    Jsonb = None\n",
    "psycopg import",
)

storage_helpers = '''\n\n_DB_LOCK = threading.RLock()\n_DB_READY = False\n_DB_ERROR_TYPE: str | None = None\n_DB_LOG_STATE: str | None = None\n\n\ndef _database_url() -> str:\n    return (\n        os.getenv("PHILTHY_EVIDENCE_DATABASE_URL", "").strip()\n        or os.getenv("DATABASE_URL", "").strip()\n    )\n\n\ndef _log_storage_state(state: str) -> None:\n    global _DB_LOG_STATE\n    if state != _DB_LOG_STATE:\n        print(f"PHILTHY_EVIDENCE_STORAGE:{state}", flush=True)\n        _DB_LOG_STATE = state\n\n\ndef _mark_db_failed(exc: Exception) -> None:\n    global _DB_READY, _DB_ERROR_TYPE\n    _DB_READY = False\n    _DB_ERROR_TYPE = type(exc).__name__\n    _log_storage_state(f"server_runtime_fallback:{_DB_ERROR_TYPE}")\n\n\ndef _ensure_database() -> bool:\n    global _DB_READY, _DB_ERROR_TYPE\n    if _DB_READY:\n        return True\n    url = _database_url()\n    if not url:\n        _DB_ERROR_TYPE = "DATABASE_URL_MISSING"\n        _log_storage_state("server_runtime_fallback:DATABASE_URL_MISSING")\n        return False\n    if psycopg is None or Jsonb is None:\n        _DB_ERROR_TYPE = "PSYCOPG_UNAVAILABLE"\n        _log_storage_state("server_runtime_fallback:PSYCOPG_UNAVAILABLE")\n        return False\n    with _DB_LOCK:\n        if _DB_READY:\n            return True\n        try:\n            with psycopg.connect(url, autocommit=True, connect_timeout=5) as conn:\n                with conn.cursor() as cur:\n                    cur.execute(\n                        """\n                        CREATE TABLE IF NOT EXISTS philthy_evidence_signals (\n                            signal_id TEXT PRIMARY KEY,\n                            event_date DATE NOT NULL,\n                            league TEXT NOT NULL,\n                            payload JSONB NOT NULL,\n                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()\n                        )\n                        """\n                    )\n                    cur.execute(\n                        "CREATE INDEX IF NOT EXISTS philthy_evidence_signals_date_idx "\n                        "ON philthy_evidence_signals (event_date DESC, league, created_at DESC)"\n                    )\n                    cur.execute(\n                        """\n                        CREATE TABLE IF NOT EXISTS philthy_evidence_manifests (\n                            id BIGSERIAL PRIMARY KEY,\n                            evidence_date DATE NOT NULL,\n                            merkle_root TEXT,\n                            payload JSONB NOT NULL,\n                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),\n                            UNIQUE (evidence_date, merkle_root)\n                        )\n                        """\n                    )\n            _DB_READY = True\n            _DB_ERROR_TYPE = None\n            _log_storage_state("render_postgres")\n            return True\n        except Exception as exc:\n            _mark_db_failed(exc)\n            return False\n\n\ndef storage_status() -> dict[str, Any]:\n    durable = _ensure_database()\n    return {\n        "mode": "render_postgres" if durable else "server_runtime_fallback",\n        "durable": durable,\n        "database_configured": bool(_database_url()),\n        "database_error_type": _DB_ERROR_TYPE,\n    }\n'''
marker = 'SIGNAL_ROOT = Path(os.environ.get("PHILTHY_SIGNAL_LOG_DIR", str(_DEFAULT_ROOT)))\n'
s = replace_once(s, marker, marker + storage_helpers, "storage helpers")

old_persist = '''def _persist_batch(records: list[dict[str, Any]], snapshot: datetime) -> list[dict[str, Any]]:\n    if not records:\n        return []\n    anchored, manifest = anchor_batch(records)\n    day = snapshot.strftime("%Y-%m-%d")\n    with _LOCK:\n        append_jsonl(SIGNAL_ROOT / day / "signals.jsonl", anchored)\n        append_jsonl(SIGNAL_ROOT / day / "manifests.jsonl", [manifest])\n    return anchored\n'''
new_persist = '''def _persist_batch(records: list[dict[str, Any]], snapshot: datetime) -> list[dict[str, Any]]:\n    if not records:\n        return []\n    anchored, manifest = anchor_batch(records)\n    day = snapshot.strftime("%Y-%m-%d")\n\n    if _ensure_database():\n        try:\n            with psycopg.connect(_database_url(), autocommit=False, connect_timeout=5) as conn:\n                with conn.cursor() as cur:\n                    for row in anchored:\n                        event_date = str(row.get("event_time_utc") or day)[:10]\n                        cur.execute(\n                            """\n                            INSERT INTO philthy_evidence_signals\n                                (signal_id, event_date, league, payload)\n                            VALUES (%s, %s, %s, %s)\n                            ON CONFLICT (signal_id) DO NOTHING\n                            """,\n                            (row["signal_id"], event_date, row.get("league") or "", Jsonb(row)),\n                        )\n                    cur.execute(\n                        """\n                        INSERT INTO philthy_evidence_manifests\n                            (evidence_date, merkle_root, payload)\n                        VALUES (%s, %s, %s)\n                        ON CONFLICT (evidence_date, merkle_root) DO NOTHING\n                        """,\n                        (day, manifest.get("merkle_root"), Jsonb(manifest)),\n                    )\n                conn.commit()\n            return anchored\n        except Exception as exc:\n            _mark_db_failed(exc)\n\n    # Fail available: preserve the previous append-only runtime JSONL path. The\n    # status endpoint explicitly reports that this fallback is not durable.\n    with _LOCK:\n        append_jsonl(SIGNAL_ROOT / day / "signals.jsonl", anchored)\n        append_jsonl(SIGNAL_ROOT / day / "manifests.jsonl", [manifest])\n    return anchored\n'''
s = replace_once(s, old_persist, new_persist, "persist batch")

old_read = '''def _read_signals(*, sport: str | None = None, date: str | None = None, limit: int = 100) -> list[dict[str, Any]]:\n    wanted_sport = sport.upper() if sport else None\n    rows: list[dict[str, Any]] = []\n    for path in _iter_signal_files():\n        try:\n            lines = path.read_text(encoding="utf-8").splitlines()\n        except OSError:\n            continue\n        for line in reversed(lines):\n            if not line.strip():\n                continue\n            try:\n                row = json.loads(line)\n            except ValueError:\n                continue\n            if wanted_sport and row.get("league") != wanted_sport:\n                continue\n            if date and not str(row.get("event_time_utc") or "").startswith(date):\n                continue\n            rows.append(row)\n            if len(rows) >= limit:\n                return rows\n    return rows\n'''
new_read = '''def _read_signals(*, sport: str | None = None, date: str | None = None, limit: int = 100) -> list[dict[str, Any]]:\n    wanted_sport = sport.upper() if sport else None\n    if _ensure_database():\n        try:\n            clauses: list[str] = []\n            params: list[Any] = []\n            if wanted_sport:\n                clauses.append("league = %s")\n                params.append(wanted_sport)\n            if date:\n                clauses.append("event_date = %s")\n                params.append(date)\n            where = " WHERE " + " AND ".join(clauses) if clauses else ""\n            params.append(int(limit))\n            query = (\n                "SELECT payload FROM philthy_evidence_signals"\n                + where\n                + " ORDER BY created_at DESC LIMIT %s"\n            )\n            with psycopg.connect(_database_url(), autocommit=True, connect_timeout=5) as conn:\n                with conn.cursor() as cur:\n                    cur.execute(query, params)\n                    values = cur.fetchall()\n            return [value[0] if isinstance(value[0], dict) else json.loads(value[0]) for value in values]\n        except Exception as exc:\n            _mark_db_failed(exc)\n\n    rows: list[dict[str, Any]] = []\n    for path in _iter_signal_files():\n        try:\n            lines = path.read_text(encoding="utf-8").splitlines()\n        except OSError:\n            continue\n        for line in reversed(lines):\n            if not line.strip():\n                continue\n            try:\n                row = json.loads(line)\n            except ValueError:\n                continue\n            if wanted_sport and row.get("league") != wanted_sport:\n                continue\n            if date and not str(row.get("event_time_utc") or "").startswith(date):\n                continue\n            rows.append(row)\n            if len(rows) >= limit:\n                return rows\n    return rows\n'''
s = replace_once(s, old_read, new_read, "read signals")

old_list_return = '''    return {\n        "schema_version": "2",\n        "signals": rows,\n        "count": len(rows),\n        "append_only_runtime_log": True,\n        "storage_root": "server_runtime",\n    }\n'''
new_list_return = '''    storage = storage_status()\n    return {\n        "schema_version": "2",\n        "signals": rows,\n        "count": len(rows),\n        "append_only_runtime_log": True,\n        "storage_root": storage["mode"],\n        "durable_storage": storage["durable"],\n        "storage_status": storage,\n    }\n'''
s = replace_once(s, old_list_return, new_list_return, "list signal storage status")

old_roots = '''@router.get("/roots/{date}")\ndef roots_for_date(date: str):\n    path = SIGNAL_ROOT / date / "manifests.jsonl"\n    if not path.exists():\n        return {"date": date, "roots": [], "count": 0}\n    roots: list[dict[str, Any]] = []\n    for line in path.read_text(encoding="utf-8").splitlines():\n        if line.strip():\n            try:\n                roots.append(json.loads(line))\n            except ValueError:\n                continue\n    return {"date": date, "roots": roots, "count": len(roots)}\n'''
new_roots = '''@router.get("/roots/{date}")\ndef roots_for_date(date: str):\n    if _ensure_database():\n        try:\n            with psycopg.connect(_database_url(), autocommit=True, connect_timeout=5) as conn:\n                with conn.cursor() as cur:\n                    cur.execute(\n                        "SELECT payload FROM philthy_evidence_manifests "\n                        "WHERE evidence_date = %s ORDER BY created_at ASC",\n                        (date,),\n                    )\n                    values = cur.fetchall()\n            roots = [value[0] if isinstance(value[0], dict) else json.loads(value[0]) for value in values]\n            return {\n                "date": date,\n                "roots": roots,\n                "count": len(roots),\n                "storage_root": "render_postgres",\n                "durable_storage": True,\n            }\n        except Exception as exc:\n            _mark_db_failed(exc)\n\n    path = SIGNAL_ROOT / date / "manifests.jsonl"\n    if not path.exists():\n        return {\n            "date": date,\n            "roots": [],\n            "count": 0,\n            "storage_root": "server_runtime_fallback",\n            "durable_storage": False,\n        }\n    roots: list[dict[str, Any]] = []\n    for line in path.read_text(encoding="utf-8").splitlines():\n        if line.strip():\n            try:\n                roots.append(json.loads(line))\n            except ValueError:\n                continue\n    return {\n        "date": date,\n        "roots": roots,\n        "count": len(roots),\n        "storage_root": "server_runtime_fallback",\n        "durable_storage": False,\n    }\n'''
s = replace_once(s, old_roots, new_roots, "roots durable storage")
runtime.write_text(s)

# 2) Backend requirements.
requirements = Path("backend/requirements.txt")
r = requirements.read_text()
if "psycopg[binary]" not in r:
    r = r.rstrip() + "\npsycopg[binary]>=3.2,<4\n"
requirements.write_text(r)

# 3) Backend status: distinguish implemented/verified controls from strict sport
# promotion proof, report durable evidence storage, and account for every
# credentialed API adapter without treating an unrotated key as safe.
app = Path("backend/app.py")
a = app.read_text()
a = replace_once(a, 'APP_VERSION = "1.6.5"', 'APP_VERSION = "1.6.6"', "backend version")
a = replace_once(
    a,
    '    odds_key = bool(os.getenv("ODDS_API_KEY", "").strip())\n    credential_status = (\n        "CONFIGURED_CANARY_EVIDENCE_REQUIRED" if rotation and odds_key\n        else "BLOCKED_ROTATION_CONFIRMATION_REQUIRED" if odds_key\n        else "BLOCKED_FRESH_ROTATED_KEY_REQUIRED"\n    )\n',
    '    provider_key_state = {\n        "the_odds_api": bool(os.getenv("ODDS_API_KEY", "").strip()),\n        "odds_api_net": bool(os.getenv("ODDS_API_NET_KEY", "").strip()),\n        "sportradar": bool(os.getenv("SPORTRADAR_API_KEY", "").strip()),\n    }\n    odds_key = any(provider_key_state.values())\n    credential_status = (\n        "CONFIGURED_CANARY_EVIDENCE_REQUIRED" if rotation and odds_key\n        else "BLOCKED_ROTATION_CONFIRMATION_REQUIRED" if odds_key\n        else "BLOCKED_FRESH_ROTATED_KEY_REQUIRED"\n    )\n',
    "multi-provider credential status",
)

a = replace_once(
    a,
    '    remaining = [\n        "physical Android-device end-to-end smoke testing",\n        "durable runtime prediction ledger plus rollback/alert validation",\n    ]\n',
    '    evidence_storage = evidence_storage_status()\n    counts = capture.get("canonical_rows") or {}\n    policy = V8_GATE_STATUS.get("sample_policy") or {}\n    sample_summary = "; ".join(\n        f"{sport} {int(counts.get(sport) or 0)}/{int((policy.get(sport) or {}).get(\"minimum_total_rows\") or 0)}"\n        for sport in SPORTS\n    )\n\n    remaining = [\n        "physical Android-device end-to-end smoke testing",\n        "rollback drill and alert validation",\n    ]\n    if not evidence_storage.get("durable"):\n        remaining.insert(0, "durable runtime prediction ledger storage")\n',
    "evidence storage status",
)

old_gate_details = '''        "gate_details": {\n            "credential_live_odds_props": credential_action,\n            "four_sport_model_promotion": (\n                "All four trained models passed their promotion checks." if promotion_pass else\n                "Trained models have not passed every data, chronology and accuracy check. Available fresh market baselines remain usable."\n            ),\n        },\n'''
new_gate_details = '''        "gate_display": {\n            "chronology": "Passed" if chronology_pass else (\n                "Capture verified · promotion pending" if capture_verified else "Evidence needed"\n            ),\n            "calibration": "Passed" if calibration_pass else "Control implemented · promotion pending",\n            "leakage": "Passed" if leakage_pass else "Control implemented · promotion pending",\n            "provenance": "Passed" if provenance_pass else (\n                "Dataset hashes verified · model provenance pending" if capture_verified else "Evidence needed"\n            ),\n            "four_sport_model_promotion": "Passed" if promotion_pass else "Sample threshold pending",\n            "credential_core_keyless": "Passed",\n            "credential_live_odds_props": (\n                "Canary pending" if rotation and odds_key else\n                "Rotation confirmation pending" if odds_key else\n                "Fresh credential pending"\n            ),\n            "stable_android_signing": "Passed",\n            "immutable_pregame_evidence_capture": "Passed" if capture_verified else "Verification needed",\n        },\n        "gate_details": {\n            "chronology": (\n                "Canonical pregame capture is checksum-verified under as_of < event_time. "\n                "Per-sport promoted-model chronology remains part of the strict promotion gate."\n            ),\n            "calibration": (\n                "Chronological OOF-only calibration and ECE/log-loss/Brier gates are implemented. "\n                "No sport has enough canonical settled rows yet to produce a promoted calibration artifact."\n            ),\n            "leakage": (\n                "Temporal leakage checks are implemented fail-closed. A promoted sport artifact still requires "\n                "its own successful leakage evidence."\n            ),\n            "provenance": (\n                "Canonical dataset and source-manifest hashes are verified. Signed promoted-model artifact "\n                "provenance remains pending until a sport passes promotion."\n            ),\n            "credential_live_odds_props": credential_action,\n            "four_sport_model_promotion": (\n                "All four trained models passed their promotion checks." if promotion_pass else\n                f"Current canonical settled rows versus strict minimums: {sample_summary}. "\n                "Fresh governed market baselines remain active until each sport passes."\n            ),\n        },\n        "evidence_storage": evidence_storage,\n'''
a = replace_once(a, old_gate_details, new_gate_details, "gate display/details")

a = replace_once(
    a,
    '            "odds_api_key_configured": odds_key,\n            "odds_props_live_allowed": rotation and odds_key,\n',
    '            "odds_api_key_configured": provider_key_state["the_odds_api"],\n            "odds_api_net_key_configured": provider_key_state["odds_api_net"],\n            "sportradar_api_key_configured": provider_key_state["sportradar"],\n            "any_credentialed_provider_configured": odds_key,\n            "odds_props_live_allowed": rotation and odds_key,\n',
    "credential provider detail",
)

a = replace_once(
    a,
    '        "production_ready_reason": "The backend has HTTPS, pinned Android signing, four-sport adapters, and a verified checksummed pregame evidence history. Production-ready remains blocked until four sport-specific trained models accumulate sufficient resolved samples and pass every v8 promotion gate, live provider canaries and credential revocation are evidenced, the runtime prediction ledger/rollback alerts are validated, and a physical-device end-to-end smoke run is recorded.",\n',
    '        "production_ready_reason": (\n            "The backend has HTTPS, pinned Android signing, four-sport adapters, and a verified checksummed pregame evidence history. "\n            "Production-ready remains blocked until four sport-specific trained models accumulate sufficient resolved samples and pass every v8 promotion gate, "\n            "live provider canaries and credential revocation are evidenced, rollback/alert validation is recorded, and a physical-device end-to-end smoke run is recorded."\n            + (" Durable runtime ledger storage is active." if evidence_storage.get("durable") else " Durable runtime ledger storage is not active yet.")\n        ),\n',
    "production readiness reason",
)

a = replace_once(
    a,
    'from evidence.runtime import SignalEvidenceMiddleware, router as evidence_router\n',
    'from evidence.runtime import (\n    SignalEvidenceMiddleware,\n    router as evidence_router,\n    storage_status as evidence_storage_status,\n)\n',
    "evidence storage import",
)
app.write_text(a)

# 4) Make Settings accurately describe the distinction instead of turning every
# strict promotion block into the same "Evidence needed" label.
dashboard = Path("mobile_dashboard/app/sports-dashboard.tsx")
d = dashboard.read_text()
old = "<b className={String(v).startsWith('PASS')?'passed':'pending'}>{String(v).startsWith('PASS')?'Passed':String(v).startsWith('BLOCKED')?'Evidence needed':'Verification needed'}</b>"
new = "<b className={String(v).startsWith('PASS')?'passed':'pending'}>{status.gate_display?.[k]||String(v).startsWith('PASS')?'Passed':String(v).startsWith('BLOCKED')?'Evidence needed':'Verification needed'}</b>"
# Parentheses are required because ??/|| precedence with the conditional would be
# ambiguous. Use a safe final expression instead.
new = "<b className={String(v).startsWith('PASS')?'passed':'pending'}>{status.gate_display?.[k]||(String(v).startsWith('PASS')?'Passed':String(v).startsWith('BLOCKED')?'Evidence needed':'Verification needed')}</b>"
d = replace_once(d, old, new, "dashboard gate display")
dashboard.write_text(d)

# 5) Release version bump for the configured APK.
pubspec = Path("pubspec.yaml")
p = pubspec.read_text()
p = replace_once(p, "version: 1.6.5+28", "version: 1.6.6+29", "Flutter version")
pubspec.write_text(p)

package = Path("mobile_dashboard/package.json")
pj = package.read_text()
pj = replace_once(pj, '"version": "1.6.5"', '"version": "1.6.6"', "dashboard package version")
package.write_text(pj)

lock = Path("mobile_dashboard/package-lock.json")
pl = lock.read_text().replace('"version": "1.6.5"', '"version": "1.6.6"', 2)
lock.write_text(pl)

print("Applied durable evidence, status clarity, provider-state, and 1.6.6 release fixes.")

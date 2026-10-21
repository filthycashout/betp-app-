# Sports Omni Project

Evidence-first shared workspace for NFL, NBA, NHL, MLB, and UFC inside the existing `filthycashout/betp-app-` repository. This is an integration layer, not a second production backend.

## Status

Configured here: core probability helpers, American-odds normalization, freshness/data-quality gates, JSON evidence CLI, schema, tests, canonical notebook entry points, and a read-only adapter to the existing five-sport backend. Not yet complete: verified provider credentials and coverage, promoted/calibrated models for every market, live prop coverage, dependence-aware parlays, fully scheduled automation or deployment. Empty/stale evidence fails closed; no synthetic schedule or pick is generated.

## Quick start (Python 3.11+)

```sh
cd Sports_Omni_Project
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows: .venv\\Scripts\\activate
python -m pip install -e '.[test]'
pytest -q
python 01_Core_Engine/orchestrator.py 03_Data_and_Features/schemas/sample_evidence.json --output 05_Daily_Outputs/data_quality_report.json
```

The empty fixture intentionally returns exit code 2 because no eligible event exists; this is the evidence gate working, not a fabricated success.

## Live report from the existing governed backend

From the repository root, install the backend's runtime dependencies and run:

```sh
python -m pip install -r backend/requirements.txt -r backend/requirements-validation.txt
python Sports_Omni_Project/01_Core_Engine/live_report.py --date 2026-10-22 --sport NBA
```

Omit `--date` to use the current Pacific date, and omit `--sport` to cover NFL, NBA, MLB, NHL, and UFC. The JSON report is written to `Sports_Omni_Project/05_Daily_Outputs/games/YYYY-MM-DD.json`. This report is **read-only**, and the existing `backend/sports_ai/live.py` and promotion/market gates are authoritative. It separates verified promoted-model analyses from market-only baseline analyses, and suppresses unsupported selections. No props or parlays are invented; every selection requires human review.

For a phone-first one-click run, open **GitHub → Actions → Sports Omni Live Snapshot → Run workflow** on the main branch after the integration PR is merged. Select a sport/date or use ALL/current Pacific date; download the seven-day retained JSON artifact from the workflow run. It is manual by design to avoid unexpected provider API costs. `ODDS_API_KEY` remains an optional GitHub Actions secret that must be configured through repository settings with a valid, rotated credential; missing keys cause coverage restrictions, not fabricated prices. Provider failures return exit code 2 and still attempt to upload a diagnostic report. A passing workflow only verifies that the adapter ran, **not** that models were promoted or complete pricing was available.

Run the repo-backed tests using:

```sh
cd Sports_Omni_Project
python -m pip install -e '.[test]'
pytest -q
```

## Required event fields

Events: `event_id,sport,start_time,home_team,away_team,source,observed_at`. Quotes: `event_id,sport,market,selection,odds_american,book,source,observed_at`. Timestamps must be timezone-aware ISO-8601. Keep provider timestamp separate from local observed-at time.

## Layout and gates

- `01_Core_Engine`: orchestration, quality, odds, probability, freshness.
- `02_Models`: sport models, calibration and registry; no promotion by filename alone.
- `03_Data_and_Features`: provider adapters, ingestion, features and schemas.
- `04_Historical_Results`: immutable predictions, settled labels, closing odds.
- `05_Daily_Outputs`: game, prop and parlay reports with evidence timestamps.
- `06_Notebooks`: ingestion, evaluation, readiness and data-quality audits.
- `07_Reports_and_Analysis`: backtests, calibration, CLV and operational reports.
- `08_Archive_Duplicates`: preserve legacy artifacts before deduplication.
- `09_Docs_and_README`: integration map and runbooks.

Promotion requires point-in-time-correct data, chronological holdouts, leakage checks, per-sport calibration, market-baseline comparison, source provenance, artifact hashes, provider canaries and deployment verification. Player props require current player/role/line/price evidence. Parlays require actual prices and a validated joint-probability method; independent multiplication is only an assumption.

# Sports Omni Project

Evidence-first shared workspace for NFL, NBA, NHL and MLB inside the existing `filthycashout/betp-app-` repository. This is an integration layer, not a second production backend.

## Status

Configured here: core probability helpers, American-odds normalization, freshness/data-quality gates, JSON evidence CLI, schema, tests and canonical notebook entry points. Not yet complete: live provider ingestion, promoted/calibrated models, live prop coverage, dependence-aware parlays, scheduled automation or deployment. Empty/stale evidence fails closed; no synthetic schedule or pick is generated.

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

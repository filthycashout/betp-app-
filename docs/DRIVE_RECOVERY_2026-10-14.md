# Google Drive evidence recovery — 2026-10-14

## Purpose

This record documents the Drive material reviewed to close evidence-pipeline gaps without weakening Master Protocol v8. Google Drive is an evidence source, not a model-promotion authority.

## Recovered material

The reviewed Drive inventory confirms useful historical material for MLB and NFL, but no complete promotion-grade four-sport corpus.

- MLB: `PREDICTED_VS_ACTUAL_RESULTS_2026-07-02.csv`, `MLB_Feature_Dictionary_v2.docx`, `2026-06-26_MLB_Experiment_Summary.docx`, feature snapshots and tracking metadata.
- NFL: historical prop model/scaler files and `nfl_analysis_results.json`; serialized joblib artifacts remain quarantined and are not deserialized as evidence.
- NBA: framework/documentation only; no verified reconstructable sport-specific training bundle was recovered.
- NHL: `NHL models` and `NHL_AI` scaffolds exist, but the inspected data/model areas do not contain a verified training corpus.

The existing reconstruction manifest remains authoritative for Drive IDs and checksums.

## Pregame feature policy

Drive feature concepts may be implemented only when each value has verifiable point-in-time provenance satisfying `observed_at <= prediction_time < event_time`.

Potentially admissible when timestamped and source-validated:

- recent form derived strictly from games completed before prediction time;
- pregame injury flags/scores;
- park/context factors known before first pitch/puck/tip/kickoff;
- probable starter/role/opportunity features known before event start;
- current market/odds context captured before event start.

Explicitly inadmissible for pregame promoted training:

- `live_win_probability_trend`;
- final scores or final game status as features;
- LIVE-adjusted prediction rows;
- post-start injuries, substitutions or game state;
- legacy claimed `confidence`, `edge`, recommendation labels or "quantum" flags without reproducible OOF evidence;
- random/hash-derived/synthetic notebook values;
- any serialized legacy model whose schema, timing, provenance and checksum contract has not independently passed the promotion gate.

## Repairs made from this review

1. Canonical production evidence capture defaults to `https://philthyparleys.floot.app/_api`.
2. Retired PhilthySports Render hosts are rejected by the training evidence collector rather than accepted as explicit overrides.
3. The standalone production MCP endpoint is explicitly disabled in the shared source map; Floot is the governed production backend.
4. A manual player-prop evidence collector records current pregame market rows with checksums while forcing `promotion_eligible=false`, `model_probability=null`, and `automatic_wagering=false`.
5. Regression tests lock the Floot namespace, retired-host rejection, chronology, and research-only prop semantics.

## What this does not prove

This recovery does **not** promote a model. Drive evidence still does not provide the required clean, sufficiently large, timestamped and settled NFL/NBA/MLB/NHL prop corpus with walk-forward OOF predictions and OOF-only calibration. Until those requirements pass, runtime model probabilities remain unavailable or market-baseline-only.

# Promoted model aliases

This directory is a runtime alias location, not a promotion mechanism.

A file named `<sport>.json` here is **not** considered promoted merely because it exists. `backend/model_runtime.py::load_promoted()` must parse it and the deterministic `promotion_gate()` must pass every required check before runtime inference can use it.

Do not place legacy `.joblib`, `.pkl`, `.pickle`, `.sav`, notebook, synthetic/demo, or research-only artifacts here.

The only intended active aliases are:

- `nfl.json`
- `nba.json`
- `mlb.json`
- `nhl.json`

Those files are created only by the governed train/promote workflow after admitted evidence, sample, chronology, OOF calibration, holdout, Brier/log-loss/ECE, leakage, provenance, parity, checksum, signature, and immutable-registry gates pass.

Absence of a sport JSON file means no promoted trained artifact is available for that sport. Presence of a rejected JSON file is a CI/runtime failure, not permission to use it.

# PhilthyParleys MLOps Automation

This document describes the governed automation path for data quality, chronological training, immutable model artifacts, and serving. It intentionally keeps automatic wagering disabled and preserves the market-baseline fallback until a trained candidate passes every promotion gate.

## 1. Data and schema contract

`backend/training/data_contract.py` is the fail-closed contract boundary.

Two contracts are enforced:

- `pregame`: validates raw pregame snapshots before they are admitted to durable evidence history.
- `canonical`: validates settled canonical training rows before sample counting or training.

Required chronology invariants include:

- `as_of < event_time`
- `label_available_at > event_time` for settled training rows
- unique `(sport, event_id)` keys
- distinct home and away teams
- binary `target_home_win`
- market probabilities strictly between zero and one when present
- finite numeric values for the exact features requested by training

The evidence workflow writes contract PASS reports beside run metadata. A contract failure blocks the capture commit or training run rather than allowing malformed rows into model training.

## 2. Chronological training

The production training path is script-based, not notebook-based:

- `backend/training/governed_train.py`
- `backend/training/strict_promote.py`
- `.github/workflows/v8-train-promote.yml`

The trainer uses point-in-time data, chronological holdout, time-ordered out-of-fold predictions, in-fold preprocessing, Platt/isotonic calibration selection, Brier/log-loss/ECE evaluation, leakage checks, and the existing sport-specific sample policy.

The scheduled workflow remains a promotion checker rather than an unconditional promoter. If evidence is insufficient or any gate fails, the market baseline remains active.

Recommended operating cadence:

- evidence/odds capture: hourly or more frequently at the runtime layer when provider terms allow;
- settled player/team statistics: after games finish, normally daily reconciliation;
- model retraining: daily for NBA/MLB/NHL is sufficient for this architecture; NFL can be reduced to a weekly Tuesday post-MNF run once the evidence corpus is mature;
- model promotion: only when a new candidate passes every deterministic gate, never merely because a schedule fired.

## 3. Immutable artifact registry

`backend/training/register_artifact.py` creates a content-addressed registry under `backend/models/registry/`.

Only a `PROMOTED_TRAINED_MODEL` may be registered. Registration verifies:

- the artifact's canonical SHA-256;
- the signed-core SHA-256;
- signature metadata presence;
- dataset SHA-256;
- feature-schema SHA-256;
- sport identity.

Artifacts are stored as:

`backend/models/registry/<sport>/<artifact_sha256>.json`

`backend/models/registry/index.json` records immutable history and the active artifact hash for each sport. Re-registering the same artifact is idempotent. A hash collision with different bytes fails closed.

The existing `backend/models/promoted/<sport>.json` paths remain the runtime-friendly active aliases, but every promoted alias must now have a corresponding immutable registry entry.

## 4. Serving

The existing production serving architecture already satisfies the core serving requirement:

- FastAPI backend;
- Docker image;
- GitHub Actions image build;
- immutable image tag by Git commit SHA;
- governed runtime model gate;
- `/v1/models/registry` runtime visibility;
- manual-review-only recommendation behavior.

The larger PhilthyParleys project therefore consumes the governed runtime, not notebooks.

### Zero-cost paths

The lowest-cost training/orchestration path is the existing public GitHub repository using standard GitHub-hosted Actions runners. Keep model artifacts compact and content-addressed in Git when practical.

For HTTP serving, Cloudflare Workers Free is a possible secondary deployment target because Python Workers support FastAPI/Pydantic. The safest compatibility path is to serve the current portable JSON model representation with pure Python inference rather than trying to load legacy `joblib` or arbitrary scikit-learn binaries in the Worker runtime.

The only strict no-cloud/no-API inference path is on-device inference in the Flutter client. The current trainer already emits portable model structure, but on-device production must remain disabled until preprocessing parity, signature/checksum validation, and physical-device tests pass.

## 5. Drive notebook disposition

Legacy Drive notebooks remain research inputs only.

The BetP v3 notebook used XGBoost, pandas, NumPy, joblib and hand-built features, but it also generated random form/injury/probability perturbations. Those notebook predictions are not admissible promotion evidence.

Useful notebook concepts may be ported into governed scripts only when they have:

- deterministic feature definitions;
- point-in-time timestamps;
- source provenance;
- chronological train/validation/holdout separation;
- OOF-only calibration;
- reproducible tests;
- schema versioning.

XGBoost or LightGBM can later be added as challenger model families, but they must compete against the current baseline under the same Brier/log-loss/ECE and leakage gates. They do not bypass promotion requirements.

## 6. Operational invariant

Notebook output != production model.

Captured data != admitted training data until the contract passes.

Trained candidate != promoted artifact until strict evaluation passes.

Promoted artifact != active runtime model until signature, checksum, schema, and runtime gates pass.

Automatic wagering remains disabled.

## 7. Completion terminology

For this repository, **Complete** is scoped to the artifact being evaluated.

A notebook is complete when it performs its intended notebook-level job. That does **not** mean every external API, GPU-backed model, local server, data provider, or sport-specific prediction model is currently available.

Likewise:

- code exists != promoted model;
- legacy model file != promoted model;
- baseline `production.json` != promoted trained model;
- candidate registry entry != promoted trained model;
- configured Docker/scheduler path != observed successful runtime execution;
- successful CI for code/schema != successful model promotion;
- successful signing != successful runtime activation unless `load_promoted()` accepts the artifact.

`backend/model_runtime.py::load_promoted()` together with `promotion_gate()` remains the final deterministic model-activation authority. `backend/training/completeness_audit.py` continuously checks that the repository state does not contradict these distinctions.

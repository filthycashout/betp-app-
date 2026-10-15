# PhilthyParleys current state and file map

This document is a location map and state-semantics contract. It does **not** promote a model, certify an external service, or claim that a configured workflow has succeeded at runtime.

## Core state invariants

- **Code exists != promoted model.** Training, calibration, signing, registry, or inference code can exist without any sport having a promoted trained artifact.
- **Legacy model file != promoted model.** A `.joblib`, `.pkl`, `.pickle`, `.sav`, notebook export, experiment output, or historical serialized model is research/candidate material until the current deterministic promotion gate accepts a signed portable artifact.
- **Notebook complete != production model.** Here, `Complete` means a notebook performs its intended notebook-level job. It does not imply that an external API, GPU model, local server, sportsbook feed, or sport-specific prediction model is currently available.
- **Baseline artifact != trained promoted model.** The four `production.json` files under `backend/models/<sport>/` are governed market baselines with `trained_weights=false`.
- **Configured state != observed runtime state.** A Dockerfile, Compose restart policy, cron/GitHub Actions schedule, API URL, or provider configuration proves configuration only. Runtime success requires observed execution evidence.

## Canonical locations

| Purpose | Current location | Authority / meaning |
|---|---|---|
| FastAPI runtime | `backend/app.py` | Serving logic; code existence is not promotion. |
| Deterministic model runtime gate | `backend/model_runtime.py` | **Promotion authority.** `load_promoted()` returns a model only if `promotion_gate()` passes. |
| Governed baseline manifest | `backend/models/manifest.json` | Declares the four-sport market-baseline bundle. It explicitly has `trained_weights=false`. |
| NFL baseline | `backend/models/nfl/production.json` | Production market baseline, not trained ML promotion. |
| NBA baseline | `backend/models/nba/production.json` | Production market baseline, not trained ML promotion. |
| MLB baseline | `backend/models/mlb/production.json` | Production market baseline, not trained ML promotion. |
| NHL baseline | `backend/models/nhl/production.json` | Production market baseline, not trained ML promotion. |
| Legacy/candidate disposition | `backend/models/candidate_registry.json` | Describes historical candidates; never grants runtime authority. |
| Active promoted aliases | `backend/models/promoted/<sport>.json` | A file here is still **not active** unless `load_promoted()` accepts it. |
| Immutable promoted registry | `backend/models/registry/<sport>/<artifact_sha256>.json` | Content-addressed history written only after governed promotion. |
| Immutable registry index | `backend/models/registry/index.json` | Active/promoted artifact hashes after registration. |
| Training implementation | `backend/training/governed_train.py` | Candidate training implementation; not promotion authority. |
| Strict evaluation/promotion | `backend/training/strict_promote.py` | Builds/evaluates candidates; result still must be signed and accepted by runtime. |
| Artifact signer client | `backend/training/sign_promoted.py` | Produces signed artifact material; signature alone is not promotion. |
| Artifact registration | `backend/training/register_artifact.py` | Writes immutable registry only for promoted artifacts. |
| Evidence contract | `backend/training/data_contract.py` | Pregame/canonical schema and chronology validation. |
| Evidence admission | `backend/training/evidence_admission.py` | Separates captured/recovered data from training-admitted evidence. |
| Evidence capture pipeline | `backend/training/evidence_pipeline.py` | Capture/build/settlement tooling. |
| Official settlement proof | `backend/training/settlement_proof.py` | Independent result-proof sidecars. |
| Allspice/Drive recovery classifier | `backend/training/recovery_manifest.py` | Classifies historical material; classification is not promotion. |
| Allspice recovery policy | `backend/training/ALLSPICE_RECOVERY.md` | Human-readable recovery and quarantine rules. |
| MLOps operating contract | `backend/training/MLOPS_AUTOMATION.md` | Describes governed automation and promotion semantics. |
| Legacy Drive/notebook inventory | `integrations/drive-evidence/drive_research_inventory_2026-10-06.md` | Research inventory; not canonical training/promotion evidence. |
| Backend Docker image | `backend/Dockerfile` | Reproducible serving container with healthcheck. |
| Portable deployment | `deploy/docker-compose.prod.yml` | Long-running service configuration with restart policy and manual-review-only environment. |
| Evidence scheduler | `.github/workflows/v8-evidence-capture.yml` | Hourly evidence attempt; a scheduled run is not automatically a successful capture. |
| Train/promote scheduler | `.github/workflows/v8-train-promote.yml` | Hourly promotion checker; schedule firing does not mean a model is promoted. |
| Completeness state audit | `backend/training/completeness_audit.py` | Deterministically checks the distinctions in this document. |
| Completeness CI | `.github/workflows/completeness-contract.yml` | Runs the state audit and retains its report. |

## Durable evidence location

Canonical evidence history is intentionally not treated as ordinary source code on `main`. The scheduled evidence workflow writes immutable history to the `evidence-snapshots` branch, including:

- `evidence/pregame/...`
- `evidence/canonical/nfl.csv`
- `evidence/canonical/nba.csv`
- `evidence/canonical/mlb.csv`
- `evidence/canonical/nhl.csv`
- source manifests
- contract reports
- settlement proof sidecars
- `evidence/run_metadata/admission_latest.json`

Training is permitted to proceed only when the admission report is present, PASS, version-compatible, and bound to the exact canonical dataset hashes.

## Notebook disposition

The production training path is script-based. Historical notebook exports are research material only unless their useful concepts are reimplemented under the current point-in-time data contract, chronological split, OOF calibration, leakage, provenance, metric, signing, and runtime gates.

The known BetP v3 notebook material is specifically unsuitable as direct promotion evidence because the prior Drive audit found synthetic/randomized feature and prediction behavior. Notebook-level completion therefore means only that the notebook accomplished its own intended task.

## External website classification from the October 2026 review

The following user-supplied sites are sports **employment/recruiting** sources, not sports-statistics or model-training libraries:

- `https://www.workinsports.com/` — employment/recruiting platform.
- `https://www.teamworkonline.com/` — sports/entertainment recruiting and job network.
- `https://hub.globalsportsjobs.com/` — international sports careers/vacancy platform.
- `https://www.jobsinsports.com/` — sports employment database/job board with listing-freshness practices.

They are classified **EMPLOYMENT_DISCOVERY_ONLY** for PhilthyParleys. They have no training, settlement, probability, model-promotion, or wagering authority. Their useful architectural lesson is limited to source categorization, freshness labeling, deduplication/verification concepts, and explicit separation of discovery from authoritative state.

## Docker and scheduling decision

The pasted standalone `docker run` + host `cron` example is not added as a second production scheduler because this repository already has:

- a backend Dockerfile;
- a Compose service with `restart: unless-stopped` and healthcheck;
- hourly GitHub Actions evidence capture;
- hourly GitHub Actions train/promotion checking.

Adding a second unmanaged cron path would create duplicate execution, race, provenance, and secret-management risk. If the project is later moved to a dedicated host, host cron/systemd timers may be used only as an explicitly selected deployment mode, not simultaneously with the governed GitHub scheduler without idempotency and locking evidence.

## What counts as a promoted model

A sport is promoted only when all of the following are true:

1. admitted point-in-time canonical evidence exists;
2. sport sample thresholds are met;
3. chronological walk-forward/OOF and in-fold preprocessing pass;
4. calibration uses OOF data and an untouched holdout;
5. candidate Brier improves over baseline;
6. log loss is non-inferior under policy;
7. ECE is within policy (`<= 0.01` in the current v8 contract);
8. leakage audit passes;
9. dataset/source/schema/model provenance hashes exist and match;
10. portable inference parity passes;
11. the artifact is signed with the expected key and all checksums verify;
12. the immutable registry accepts it;
13. `backend/models/promoted/<sport>.json` exists;
14. `backend/model_runtime.py::load_promoted(<sport>)` returns the artifact.

Anything less is baseline, candidate, legacy/reference material, unavailable, or blocked — never silently promoted.

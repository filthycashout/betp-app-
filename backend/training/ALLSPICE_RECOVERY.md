# Allspice Recovery and Sports_Omni Canonicalization

## Authority boundary

Allspice and Google Drive are recovery/reference sources. They are not model-promotion authority.
The machine-governed training authority remains the checksummed `evidence-snapshots` branch after data-contract and evidence-admission checks pass.

`LEGACY FILE EXISTS != CANONICAL TRAINING EVIDENCE`

`EVIDENCE ADMITTED != MODEL PROMOTED`

Automatic wagering remains disabled.

## Canonical Drive home

`Sports_Omni_Project` is the intended human-readable sports archive. The recommended mapping is:

- `01_Core_Engine/` — architecture and code references only.
- `02_Data_and_Features/` — raw manifests, pregame snapshots, feature schemas, source registry.
- `03_Historical_Results/` — settled NFL/NBA/MLB/NHL result material.
- `04_Models/` — candidate/reference/rejected/promoted artifact records; legacy binaries remain quarantined until independently reproduced.
- `05_Training_and_Validation/` — walk-forward folds, OOF predictions, calibration, leakage reports.
- `06_Reports_and_Outputs/` — historical prediction/report outputs that do not themselves establish truth.
- `07_Recovery_Manifests/` — normalized Allspice/Drive recovery inventories.
- `08_Archive_Duplicates/` — duplicate/obsolete snapshots by content hash.
- `09_Docs_and_README/` — v8 audits, integration inventories, governance documentation.

The repository does not move or delete Drive files automatically. Drive mutation is a separate human-controlled operation. The repo records deterministic classification and admissibility rules.

## Recovery classifications

Every legacy artifact is assigned exactly one recovery classification:

- `ADMISSIBLE_PREGAME` — explicit immutable pre-start chronology + provenance + verified content hash.
- `SETTLEMENT_ONLY` — authoritative result/label material; not a prediction feature source.
- `FEATURE_REFERENCE` — feature/schema ideas that require reconstruction in the governed pipeline.
- `MODEL_REFERENCE` — old `.joblib`/pickle/model/preprocessor artifacts; never executed to infer missing provenance.
- `LIVE_LEAKAGE` — in-play/post-start information excluded from pregame training.
- `SYNTHETIC` — random/demo/generated values excluded from evidence.
- `DUPLICATE` — duplicate content hash; one canonical copy is sufficient.
- `EMPTY` — empty DB/folder/schema shell.
- `SECRET_EXCLUDED` — credentials, keys, `.env`, tokens; never imported into evidence.
- `ARCHIVE_ONLY` — useful lineage/history with no training authority.

`backend/training/recovery_manifest.py` turns the existing Drive reconstruction inventory into this normalized classification. CI produces a checksummed recovery manifest artifact.

## Evidence contract v2

New live captures bind, when actually supplied, the following metadata without inventing missing provider identifiers:

- sport/event identity
- provider event/market identity
- market type and selection
- line and price/book when supported
- provider/source
- `quote_captured_at`
- `event_started_at`
- raw snapshot SHA-256

Core chronology remains:

`quote_captured_at/as_of < event_started_at/event_time`

A missing provider-specific market ID remains `null`; it is never synthesized.

## Settlement proof

`settlement_proof.py` independently re-queries the recognized league result source after an event settles and stores a sidecar with:

- event identity
- source event identity
- final home/away score
- derived binary home-win label
- settlement source
- first proof-observation timestamp
- hash of the provider event payload used as proof
- proof-record hash

Current accepted settlement sources are:

- NFL/NBA: ESPN scoreboard result feed used by the existing evidence pipeline
- MLB: MLB Stats API
- NHL: NHL Web API

Where an upstream does not expose an authoritative event-ended timestamp, PhilthyParleys does **not** invent one. The proof records the first independently observed final state instead.

## Evidence admission gate

`evidence_admission.py` runs after capture, settlement, official-result proof, canonical rebuild, and historical merge.

It requires:

1. capture rows and raw body match their manifests' SHA-256 values;
2. pregame rows pass Pydantic chronology/schema checks;
3. contract-v2 live captures have independent official-result proof once settled;
4. label and proof agree on the outcome;
5. canonical NFL/NBA/MLB/NHL files pass the training contract;
6. each canonical file hash matches its canonical source manifest.

The resulting `evidence/run_metadata/admission_latest.json` is the control-plane artifact consumed by training.

## Training gate

`v8-train-promote.yml` will not attempt sample sufficiency or training unless:

- the evidence branch exists;
- an admission v2 report exists;
- that report is `PASS`;
- all four canonical CSV SHA-256 hashes match the hashes recorded in the admission report;
- the Pydantic canonical contract passes again.

Only then do the existing gates run: sample sufficiency, chronological walk-forward OOF, in-fold preprocessing, OOF-only calibration, independent holdout, Brier improvement, non-inferior log loss, ECE <= 0.01, leakage audit, provenance/schema hashes, signing, runtime parity, and immutable artifact registration.

## Transaction/promotion fields

Fields such as wager amount, payout, bonus-fund eligibility, sportsbook promotion IDs, wash-trading rules, and transaction references are **not** model-promotion criteria. They belong in a separate execution/audit ledger only if a real user-directed transaction exists.

PhilthyParleys can learn from a valid market observation without placing a wager.

## Legacy examples

The existing Drive reconstruction manifest already establishes that:

- the July MLB feature snapshot is a small mixed snapshot and is not a canonical multi-season corpus;
- tracked material can mix PRE-GAME and LIVE-adjusted states, so live rows are excluded;
- legacy NFL `.joblib` models/scalers have insufficient promotion provenance and remain quarantined;
- NBA/NHL legacy folders do not contain a complete promotion-grade training bundle;
- empty organizational folders do not count as evidence.

Those facts are preserved; this automation does not promote any legacy artifact merely by classifying it.

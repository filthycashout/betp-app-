# Training and evidence

This directory records only evidence that can be reconstructed without trusting leaked credentials or deserializing untrusted pickle/joblib files. Production promotion remains governed by Master Protocol v8.

## Current evidence state

- NFL legacy evidence: 241 canonical rows remain subject to the historical settlement-time repair described by the v8 evidence audit.
- NFL archive research: a separate checksum-verified `nflverse/nfldata` recovery path produced 1,596 rows from 149 archived snapshots spanning 2020-2025. Its canonical CSV SHA-256 is `4889736d0bb4e513fc118fefd442b99333c3cbd2501c27503c38eedac22f8949`. Five focused importer/quarantine tests passed in the supplied research run. This corpus is **research-only**: upstream Git committer timestamps are not independently witnessed sportsbook publication receipts, and the source manifest explicitly holds promotion.
- The NFL research candidate is not promoted: Brier `0.212071438` vs market `0.211269473`, log loss `0.611067451` vs market `0.608803910`, ECE `0.081047059` vs the `0.01` maximum. Portable numerical parity passed, but the metric and source-admissibility gates did not.
- MLB: feature snapshot/schema, dictionary, experiment summary, settled evaluation, and tracking files are checksummed. Useful evidence, not a canonical production training corpus.
- NBA: no sport-specific reconstructable production training bundle has been verified.
- NHL: no sport-specific reconstructable production training bundle has been verified.
- Legacy joblib/pickle artifacts remain quarantined unless their schema, timing, provenance, checksum and promotion evidence are independently validated.

See `NFL_ARCHIVE_RESEARCH.md` for the reproducible NFL research path. A successful schema check or successful CI run is not model-promotion approval.

## Google Drive research references

Drive material may be used to recover architecture ideas, source names, feature concepts, documentation and historical provenance, but not as automatic production truth. Inspected legacy BetP/SportsMachine material contains useful ideas such as agent orchestration, market de-vigging, calibration, time-series evaluation, model persistence, props/parlays and result tracking.

Do **not** import generated/demo rows as canonical evidence. In particular, the inspected `BetP_v3_Colab_Drive_Merged_Full.ipynb_ready.txt` uses hard-coded/hash-derived team strengths, random synthetic form/injury/probability values and props/parlay stubs. Those constructs are suitable only as historical architecture reference, not training, live inference, promotion or settlement evidence.

Do not copy credentials from legacy Drive source. Older project files were previously observed with embedded credentials and overly broad sharing; provider-side revocation/rotation and sharing remediation require independent evidence.

## Promotion gate

Promotion requires chronological walk-forward OOF with in-fold preprocessing, OOF-only calibration, separated holdout, sample sufficiency, Brier improvement, non-inferior log loss, ECE <= 0.01, leakage checks, canonical provenance, schema/model/source checksums, explicit source admissibility, portable parity, signed artifacts and runtime acceptance. Any failing sport remains on the explicit market baseline.

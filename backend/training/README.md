# Google Drive reconstruction evidence

This directory records only evidence reconstructable without trusting leaked credentials or deserializing untrusted pickle/joblib files.

- MLB: feature snapshot/schema, dictionary, experiment summary, settled evaluation, and tracking files are checksummed. Useful evidence, not a canonical production training corpus.
- NFL: player-prop models/scalers and provider XSD schemas are checksummed. Training rows and OOF/settled calibration evidence are missing; joblibs remain quarantined.
- NBA: no sport-specific reconstructable training bundle was found.
- NHL: dedicated data/model/export/log folders are empty; no reconstructable training bundle was found.

The reconstruction utility verifies staged files by SHA-256 and recomputes hard-pick settled metrics. It never loads joblib/pickle files.

Promotion remains governed by Master Protocol v8: chronological walk-forward OOF, in-fold preprocessing, Brier/log-loss/ECE, OOF-only calibration, ECE <= 0.01, separated holdout, leakage audit, provenance/schema/model checksums, and market-baseline comparison.

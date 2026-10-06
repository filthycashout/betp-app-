# NFL archive recovery: executable research path

This command rebuilds a **research-only** corpus from pinned versions of
`nflverse/nfldata/data/games.csv`. It never signs or installs a model. On the
2026-10-06 run, 149 snapshots from the 2020–2025 seasons produced 1,596 rows.
The candidate failed strict promotion and the production baseline was retained.

## Inputs and execution

Use the separately supplied `PhilthyParleys-NFL-research-evidence.tar.xz`
evidence package. It contains `nfl-snapshots.json`, the corresponding `raw/`
files, canonical data, row-level provenance and evaluation reports. Extract
only a trusted copy into a fresh directory. Set `EVIDENCE_DIR` to that directory.
Run these commands from the repository root with Python 3.12:

```bash
python -m pip install numpy==2.3.5 pandas==2.2.3 scikit-learn==1.8.0 joblib==1.5.3
python -m unittest discover -s backend/training -p test_nflverse_archive_backfill.py -v
python backend/training/nflverse_archive_backfill.py \
  --index "$EVIDENCE_DIR/nfl-snapshots.json" \
  --cache "$EVIDENCE_DIR/raw" \
  --output-dir "$EVIDENCE_DIR/rebuilt"
python backend/training/validate_dataset.py \
  --sport NFL --input "$EVIDENCE_DIR/rebuilt/nfl.csv" \
  --source-manifest "$EVIDENCE_DIR/rebuilt/nfl_source_manifest.json" \
  --output "$EVIDENCE_DIR/rebuilt/nfl_schema_validation.json"
python backend/training/strict_promote.py \
  --sport NFL --input "$EVIDENCE_DIR/rebuilt/nfl.csv" \
  --source-manifest "$EVIDENCE_DIR/rebuilt/nfl_source_manifest.json" \
  --output-dir "$EVIDENCE_DIR/rebuilt/training" \
  --features consensus_de_vig_home_probability,home_spread,consensus_total
```

The last command intentionally exits **2** for a rejected candidate. A schema
pass or successful workflow is not promotion approval. If raw files are absent,
add `--fetch-missing` to the importer; it downloads only the pinned upstream URLs
and checks their SHA-256 hashes before use.

## Data rules

- Verify each full archive's checksum and size against the index.
- Interpret kickoff in `America/New_York`, including daylight saving time.
- Select the latest sampled snapshot strictly before kickoff, within seven days,
  with blank score/result fields and valid paired moneylines, spread and total.
- Exclude schedule or team revisions that disagree with the final reference.
- Observe the label from a later archive at least 24 hours after kickoff, with
  internally consistent scores matching the final reference. This is an actual
  sampled archive timestamp, not an invented finish time or a price threshold.
- De-vig the upstream paired moneylines; negate nflverse's home-favoured spread
  to match the runtime convention. The source does not establish an independently
  verified bookmaker-consensus construction for those paired odds.
- Keep this corpus separate from differently keyed existing events until a
  cross-source event mapping can prevent duplicates.

## Verified result

| Check | Observed |
| --- | ---: |
| Rows / OOF rows / final holdout rows | 1,596 / 1,023 / 321 |
| Schema and canonical checksum | PASS_SCHEMA_ONLY |
| Candidate Brier / market Brier | 0.212071438 / 0.211269473 |
| Candidate log loss / market log loss | 0.611067451 / 0.608803910 |
| Candidate ECE / maximum allowed | 0.081047059 / 0.01 |
| Portable numerical parity maximum error | 2.220446049250313e-16 |
| Promotion | CANDIDATE_REJECTED |

Chronological OOF splitting, separated calibration-method selection, in-fold
preprocessing, leakage checks and numerical parity passed the implemented
checks. These are software checks over supplied timestamps, not an independent
audit of upstream publication times or a real Android-device test.

Canonical CSV SHA-256:
`4889736d0bb4e513fc118fefd442b99333c3cbd2501c27503c38eedac22f8949`.

## Holds and next validation

Git committer timestamps are upstream metadata, not independently witnessed
publication receipts; original sportsbook update times are unavailable.
The source manifest explicitly sets `promotion_ready: false` and
`independent_publication_timestamp_verified: false`. Strict promotion now
honours these holds even if numerical metrics pass. Missing hold flags do not
certify provenance: the existing source validation and external review remain
necessary.

The existing Polymarket historical importer also uses a post-start 99%/1% price
crossing as label availability. That is not final-result observation. Rejoin
those rows to independently timed final-result or resolution evidence before
using them for promotion. Do not solve this by lowering the sample/calibration
thresholds or copying final results into earlier timestamps.

Next: establish admissible publication/quote evidence and feature semantics,
then improve features using development and selection-validation data only.
The exposed holdout must not become a tuning target. Any new candidate needs a
predeclared evaluation on an additional untouched chronological window.

Sources: [nflverse data definitions](https://github.com/nflverse/nfldata/blob/master/DATASETS.md)
and [nflreadr data terms](https://nflreadr.nflverse.com/). NFL data retain their
respective owners' terms; an open source package licence does not relicense
every underlying data source.

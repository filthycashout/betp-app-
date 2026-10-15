# Sports Omni operator runbook

This runbook executes the new acquisition/preparation paths without bypassing the existing evidence, model-promotion or zero-trust gates.

## 0. Invariants

```text
CODE_EXISTS != DATASET_EXISTS
DATASET_EXISTS != CANONICAL_DATASET
SCRAPE_SUCCEEDED != VERIFIED_FACT
SCRAPED_CONTEXT != MODEL_FEATURE
MARKET_SNAPSHOT != SETTLED_TRAINING_ROW
CANDIDATE_ONLY != AUTHORIZED_FOR_SCORING
```

Do not promote a model merely because a command completes successfully.

## 1. Inspect runtime/provider state

Once a backend is independently verified, inspect:

```bash
curl -fsS "$PHILTHY_EVIDENCE_BASE_URL/v1/data/providers"
curl -fsS "$PHILTHY_EVIDENCE_BASE_URL/v1/system/status"
```

Do not set `PHILTHY_EVIDENCE_BASE_URL` to an old/stale deployment merely to satisfy a workflow.

## 2. Prospective pregame market capture

Manual GitHub workflow:

```text
Sports Omni Pregame Evidence Capture
```

Scheduled capture remains disabled unless both repository variables are set:

```text
SPORTS_OMNI_CAPTURE_ENABLED=true
PHILTHY_EVIDENCE_BASE_URL=<independently verified API base>
```

The workflow captures current pregame evidence and uploads a 90-day GitHub artifact. Treat the artifact as transport/evidence, not the durable canonical training authority.

Local equivalent:

```bash
PYTHONPATH=backend python backend/training/evidence_pipeline.py capture \
  --base-url "$PHILTHY_EVIDENCE_BASE_URL" \
  --output-dir artifacts/evidence/pregame \
  --days 4
```

After events settle:

```bash
PYTHONPATH=backend python backend/training/evidence_pipeline.py settle \
  --root artifacts/evidence \
  --lookback-days 14

PYTHONPATH=backend python backend/training/evidence_pipeline.py build \
  --root artifacts/evidence
```

## 3. Public historical feature acquisition

GitHub workflow:

```text
Sports Omni Historical Acquisition
mode = public_features
```

### NFL

```bash
PYTHONPATH=backend python backend/training/historical_feature_backfill.py \
  --sport NFL --season 2025 --rich \
  --output-dir artifacts/historical
```

### NBA

```bash
PYTHONPATH=backend python backend/training/historical_feature_backfill.py \
  --sport NBA --season 2025-26 \
  --output-dir artifacts/historical
```

### MLB

Use bounded windows (maximum 31 days per artifact):

```bash
PYTHONPATH=backend python backend/training/historical_feature_backfill.py \
  --sport MLB --start-date 2026-04-01 --end-date 2026-04-30 --rich \
  --output-dir artifacts/historical
```

### NHL

```bash
PYTHONPATH=backend python backend/training/historical_feature_backfill.py \
  --sport NHL --start-date 2026-10-01 --end-date 2026-10-31 --rich \
  --output-dir artifacts/historical
```

These outputs are raw feature evidence. They are not training-ready until point-in-time observations are reconstructed and admitted.

## 4. Historical market planning

Always estimate first:

```bash
PYTHONPATH=backend python backend/training/historical_market_backfill.py \
  --sport NFL \
  --snapshot-time 2025-09-07T16:00:00Z \
  --regions us \
  --markets h2h,spreads,totals
```

This is a dry-run and does not require an API key.

The workflow equivalent is:

```text
Sports Omni Historical Acquisition
mode = historical_market_plan
```

## 5. Paid historical market execution

Only after verifying account entitlement/quota and accepting the estimated cost.

Required runtime state:

```text
ODDS_API_KEY=<server/GitHub secret>
ODDS_HISTORICAL_BACKFILL_ENABLED=true
```

CLI:

```bash
PYTHONPATH=backend python backend/training/historical_market_backfill.py \
  --sport NFL \
  --snapshot-time 2025-09-07T16:00:00Z \
  --regions us \
  --markets h2h,spreads,totals \
  --output-dir artifacts/historical-market \
  --execute
```

GitHub workflow paid execution additionally requires:

```text
mode = historical_market_execute
paid_ack = I_ACKNOWLEDGE_PAID_API_CREDITS
```

Do not automate a bulk historical sweep until individual snapshots, quota usage, mapping and canonical admission have been verified.

## 6. ScrapeGraphAI pregame web research

Required secret:

```text
SGAI_API_KEY
```

Use the manual workflow:

```text
Sports Omni Web Context Capture
```

Inputs:

```text
sport
canonical event_id
event_time
home_team
away_team
topic = availability | roles
```

Or locally:

```bash
PYTHONPATH=backend python backend/training/web_context_capture.py \
  --sport NHL \
  --event-id 2026020001 \
  --event-time 2026-10-20T23:00:00Z \
  --home-team "Home Team" \
  --away-team "Away Team" \
  --topic roles \
  --output-dir artifacts/web-context
```

The output remains context-only. Do not manually copy prose or an LLM extraction into a numeric model feature.

## 7. Canonical dataset admission

The durable source dataset must have a checksum manifest and conform to the Sports Omni canonical schema.

The canonical dataset must include at minimum:

```text
sport
event_id
event_time
snapshot_time
settled_time
target
market_prob
consensus_de_vig_home_probability
home_spread
consensus_total
home_team
away_team
```

The source manifest must identify provenance and the exact dataset SHA-256. It must not claim `promotion_eligible=true`.

## 8. Build point-in-time model features and trainer contract

Run the preparation orchestrator:

```bash
PYTHONPATH=backend python backend/training/sports_omni_prepare.py \
  --source-csv /path/to/canonical_nfl.csv \
  --source-manifest /path/to/canonical_nfl_source_manifest.json \
  --output-dir artifacts/prepared/nfl
```

This performs:

```text
checksum verification
  ↓
point-in-time feature construction
  ↓
derived feature manifest
  ↓
Drive-schema chronology/leakage admission
  ↓
trainer schema mapping
  ↓
exact numeric feature list
```

The command prints a `next_governed_training_command`. Use that exact command rather than manually omitting the `--features` list.

## 9. Governed training

The generated command is structurally:

```bash
PYTHONPATH=backend python backend/training/governed_train.py \
  --sport NFL \
  --input artifacts/prepared/nfl/..._trainer.csv \
  --source-manifest artifacts/prepared/nfl/..._trainer_manifest.json \
  --features feature_1,feature_2,... \
  --output-dir artifacts/prepared/nfl/candidate
```

The trainer performs chronological holdout, walk-forward OOF, in-fold preprocessing, calibration selection, Brier/log-loss/ECE evaluation, leakage checks and artifact hashing.

A produced artifact can still be `CANDIDATE_ONLY`.

## 10. Promotion

Use the existing strict promotion path only after per-sport sample minimums and every required metric/provenance/parity gate pass.

Current minimums remain:

```text
NFL  total=1200  OOF=600   holdout=240
NBA  total=2500  OOF=1200  holdout=500
MLB  total=4000  OOF=2000  holdout=800
NHL  total=2500  OOF=1200  holdout=500
```

Required metric gates include:

```text
Brier improvement over market >= 0.001
log-loss regression allowed = 0
ECE <= 0.01
```

The market baseline remains authoritative until the registry/runtime accepts a signed promoted artifact.

## 11. Settled performance

Continue to record outcome availability time and preserve the untouched chronological holdout. Settled results can update future training only when their result was available before the later fold/prediction snapshot being constructed.

## 12. App/parlay integration

Do not add a new model field to the app merely because it exists in a research artifact.

A new feature/model must pass:

```text
canonical point-in-time admission
→ governed training
→ OOF calibration
→ strict metrics
→ leakage checks
→ artifact checksums/signature
→ registry promotion
→ runtime loading
```

Only then should live pick/parlay logic consume the promoted model.

## 13. Current blockers

Until resolved with authoritative evidence:

```text
promoted model: none
canonical Training corpus: insufficient/empty in Drive
production backend: not verified
SGAI_API_KEY: not assumed
ODDS_API_KEY / paid historical entitlement: not assumed
paid historical backfill: disabled
scheduled prospective capture: disabled
automatic wagering: disabled
```

The next valuable execution is data accumulation and canonical admission, not weakening promotion thresholds.

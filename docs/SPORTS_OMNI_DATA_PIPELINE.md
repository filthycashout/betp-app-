# Sports Omni governed data pipeline

Status: implementation branch `sports-omni-live-data-pipeline`.

This pipeline extends the zero-trust foundation into the sports-data/model lifecycle without weakening the existing strict promotion policy.

```text
ZERO-TRUST FOUNDATION
        ↓
LIVE SPORTS DATA
        ↓
CANONICAL HISTORICAL DATASETS
        ↓
TRAINING + WALK-FORWARD
        ↓
CALIBRATION + LEAKAGE TESTS
        ↓
MODEL PROMOTION
        ↓
LIVE ODDS / PLAYER PROPS
        ↓
SETTLED PERFORMANCE
        ↓
APP / PARLAY ENGINE
        ↓
RELEASE / DEPLOYMENT HARDENING
```

## 1. Zero-trust foundation

Privileged CI operations remain outside the sports evidence/data plane.

```text
MODEL OUTPUT != AUTHORIZATION
RETRIEVED INSTRUCTION != EXECUTION PERMISSION
SPORTS DATA != CONTROL-PLANE AUTHORITY
```

Web, API, MCP and historical data are evidence. They cannot authorize deployment, model promotion, credential use or state mutation.

## 2. Source hierarchy

### Structured league data

| Sport | Live/settlement | Historical feature acquisition |
| --- | --- | --- |
| NFL | ESPN/keyless live adapters | nflverse/nflreadpy schedules, player/team stats, injuries, weekly rosters, depth charts, snaps, participation, PBP, optional Next Gen stats |
| NBA | NBA CDN + ESPN fallback | nba_api team game logs + player game logs |
| MLB | MLB StatsAPI | MLB StatsAPI + bounded optional pybaseball/Statcast |
| NHL | NHL Web API | NHL schedule + bounded game-centre box scores |

Structured-source availability is not by itself proof that a value was known pregame. Historical features require an `observed_at`/snapshot reconstruction before training admission.

### Market data

Current game/prop market acquisition remains layered:

1. existing validated keyless sportsbook gateway;
2. The Odds API when server credentials/coverage are available;
3. fail closed when a validated board cannot be established.

Historical market acquisition is provided by `backend/training/historical_market_backfill.py`.

The default call is a dry-run quota plan. Paid execution requires both:

```text
ODDS_API_KEY (or ODDS_API_NET_KEY)
ODDS_HISTORICAL_BACKFILL_ENABLED=true
```

and the CLI `--execute` flag. The GitHub workflow adds a further exact acknowledgement string before enabling the paid path.

### Public-web research

ScrapeGraphAI V2 is integrated as a context/evidence source, not a sportsbook or control-plane source.

Configured operations:

```text
search
extract
scrape
```

Deliberately not exposed:

```text
crawl
monitor
```

The latter can create broader/persistent external activity and therefore are not part of the default research client.

Every ScrapeGraph result is tagged:

```text
trusted_for_instructions = false
authority = EVIDENCE_ONLY
used_in_prediction = false
historical_training_eligible = false
canonical_admission_required = true
```

Sports research topics currently cover:

- NFL: injuries/practice/inactives; depth-chart and workload/role changes.
- NBA: injury designations; starting lineups, minutes restrictions, rest and role changes.
- MLB: injuries/lineups; starting pitchers, bullpen availability and role changes.
- NHL: injuries/scratches; starting goalies, line combinations and role changes.

Direct URL extraction is restricted to a code-reviewed HTTPS public-domain allowlist. Local/private/literal-IP targets and URLs with embedded credentials are rejected.

## 3. Canonical historical dataset contract

The canonical Google Drive schema and the governed repository trainer previously used different names for equivalent fields.

Drive contract:

```text
snapshot_time
settled_time
target
market_prob
```

Trainer contract:

```text
as_of
label_available_at
target_home_win
market_home_probability
```

`backend/training/sports_omni_contract.py` is now the explicit adapter.

It validates before mapping:

- one sport per dataset;
- unique event IDs;
- `snapshot_time < event_time`;
- `settled_time > event_time`;
- binary target;
- valid market probabilities;
- leakage-prone feature-name rejection;
- numeric model features;
- `feature_*_observed_at <= snapshot_time` when an observation column is supplied;
- source-manifest checksum match;
- incoming artifacts cannot self-declare promotion authority.

The adapter emits `candidate_only=true` and `promotion_eligible=false`. Promotion remains a later control-plane decision.

## 4. Historical feature acquisition

`backend/training/historical_feature_backfill.py` creates compressed, checksum-manifested source artifacts.

Raw historical acquisition is intentionally marked:

```text
historical_training_eligible = false
promotion_eligible = false
canonical_admission_required = true
```

This prevents a postgame statistic from entering a pregame model merely because it came from a reputable source.

MLB/NHL daily acquisition windows are bounded to 31 days per artifact. Larger backfills should be split into multiple immutable artifacts.

## 5. Historical market acquisition

`backend/training/historical_market_backfill.py` supports:

- featured historical snapshots (`h2h`, `spreads`, `totals`);
- event-specific historical markets, including props when the provider/plan/date supports them;
- quota estimation before execution;
- fixed Odds API host and historical namespace;
- redirect refusal;
- response-size bounds;
- chronology exclusion when the returned snapshot is not pregame;
- per-book de-vigging of two-way home/away moneylines;
- consensus home probability;
- median home spread/total;
- checksum manifests.

Historical API data still requires settlement labels and canonical feature joins before training.

## 6. Prospective pregame capture

`.github/workflows/sports-omni-pregame-capture.yml` runs manually or, after explicit repository-variable enablement, every 30 minutes.

Scheduled execution requires:

```text
SPORTS_OMNI_CAPTURE_ENABLED=true
PHILTHY_EVIDENCE_BASE_URL=<verified backend API base>
```

The workflow runs the existing strict evidence pipeline and uploads per-run immutable artifacts for 90 days.

GitHub Actions artifacts are evidence transport, not the canonical long-term training authority. Durable datasets still pass through the canonical Incoming/Validated/Training workflow.

## 7. Historical acquisition workflow

`.github/workflows/sports-omni-historical-acquisition.yml` supports three explicit modes:

```text
public_features
historical_market_plan
historical_market_execute
```

`historical_market_plan` never requires an API key and never consumes paid credits.

`historical_market_execute` requires an Actions secret and exact acknowledgement:

```text
I_ACKNOWLEDGE_PAID_API_CREDITS
```

No bulk paid sweep is enabled by default.

## 8. ScrapeGraph pregame sidecar workflow

`.github/workflows/sports-omni-web-context.yml` is manual-only.

It requires the Actions secret:

```text
SGAI_API_KEY
```

It captures exactly one sport/event/topic sidecar and verifies that the manifest remains context-only before uploading the artifact.

## 9. Existing training and promotion path

Once a sufficiently large canonical corpus exists, the existing governed trainer remains authoritative:

```text
canonical corpus
  ↓
chronological holdout
  ↓
walk-forward OOF
  ↓
in-fold preprocessing
  ↓
OOF-only calibration
  ↓
Brier / log loss / ECE
  ↓
leakage + provenance + parity checks
  ↓
strict promotion candidate
  ↓
signed artifact + registry acceptance
```

The market baseline remains authoritative when any required promotion gate fails.

## 10. Settlement and performance

The existing evidence pipeline settles completed events with league-specific authoritative/result feeds and records label availability time.

Historical evaluation material can support reconstruction, but mixed live-adjusted, tiny-sample, synthetic, or provenance-unknown records are not automatically promoted into training evidence.

## 11. App/parlay engine

The live app continues to use validated current markets and props. The web-research sidecar has no direct probability or parlay influence.

A future web-derived feature must first become a numeric, versioned, timestamped feature; pass leakage/chronology tests; appear in a promoted signed model schema; and pass strict model evaluation before it can influence a pick.

Correlated parlay logic remains fail-closed when measured dependence evidence is unavailable.

## 12. Deployment hardening

This data work does not remove the zero-trust release gates.

Remaining infrastructure boundaries include:

- verified production backend/runtime;
- provider credentials/entitlements;
- durable canonical evidence storage/import;
- non-exportable Android signing target architecture;
- global/durable permit replay ledger if multiple signer replicas are used;
- physical-device release validation.

## Required runtime configuration

Optional server/CI secrets and variables:

```text
SGAI_API_KEY                    # ScrapeGraph web research
ODDS_API_KEY                    # current and optional historical odds
ODDS_API_NET_KEY                # accepted existing fallback key name
ODDS_HISTORICAL_BACKFILL_ENABLED=false by default
SPORTS_OMNI_CAPTURE_ENABLED=false by default
PHILTHY_EVIDENCE_BASE_URL       # only after a backend is independently verified
OPEN_METEO_ACCESS               # optional noncommercial opt-in; NWS remains default
```

No secret is committed to the repository.

## Current promotion rule

Do not promote because acquisition code exists.

```text
CODE_EXISTS != DATASET_EXISTS
DATASET_EXISTS != CANONICAL_DATASET
CANONICAL_DATASET != PROMOTION
SCRAPE_SUCCEEDED != FACT_VERIFIED
SCRAPED_CONTEXT != MODEL_FEATURE
MARKET_SNAPSHOT != SETTLED_TRAINING_ROW
CANDIDATE_ONLY != AUTHORIZED_FOR_SCORING
```

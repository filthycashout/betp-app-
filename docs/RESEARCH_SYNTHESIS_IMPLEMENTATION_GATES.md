# Research synthesis to implementation gates

## Source status
This document maps the user-provided synthesis of *Relentless*, *Building the Elite Athlete*, and *The Logic of Sports Betting* to the existing five-sport architecture. It is a **secondary synthesis**, not a fresh line-by-line verification of the original books. Do not attribute specific quantitative claims to those books without checking the source files and passages.

| Research layer | What it contributes | What it cannot establish |
|---|---|---|
| Execution discipline (*Relentless*) | preparation, accountability, documented failure analysis, iterative improvement | predictive accuracy or betting edge |
| Performance science (*Building the Elite Athlete*) | hypotheses about workload, opportunity, injuries, context, technique and measurement | verified current player health or useful features without out-of-sample tests |
| Market mathematics (*The Logic of Sports Betting*) | implied probability, vig, EV, line comparison, correlation, settlement | true probabilities, executable prices, profitability |

## Mapping onto existing code
Preserve NFL, NBA, MLB, NHL and UFC as separate sport contracts. Reuse existing `backend/sports_ai/`, `backend/training/`, `backend/tests/`, the odds adapters and the chat briefing path; do not create parallel calculation engines before auditing their implementations.

### Proposed implementation checkpoints
1. **Math audit**: locate existing American odds, no-vig, payout, push/void, EV and parlay functions. Record implementation paths and verify with deterministic fixtures. For American price +150, break-even probability is 100/250 = 0.4; for -110 it is 110/210. Two -110 sides have overround 2*(110/210)-1 = 0.047619. Do not equate overround with hold.
2. **Point-in-time admission**: for each event and market, retain source identity, bookmaker, exact line, settlement rules, quote time, fetched time and decision cutoff. Reject evidence first observed after the decision cutoff for historical replays.
3. **NBA pilot**: freeze one outcome target and a chronological train/validation/test split. Compare a market-based reference, a simple historical baseline, and one context-aware candidate using Brier score, log loss and calibration. No promotion based on a single favorable result.
4. **Joint probability**: independently verify 6-leg and 12-leg fair-coin reference cases (1/64 and 1/4096). For dependent legs require a validated joint simulator or mark the probability unavailable; never multiply marginals by default.
5. **Sport expansion**: maintain existing NFL, NBA, MLB and NHL regression tests; UFC stays provider-unavailable and prediction-ineligible until authorized live coverage, settlement history, point-in-time backtests and calibration gates pass.
6. **Chat reporting**: report event ID, source/quote timestamps, price, model version, uncertainty, baseline comparison and section-level unavailability. Do not turn an unavailable section into a synthetic pick.

## Study-and-Apply experiment log template
- Evidence: precise code path, source observation, fixture and timestamp.
- Hypothesis: falsifiable proposed improvement over a frozen baseline.
- Smallest experiment: one bounded change and one chronological held-out evaluation.
- Result: raw metrics, sample size, intervals, errors and limitations.
- Update: keep, revert, or mark inconclusive.
- Regression check: rerun affected sport, evidence and production contract tests.

## Acceptance criteria
- Existing four-sport outputs do not regress.
- Odds conversion and payout tests cover positive/negative prices, zero/invalid prices, pushes/voids and settlement edge cases.
- Historical evaluation never reads records unavailable at its cutoff.
- Every probability is calibrated or clearly labeled baseline/unvalidated.
- Dependent parlay outcomes are not treated as independent.
- UFC has no fabricated live picks while provider readiness is unverified.
- CI results are recorded per commit; green checks are not a substitute for model validation.
- Automatic wagering remains disabled.

## Status
Research-to-engineering mapping only. No source-book reinspection, new model, new live provider, backtest result or verified profitable edge is asserted by this document.

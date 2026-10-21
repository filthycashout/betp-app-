# Unified Sports AI Core

The Powerhouse is one analytical engine inside the existing backend, not a second backend.

## Locked invariants

- Production remains Floot-only. This package contains no Render routing.
- NFL, NBA, MLB, NHL, and UFC share one decision core while sport-specific ingestion/features remain separate. UFC uses a fight/event adapter; it is not forced through team-league schedule or player-prop assumptions.
- Point-in-time data requires `observed_at <= prediction_time < event_time`.
- Existing governed model promotion remains fail-closed; unpromoted model output cannot influence final probability.
- Market-baseline operation remains available while trained-model promotion is pending.
- A market consensus is not automatically labeled sharp. Sharp-vs-soft strategies must carry explicit verified sharp-anchor provenance and fail closed otherwise.
- A sharp anchor and the compared soft price must come from different bookmakers.
- Sharp anchors require provider timestamps; a local fetch-observed timestamp alone cannot promote a quote to sharp evidence.
- Sport-specific role context is evidence only until a promoted artifact explicitly declares compatible features in its signed schema.
- Correlated parlays fail closed when measured dependence evidence is unavailable.
- No automatic wagering execution is introduced.
- Secrets remain deployment environment variables; no `secrets.env` is committed.

## Decision flow

`point-in-time data -> normalized market anchor -> optional verified sharp provenance -> optional promoted model -> compare to independent soft-book price -> edge/EV -> freshness/context/dependence gates -> recommendation -> settlement/CLV tracking`

## Sharp anchor contract

The default trusted sharp-book key is `pinnacle`, configurable with `SPORTS_AI_SHARP_BOOK_KEYS`. `SPORTS_AI_SHARP_MAX_AGE_SECONDS` controls the maximum provider-timestamp age and defaults to 180 seconds.

The live path first looks for a qualifying sharp quote in the already-fetched event pool. If none is present and Pinnacle is enabled, it may query The Odds API v4 with `bookmakers=pinnacle` through the backend's existing credential-rotation and request wrappers. The API credential is never emitted in decision output.

A verified anchor must satisfy all of the following:

1. Match the same teams and event start window.
2. Come from a configured sharp-book key.
3. Contain exactly two moneyline outcomes for the selected game side and its opponent.
4. Carry a bookmaker/market provider timestamp within the configured age limit.
5. Be de-vigged from both sides of that same bookmaker market.
6. Be excluded from the soft-price pool used for the EV comparison.

If any requirement fails, the decision remains fail-closed with sharp evidence unavailable.

## NBA role context

`backend/sports_ai/sports/nba/role.py` provides a chronological role/opportunity context layer. It computes rolling player minutes and an estimated possession-usage rate from completed box scores strictly before the target tip. NBA CDN schedule/liveData is primary; ESPN Site API is an explicit fallback for environments where the NBA CDN blocks the server IP.

The role output is **context only**: `model_influence=false`. It must not change probabilities, picks, EV, or Kelly sizing until a signed promoted artifact declares compatible role features and passes the existing chronology/calibration/leakage/promotion gates. Floot production stores the corresponding pregame role snapshot as immutable evidence.

## Entrypoint

`backend/main.py` is the single analytics CLI entrypoint for both normalized offline candidates and the governed live backend.

Examples:

```sh
PYTHONPATH=backend python backend/main.py --sport MLB --input candidates.json
PYTHONPATH=backend python backend/main.py --input four-sport-candidates.json
PYTHONPATH=backend python backend/main.py --live --sport NFL
PYTHONPATH=backend python backend/main.py --live
```

The migration remains incremental: existing team-sport FastAPI contracts stay intact while live analytics, tracking, sport-specific role models, simulations, and settlement logic move behind the unified interfaces only after their tests and evidence gates pass. The staged UFC endpoint is `GET /v1/ufc/events?date=YYYY-MM-DD`; the mobile scoreboard calls it only for the UFC tab. This source change is not a production deployment claim.


## UFC / MMA adapter

`backend/sports_ai/ingestion/ufc.py` normalizes The Odds API v4's `mma_mixed_martial_arts` event feed into the shared candidate contract. UFC is event-driven and the adapter uses fighter identities and fight-winner (`h2h`) markets only; it does not invent fighter props or team-league statistics.

The adapter uses the existing `_odds_key()` credential-rotation gate and the backend's sanitized `_json()` wrapper. If the credential is absent or rotation is not confirmed, the live CLI reports `PROVIDER_UNAVAILABLE`. Quotes must have valid provider timestamps and pass the shared market validation. UFC remains non-actionable unless a separate, verified sharp anchor from a different bookmaker is available; a generic consensus market is not silently relabeled as sharp. Automatic wagering remains disabled.

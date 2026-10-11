# Unified Sports AI Core

The Powerhouse is one analytical engine inside the existing backend, not a second backend.

## Locked invariants

- Production remains Floot-only. This package contains no Render routing.
- NFL, NBA, MLB, and NHL share one decision core while sport-specific ingestion/features remain separate.
- Point-in-time data requires `observed_at <= prediction_time < event_time`.
- Existing governed model promotion remains fail-closed; unpromoted model output cannot influence final probability.
- Market-baseline operation remains available while trained-model promotion is pending.
- Correlated parlays fail closed when measured dependence evidence is unavailable.
- No automatic wagering execution is introduced.
- Secrets remain deployment environment variables; no `secrets.env` is committed.

## Decision flow

`point-in-time data -> normalized candidate -> sharp/no-vig market probability -> optional promoted model blend -> edge/EV -> freshness/context/dependence gates -> recommendation -> settlement/CLV tracking`

The current migration deliberately starts with the pure decision layer so existing live provider routing and FastAPI contracts remain unchanged. Ingestion, role models, simulations, persistence, CLV settlement, and API adapters can migrate behind this interface in later commits without a big-bang rewrite.

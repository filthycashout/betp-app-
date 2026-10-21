# Integration map

The existing backend is authoritative for production service and evidence gates; this directory must not duplicate or bypass providers.

| Need | Existing area | Rule |
|---|---|---|
| Live league schedules | `backend/free_odds_gateway.py` and live routes | Reuse verified event IDs; never hardcode a daily slate. |
| Market quotes | `backend/odds_api_net.py`, `backend/sports_ai/ingestion/odds.py` | League stats feeds are not sportsbook price feeds. Do not claim all odds/props are keyless. |
| Orchestration | `backend/sports_ai/orchestrator.py` | Preserve existing API and model/evidence gates. |
| Calibration | `backend/training/prop_calibration.py` | Candidate calibration is not promotion; use chronological holdouts. |
| Historical evidence | `backend/training/sports_omni_prepare.py`, `sports_omni_contract.py` | Preserve pregame snapshots, settled labels and provenance. |
| Tests/CI | `backend/tests/test_sports_omni_contract.py`, existing Sports Omni workflows | Do not suppress failed provider probes. |
| Mobile | `mobile_dashboard/`, `lib/` | Keep phone-first usability; APK is not required for this workspace. |

## Order

1. Compare canonical Drive notebooks with repository modules.
2. Reuse equivalent core logic rather than copy it.
3. Wire providers through existing source contracts; preserve provider timestamps separately from local fetch times.
4. Backfill settled data, verify chronology/provenance, then benchmark per sport.
5. Promote one sport/market only after gates pass.

## Security

Historical audit reports legacy credential material in older artifacts. Rotate/revoke exposed secrets, remove broad sharing, and keep credentials in deployment secret storage. This branch contains placeholders only.

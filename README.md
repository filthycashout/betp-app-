# PhilthyParleys

PhilthyParleys is the renamed PhilthySports Android client for NFL, NBA, MLB and NHL.
Version **1.6.6+29** uses the supplied FILTHY PICKZ raccoon artwork for the launcher, splash/loading treatment and in-app header while preserving package ID `com.philthysports.philthysports` and the pinned release signing certificate for compatible updates.

- Search team, matchup, date or sport; view today's NFL/NBA/MLB/NHL games; review moneyline/spread/total markets and player props; open a fixed Best 12 board (4 game props, 4 player props, 4 multisport-mix selections); and review Best 1 / Best 2 three-leg cards for each sport when sufficient verified markets exist.
- The client validates a candidate HTTPS backend before saving it, checks service identity, and retries temporary gateway/network failures with a finite budget.
- The primary multi-book odds provider remains server-side and requires legitimately reissued credentials for that provider. The backend also has a no-key, read-only public sportsbook fallback that is live-canary tested for NFL, NBA, MLB and NHL game markets and player props; it fails closed when an event, timestamp or market cannot be validated.
- Prop quotes must be timestamped and recent. Provider timestamps and local fresh-fetch observation timestamps are kept distinct. Recommendations require complementary prices from the same bookmaker and line. Unpaired outcomes show raw implied prices without a recommendation.
- Game markets retain actual offered lines. Unknown provider quote age is not re-stamped as current, and ambiguous doubleheader mappings are rejected.
- Training retains prior settled labels, records result availability, verifies capture hashes and excludes unavailable results from chronological folds and holdout training.
- No trained model replaces the market baseline until strict per-sport evaluation and signature checks pass. A baseline needs usable current market data; it does not guarantee prices exist for every game.

Production backend: https://philthyparleys.floot.app/_api

## Keyless live-data gateway

PhilthyParleys proxies league live data through its own backend so the Android APK does not need league API keys for schedules, scores, box scores or play-by-play.

| Sport | Keyless upstream | Local PhilthyParleys routes |
| --- | --- | --- |
| NFL | ESPN Site API | `GET /v1/live/NFL/scoreboard`, `GET /v1/live/NFL/game/{event_id}` |
| NBA | NBA CDN LiveData, ESPN fallback | `GET /v1/live/NBA/scoreboard`, `GET /v1/live/NBA/game/{event_id}` |
| MLB | MLB StatsAPI | `GET /v1/live/MLB/scoreboard`, `GET /v1/live/MLB/game/{game_pk}` |
| NHL | NHL Web API | `GET /v1/live/NHL/scoreboard`, `GET /v1/live/NHL/game/{game_id}` |

`GET /v1/live/sources` exposes the active source contract and reports that these live league feeds do not require credentials. GitHub-backed reference implementations used during integration include `sportsdataverse/sportsdataverse-js`, `swar/nba_api`, `toddrob99/MLB-StatsAPI`, `coreyjs/nhl-api-py`, and `Zmalski/NHL-API-Reference`.

These routes replace credentials for league live data only. Sportsbook moneylines, spreads, totals and player-prop quotes remain a separate provider contract and are not presented as keyless unless a verifiable keyless source exists.

## Validation

```sh
pip install -r backend/requirements.txt -r backend/requirements-validation.txt
PYTHONPATH=backend pytest -q backend/tests
PYTHONPATH=backend python backend/selftest.py
flutter analyze
flutter test
```

Full CI builds `PhilthyParleys.apk`, verifies the pinned certificate, and runs the exact signed APK on an Android 35 emulator. Emulator installation/launch is not physical-device end-to-end evidence.

On a connected physical Android device, use:

```sh
python ci/device_smoke.py --apk PhilthyParleys.apk --output device-report --serial YOUR_ADB_SERIAL --require-physical
flutter test integration_test/app_test.dart -d YOUR_ADB_SERIAL
```

For a phone-only Termux/Wireless-ADB path, use `ci/run_phone_only_physical_proof.sh` after Wireless Debugging is paired. Do not commit pairing codes, IMEI/EID, phone numbers, MAC addresses or full device identifiers.

The first command preserves app data, verifies installation/process survival and collects a screenshot/log/report. The integration test additionally exercises UI presence and public health/model/prop contracts. Manual acceptance must still cover Settings save/failure recovery, all sports, the 9-pick selected-game board, Best 12 picks, both three-leg cards per sport, offline recovery, and an update from the previous installed release. Never uninstall to bypass a signing mismatch.

Production readiness remains unproven: exposed legacy credential revocation, broad Drive permission removal, fresh live provider canaries, sufficient governed sport datasets, promoted models, physical-device acceptance, operational alerting/retention and rollback evidence are still required.

## Keyless sportsbook fallback

When the primary odds credential is unavailable or not rotation-confirmed, the backend attempts read-only public sportsbook feeds and validates them by team identity, start time, pregame state and freshness. The release live canary verifies current/upcoming NFL, NBA, MLB and NHL game markets plus mapped player-prop coverage. Empty, blocked, stale, ambiguous or unmatched responses are rejected rather than converted into synthetic lines.

The mobile release no longer displays 7/10/14-leg cards. It shows two three-leg cards per sport and preserves actual sportsbook evidence on every displayed leg. Each scheduled matchup also exposes nine fixed pick slots: moneyline, point spread, over/under, three roster-verified player props for the home side and three for the away side. Missing evidence remains visibly unavailable, and no joint parlay hit probability is invented without a validated dependence model.

## Android bundled dashboard

The Android app bundles the same React dashboard as the PhilthySports Site. It opens from local assets without a Sites login. Android performs allowlisted HTTPS GET requests for the score feeds and the configured PhilthyParleys production backend; no provider secret or arbitrary network proxy is exposed. The stable package/signing identity is preserved.

Mobile UI source is in `mobile_dashboard/`; `npm install` followed by `npm run build` regenerates `assets/dashboard/`. The web UI and its v8 evidence filters are preserved. The CI APK smoke checks require the actual dashboard to render, fresh feeds for all four sports, and Settings navigation. Physical-device and live-prop/model-promotion checks remain separate.

## MCP skill set and project evidence

The governed production MCP is available at:

`https://philthysports-mcp-v1.onrender.com/mcp`

The primary MCP skill and its supporting skills/configuration live under:

`integrations/philthysports-mcp-skills/`

Validate the complete skill set with:

```sh
python integrations/philthysports-mcp-skills/validate_skillset.py
```

The consolidated non-secret project evidence, historical gate findings, NFL archive research results, release-proof boundaries, provider credential rules and physical-device acceptance requirements are documented in:

`docs/PROJECT_EVIDENCE_CONSOLIDATION_2026-10-07.md`

Historical evidence is preserved as provenance, not automatically treated as current status. Current workflow results, deployment observations, provider canaries and model/device evidence take precedence.

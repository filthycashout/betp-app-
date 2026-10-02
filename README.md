# PhilthyParleys

PhilthyParleys is the renamed PhilthySports Android client for NFL, NBA, MLB and NHL.
Version **1.5.0+17** preserves package ID `com.philthysports.philthysports` and the pinned release signing certificate for compatible updates.

- Search matchups, review available moneyline/spread/total markets and player props, and build 7/10/14-leg manual-review parlay cards when sufficient eligible markets exist.
- The client validates a candidate HTTPS backend before saving it, checks service identity, and retries temporary gateway/network failures with a finite budget.
- Provider credentials are server-side only. Live props require legitimately reissued credentials and provider-side revocation evidence. Setting a flag or receiving HTTP 200 from `/health` does not establish live provider validation.
- Prop quotes must be timestamped and recent. Recommendations require complementary prices from the same bookmaker and line. Unpaired outcomes show raw implied prices without a recommendation.
- Game markets retain actual offered lines. Unknown provider quote age is not re-stamped as current, and ambiguous doubleheader mappings are rejected.
- Training retains prior settled labels, records result availability, verifies capture hashes and excludes unavailable results from chronological folds and holdout training.
- No trained model replaces the market baseline until strict per-sport evaluation and signature checks pass. A baseline needs usable current market data; it does not guarantee prices exist for every game.

Backend: https://philthysports-powerhouse-v8.onrender.com


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

The first command preserves app data, verifies installation/process survival and collects a screenshot/log/report. The integration test additionally exercises UI presence and public health/model/prop contracts. Manual acceptance must still cover Settings save/failure recovery, all sports, selected-game props, 7/10/14-leg cards, offline recovery, and an update from the previous installed release. Never uninstall to bypass a signing mismatch.

Production readiness remains unproven: exposed legacy credential revocation, broad Drive permission removal, fresh live provider canaries, sufficient governed sport datasets, promoted models, physical-device acceptance, operational alerting/retention and rollback evidence are still required.

# PhilthySports runtime backend

Lean runtime for the Flutter client. It serves keyless schedules for NFL/NBA/MLB/NHL, an explicit four-sport market-baseline model registry, and fresh sportsbook odds/player props when a rotated server-side `ODDS_API_KEY` is configured.

Secrets must never be committed. Live sportsbook odds/props are disabled without a server-side credential. Execution is analytics/manual-review only.

## Public API replacements — backend 1.5.5

The `public-apis/public-apis` directory was cloned and reviewed at commit
`dfb5690f7fdd4073a54290f499a76c71cd9e5ba8`. It is a catalogue, not an SDK or
credential bundle. See `public_api_review.json` for the scoped decisions and
provider documentation. No code or credentials were imported from arbitrary
listed providers.

- `GET /v1/data/providers` publishes the replacement inventory and non-secret
  runtime readiness. All four existing keyless score/schedule adapters remain.
- `GET /v1/context/weather?lat=32.7073&lon=-117.1566` uses the US National Weather
  Service with a descriptive User-Agent, bounded cache and metric units. `at`
  accepts an ISO timestamp with a timezone. Past events, stale forecasts and
  missing coverage return explicit unavailable states, not reconstructed weather.
- MLB schedules now retain official venue coordinates and roof metadata.
  Game detail adds an NWS forecast only for a confirmed open-air venue and a
  future game covered by the forecast. Existing APKs show its context-only note
  in the existing game-detail reasons; their dashboard layout is unchanged.
- `GET /v1/context/weather?...&provider=open_meteo` is an optional global
  non-commercial adapter. It stays disabled unless the operator explicitly sets
  `OPEN_METEO_ACCESS=noncommercial`. The public service's commercial-use terms
  differ; this implementation never assumes a free commercial entitlement or
  silently switches to a paid service. Open-Meteo attribution is returned.
- `GET /v1/context/news/{NFL|NBA|MLB|NHL}?limit=5` returns dated ESPN headlines and
  article links, with seven-day freshness filtering. Headlines are context,
  not a verified injury feed, and are not model inputs. The current APK does not
  yet have a news view; this route is available to API clients.

The new context is **not used to adjust probabilities or train models**. Original
retrieval times survive cache hits. Provider errors never return raw URLs or
credential material. Current forecasts are not retroactively treated as pregame
training data. Existing model, odds, signing and credential-rotation gates remain.

APILayer Weatherstack/Mediastack and BALLDONTLIE still require provider keys.
FanLine's free snapshot lacks the runner labels, handicap and scheduled event
metadata required by our market validation; it was not added to prediction inputs.
The separate NBA full-season schedule CDN endpoint returned HTTP 403 during this
review and was not added. Existing NBA live adapters remain unchanged.

The Odds API remains an optional primary odds/props source. Existing keyless
DraftKings/Bovada routes retain per-event coverage limitations; no full four-sport
prop coverage is claimed. Revoke previously exposed legacy keys even if the
replacement means they are no longer used. Do not rotate Android signing material
as part of this data-provider change.

Verification:

```sh
PYTHONPATH=backend pytest -q backend/tests
PYTHONPATH=backend python backend/validate_public_context.py \
  --output /tmp/public-context-evidence.json --check-noncommercial-open-meteo
```

The live check uses real, read-only provider requests; its non-commercial flag
only enables Open-Meteo for the validation process. Evidence in `backend/evidence/`
states whether it concerns local routes or a deployed service. HTTP success does
not demonstrate trained-model promotion or complete odds coverage.

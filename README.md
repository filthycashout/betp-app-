# PhilthySports Android Build

PhilthySports is a Flutter Android client for the NFL, NBA, MLB, and NHL matchup-search backend.

## Security and freshness rules

- Provider credentials remain server-side. Do not add them to Flutter, Android resources, assets, or GitHub.
- The client stores only the backend URL locally.
- Schedules, odds, props, and predictions are fetched fresh from the Python API.
- API failures do not echo raw backend/provider response bodies into the UI.
- The shield icon reads backend health, production-gate status, and model-governance status so a launchable APK is never confused with a production-cleared system.
- Portable on-device model activation remains disabled until promoted artifacts, preprocessing contracts, parity tests, and checksummed/signed manifests exist.

Current client version: **1.2.3+6**.

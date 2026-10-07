# PhilthySports / PhilthyParleys merge manifest — 2026-10-07

This manifest records the final consolidation pass that moved the useful, safe project material into `filthycashout/betp-app-` `main`.

## Incorporated on `main`

- Current Flutter/Android source and bundled dashboard.
- FastAPI/backend runtime, evidence, provider-canary, operations and training code.
- NFL archive research importer, tests, research documentation, and source-quarantine promotion guard.
- Odds API historical-backfill/probe path and historical-source helpers.
- Physical-device ADB smoke runner and phone-only Termux/Wireless-ADB runner.
- Exact signed-APK domain audit and pinned external-analysis inputs.
- Requested external-source clone/audit workflows and pinned upstream manifest.
- Deployed PhilthySports MCP implementation plus the seven-skill MCP set.
- Direct MCP connection config and core skill validator.
- Consolidated project evidence and historical release-evidence summaries.
- CI workflows for backend, Android, MCP, secret scanning, provider proof, historical access, external source audits and production guards.

## Consolidated historical source material

The project evidence summary incorporates the non-secret conclusions and requirements from the prior Master Protocol, security/data audit, v6 production-gate report, v8/v8.1 inventories, credential/validation plan, execution-and-validation report, and historical Android verification reports.

These documents are treated as dated evidence. Current source/workflow/deployment evidence takes precedence over stale status text.

## Intentionally not copied into public git

The following are represented only by safe metadata/hashes or remain in their original controlled location:

- API keys, tokens, passwords, service-account private keys, signing private keys and other credentials.
- Raw legacy `.env`, `Keys*.txt`, credential JSON or private-key files.
- Private Google Drive identifiers/links that are not needed for public reproducibility.
- Generated APK, ZIP and evidence-package binaries already reproducible from CI or held in the file library.
- Legacy `.joblib`/serialized models lacking a fully reproducible feature/training/provenance contract.
- Synthetic/random notebook values as canonical training evidence.
- Device identifiers, IMEI/EID, phone number, MAC addresses, ADB pairing codes or other phone-private fields.

This exclusion is deliberate: “merge everything” means preserve all useful project knowledge and executable work, not publish secrets or unsafe binary evidence into a public repository.

## Superseded branch / PR cleanup

Draft PR #5 (`research/nfl-archive-evidence-20261006`) was closed as superseded rather than force-merged. Its useful changes are already present on `main` through the current NFL archive importer/docs/tests and strict source-quarantine guard. The rejected NFL research model remains unpromoted.

## Truth-state boundaries retained

The repository must continue to distinguish these gates independently:

- source/tests/CI;
- deployed backend health;
- credentialed live-provider proof;
- credential revocation proof;
- immutable/admissible historical data;
- per-sport strict model promotion;
- APK build/signature/static audit;
- emulator acceptance;
- physical-device acceptance;
- upgrade-in-place acceptance;
- alerting/retention/restore/rollback drills.

No successful subset may be relabeled as overall production readiness.

## Primary references now in repository

- `README.md`
- `docs/PROJECT_EVIDENCE_CONSOLIDATION_2026-10-07.md`
- `docs/RELEASE_EVIDENCE_HISTORY.md`
- `backend/training/NFL_ARCHIVE_RESEARCH.md`
- `backend/training/policy.json`
- `backend/training/strict_promote.py`
- `integrations/upstreams.lock.json`
- `integrations/philthysports-mcp-skills/`
- `ci/device_smoke.py`
- `ci/run_physical_device_proof.sh`
- `ci/run_phone_only_physical_proof.sh`

## Validation expectation

After this consolidation, use the latest commit's own GitHub Actions results. Do not inherit a green Android/MCP/secret-scan result from an earlier commit merely because the changes are documentation-only.

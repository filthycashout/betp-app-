# Final Mainline Integration Audit

**Repository:** `filthycashout/betp-app-`  
**Audit date:** 2026-10-21  
**Audit scope:** current `main`, recent integration commits, GitHub Actions results, and the production endpoint probe.

## Executive result

The primary sports-intelligence integration is in `main`. The source integration is **not the same as a production release**: the latest production probe reached the host but returned HTTP 404 for both newly integrated endpoints. Keep the release status blocked until Floot publishes the matching source and both endpoints return valid JSON.

## Verified mainline commits

| Commit | Integrated work |
| --- | --- |
| `68977ea48388a4454d008143185213049bc701b1` | Zero-trust control plane and MCP provenance |
| `3f987951921167a5808d03ed28dbc5143eaf751a` | UFC as fifth sport; governed fight-winner endpoint and staged release |
| `aa0b85735591d1880d013aee44319a80ccf3d157` | Sports-omni data adapters and point-in-time training pipeline |
| `51960654e951a92a56420726112cee33ee96fbb2` | Read-only Chat Picks briefing endpoint and contract documentation |
| `05e78edb28b3bb16619e3ffab435591974615283` | FreeOddsGateway caching/latency hardening, durable snapshot status, provenance-gated training, tests and production guard |

The FreeOddsGateway changes preserve the current `PRODUCTION_BASE_URL` contract and add market snapshot provenance to canonical training. The original self-writing latency optimizer workflow and one-shot source patcher were deliberately excluded from the merged implementation.

## Verification evidence

For the FreeOddsGateway PR head `517bad3cd811b8011b909577503a6e39b4da4229`, GitHub Actions reported success for:

- Backend CI
- Secret Scan
- Unified Evidence CI
- Floot Production Contract Guard
- PhilthyParleys Completeness Contract
- New API Production Probe workflow

**Important distinction:** the production probe workflow is intentionally non-blocking so a missing deployment is reported as a warning rather than a CI outage. Its logs on 2026-10-21 recorded:

- UFC endpoint: HTTP 404
- Chat Picks endpoint: HTTP 404

Therefore the workflow's green status does **not** mean the live endpoints passed. Deployment remains unverified and blocked.

## Mainline API and product boundaries

- UFC is a governed fight-winner feed. It is not a player-props feed; unsupported data must remain unavailable rather than be fabricated.
- Chat Picks is read-only. It aggregates existing today, Best 12, and parlay sections, preserving unavailable states and evidence metadata.
- FreeOddsGateway is read-only. Provider failures and timeouts reduce verified coverage; they must not create substitute lines.
- Automatic wagering remains disabled. Model promotion and betting recommendations remain subject to their evidence, freshness, and manual-review gates.
- Sports-omni historical acquisition is opt-in where it may consume paid provider quota.

## Branch triage

Do not merge stale branches wholesale just to make the branch list empty.

- `integration/zero-trust-control-plane-main`: the principal zero-trust control-plane, provenance, MCP, test, and documentation files were verified byte-identical to `main`. Its remaining differences include an older security configuration; the current mainline host detection is retained.
- `integration/sports-omni-main`: key current data-source, web-research, historical market backfill, point-in-time feature, contract, test, and runbook files were verified byte-identical to `main`. The branch is behind main and should not be merged as a whole.
- `integration/drive-evidence-20261006`: compare reported 146 commits behind and 1 ahead. It contains optional NFL archive research/backfill and external-repository audit material; review those separately if that historical research capability is wanted.
- `integration/external-sports-repos`: compare reported 179 commits behind and 8 ahead. It includes external repository cloning/provider patch automation and is not safe to merge wholesale without a fresh review.
- `integration/upstreams-3-27-20261010`: compare reported 29 commits behind and 1 ahead. Its upstream lock/clone tooling is auxiliary to the production sports API and is not part of this release.

The original FreeOddsGateway PR #16 was closed as superseded by PR #56. PR #49 and #50 remain preserved as historical, superseded PRs; their reviewed work was ported to the current mainline through newer PRs. PR #55 and #56 are merged.

## Final release acceptance checklist

1. Publish/update the existing Floot project so the deployed source matches GitHub `main`.
2. Re-run the `New API Production Probe` workflow.
3. Confirm `/_api/v1/ufc/events?date=YYYY-MM-DD` returns HTTP 200 and the expected UFC JSON contract.
4. Confirm `/_api/v1/chat/picks` returns HTTP 200 and the expected briefing JSON contract.
5. Confirm provider/credential gates and durable snapshot storage are healthy in the deployed environment. Never expose API keys in chat, logs, or source control.
6. Run the deployment's backend smoke tests and mobile dashboard type-check/build.
7. Keep the release blocked if either route is 404, if durable evidence requirements fail, or if the provider/model gates are not satisfied.

## Final status

**Source integration:** merged to `main`.  
**Automated source/contract checks:** passed for the latest FreeOddsGateway PR head.  
**Production endpoint verification:** failed (HTTP 404 for both new routes).  
**Deployment:** not claimed; user/operator action in Floot and a successful post-publish probe are still required.

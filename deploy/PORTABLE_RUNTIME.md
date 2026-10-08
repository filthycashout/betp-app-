# PhilthyParleys portable production runtime

GitHub is the source of truth for backend code, CI, container packaging, and release evidence. Hosting providers are adapters only.

## Canonical image

`backend/Dockerfile` packages the existing FastAPI backend that already owns the complete PhilthyParleys API contract. `.github/workflows/backend-ghcr.yml` publishes immutable images to GitHub Container Registry on `main`.

Use commit-SHA tags for production. Do not deploy `latest` for an audited release.

## Required production secrets

The runtime expects these to be supplied by the deployment environment, never committed:

- `ODDS_API_KEY`
- `SPORTRADAR_API_KEY`
- `PHILTHY_EVIDENCE_DATABASE_URL`
- `DATABASE_URL` should point at the same durable database unless a separate application database is intentionally configured.

The Floot copies of these secrets cannot be exported by this repository. They must be independently connected to the chosen runtime or stored as GitHub environment secrets for a self-hosted deployment.

## Provider-independent verification

`ci/portable_backend_contract.py` verifies the full API surface needed by the mobile dashboard:

- health and system status
- NFL/NBA search
- model status and registry
- prop capabilities
- provider inventory
- evidence list
- game detail, props and best9
- best12
- best3
- 7/10/14-leg multisport parlays

The smoke also reads OpenAPI so a host cannot pass by serving only `/health` while silently omitting routes.

## Self-hosted zero-provider-build-quota path

Register a GitHub Actions runner on a Linux x64 machine with labels:

`self-hosted`, `linux`, `x64`, `philthyparleys-prod`

Create a GitHub `production` environment and add the three required secrets above. Then run **Self-Hosted Production Deploy** with the immutable commit-SHA image tag produced by **Publish Backend Image**.

The deploy workflow starts the candidate container, waits for health, runs the complete portable contract, and only then replaces the old production container. If contract validation fails, the previous container remains untouched.

A reverse proxy such as Caddy or nginx can terminate HTTPS and forward the public hostname to `127.0.0.1:8080`.

## Docker Compose alternative

Copy `deploy/docker-compose.prod.yml` and create `.env.production` outside version control. Set `PHILTHYPARLEYS_IMAGE` to an immutable GHCR tag, then run `docker compose -f deploy/docker-compose.prod.yml up -d`.

## Floot and Render

Floot and Render remain optional adapters/rollback targets. Their quotas or outages must not block development because all source, tests, images, and release gates live in GitHub.

Model promotion remains separate from deployment health. A healthy container does not imply that NFL/NBA trained models passed chronology, leakage, OOF calibration, Brier/log-loss/ECE, provenance, sample sufficiency, checksum/signature, or dependence gates.

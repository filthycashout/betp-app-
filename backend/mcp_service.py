from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import requests
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

SERVICE_VERSION = "1.1.0"
BACKEND_BASE = os.getenv(
    "PHILTHY_BACKEND_BASE_URL", "https://philthysports-api-v9.onrender.com"
).rstrip("/")
PUBLIC_HOST = os.getenv("MCP_PUBLIC_HOST", "philthysports-mcp-v1.onrender.com").strip()
SESSION = requests.Session()
SESSION.headers.update(
    {
        "Accept": "application/json",
        "User-Agent": f"PhilthySports-MCP/{SERVICE_VERSION}",
    }
)
RETRYABLE = {429, 502, 503, 504}

mcp = MCPServer(
    "philthysports-mcp",
    title="PhilthySports MCP",
    description="Governed read-only sports diagnostics, live research routing, evidence inspection, and explicit-input DFS optimization for PhilthySports.",
    instructions=(
        "Preserve source provenance and freshness. For predictive inputs enforce as_of < event_time. "
        "Never substitute mock/test data for production evidence. Keep sportsbook and DFS output descriptive; "
        "never execute wagers or contest entries. Setfive FanDuel is research-only, and Bytecode Viewer is "
        "authorized static-analysis guidance only. A trained model may replace the market baseline only after "
        "all PhilthySports v8 promotion gates pass."
    ),
    version=SERVICE_VERSION,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _backend_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{BACKEND_BASE}{path}"
    last_status: int | None = None
    last_error: str | None = None
    for attempt in range(4):
        try:
            response = SESSION.get(url, params=params, timeout=(6, 50))
            last_status = response.status_code
            if response.status_code == 200:
                payload = response.json()
                return {
                    "status": "OK",
                    "source": url,
                    "retrieved_at": _utc_now(),
                    "mock_data_used": False,
                    "payload": payload,
                }
            if response.status_code not in RETRYABLE:
                last_error = f"HTTP_{response.status_code}"
                break
            last_error = f"HTTP_{response.status_code}"
        except (requests.RequestException, ValueError) as exc:
            last_error = type(exc).__name__
        if attempt < 3:
            time.sleep(1.5 * (attempt + 1))
    return {
        "status": "UNAVAILABLE",
        "source": url,
        "retrieved_at": _utc_now(),
        "mock_data_used": False,
        "http_status": last_status,
        "error": last_error or "unknown_backend_error",
    }


@mcp.tool()
def philthy_health() -> dict[str, Any]:
    """Return current PhilthySports backend health and deployment evidence."""
    return _backend_get("/health")


@mcp.tool()
def philthy_system_status() -> dict[str, Any]:
    """Return chronology, calibration, leakage, provenance, promotion, credential, signing and runtime gate status."""
    return _backend_get("/v1/system/status")


@mcp.tool()
def philthy_provider_status() -> dict[str, Any]:
    """Return provider inventory plus safe credential/configuration state without exposing credential values."""
    return {
        "status": "OK",
        "retrieved_at": _utc_now(),
        "mock_data_used": False,
        "routing_contract": {
            "sportradar": "credentialed schedules/rosters/stats context; cannot bypass v8 promotion gates",
            "odds_api": "server-side live sportsbook odds when authenticated; stale/missing markets fail closed",
            "draftfast": "explicit-input DFS optimizer only; projections remain caller-provided evidence",
            "setfive_fanduel": "unofficial historical/schema research only; no production login/account automation",
            "bytecode_viewer": "authorized static APK/JAR/DEX analysis guidance only",
            "sports_mcp_router": "records source/retrieved_at/as_of/event identifiers and enforces as_of < event_time",
        },
        "system": _backend_get("/v1/system/status"),
        "providers": _backend_get("/v1/data/providers"),
    }


@mcp.tool()
def philthy_search(
    q: str = "",
    sport: str | None = None,
    date: str | None = None,
    include_props: bool = False,
    props_limit: int = 3,
) -> dict[str, Any]:
    """Run the governed PhilthySports NFL/NBA/MLB/NHL search using live backend evidence and fail-closed market validation."""
    if sport is not None:
        sport = sport.upper().strip()
        if sport not in {"NFL", "NBA", "MLB", "NHL"}:
            return {"status": "INVALID_ARGUMENT", "error": "sport must be NFL, NBA, MLB, or NHL"}
    props_limit = max(0, min(int(props_limit), 20))
    params: dict[str, Any] = {
        "q": q,
        "include_props": str(bool(include_props)).lower(),
        "props_limit": props_limit,
    }
    if sport:
        params["sport"] = sport
    if date:
        params["date"] = date
    return _backend_get("/v1/search", params=params)


@mcp.tool()
def philthy_best12(date: str | None = None) -> dict[str, Any]:
    """Return the governed Best 12 analysis for a date. Unavailable evidence remains unavailable rather than fabricated."""
    return _backend_get("/v1/picks/best12", params={"date": date} if date else None)


@mcp.tool()
def philthy_best3(date: str | None = None) -> dict[str, Any]:
    """Return the governed Best 3-leg parlay research output for a date without executing a wager."""
    return _backend_get("/v1/parlays/best3", params={"date": date} if date else None)


@mcp.tool()
def philthy_evidence(
    sport: str | None = None,
    date: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Read PhilthySports evidence-ledger records with provenance and freshness metadata."""
    if sport is not None:
        sport = sport.upper().strip()
        if sport not in {"NFL", "NBA", "MLB", "NHL"}:
            return {"status": "INVALID_ARGUMENT", "error": "sport must be NFL, NBA, MLB, or NHL"}
    params: dict[str, Any] = {"limit": max(1, min(int(limit), 250))}
    if sport:
        params["sport"] = sport
    if date:
        params["date"] = date
    return _backend_get("/v1/evidence/signals", params=params)


@mcp.tool()
def philthy_capability_inventory() -> dict[str, Any]:
    """Return the six-skill PhilthySports MCP routing inventory and execution boundaries."""
    return {
        "status": "OK",
        "retrieved_at": _utc_now(),
        "mock_data_used": False,
        "skills": {
            "sports-mcp-router": {
                "role": "multi-source routing/provenance/freshness enforcement",
                "execution": "active",
            },
            "sportradar-sports-data": {
                "role": "schedules/rosters/stats context",
                "docs": "https://gitmcp.io/johnwmillr/SportradarAPIs",
                "execution": "credentialed-through-backend-when-configured",
            },
            "odds-api-research": {
                "role": "live odds/bookmaker/fair-price research",
                "docs": "https://gitmcp.io/odds-api/odds-api",
                "execution": "server-side-through-backend-when-authenticated",
            },
            "draftfast-lineup-optimizer": {
                "role": "DFS lineup optimization from explicit player pool",
                "docs": "https://gitmcp.io/BenBrostoff/draftfast",
                "execution": "local-mcp-service",
            },
            "fanduel-api-research": {
                "role": "unofficial Setfive source/schema research",
                "docs": "https://gitmcp.io/Setfive/fanduel-api",
                "execution": "research-only-no-account-automation",
            },
            "bytecode-viewer-analysis": {
                "role": "authorized static Java/Android artifact analysis guidance",
                "docs": "https://gitmcp.io/Konloch/bytecode-viewer",
                "execution": "static-analysis-workflow-only",
            },
        },
        "predictive_contract": "as_of < event_time; preserve provenance; no production mock substitution",
    }


@mcp.tool()
def philthy_dfs_optimize(
    site: str,
    sport: str,
    players: list[dict[str, Any]],
    locked: list[str] | None = None,
    banned: list[str] | None = None,
) -> dict[str, Any]:
    """Optimize one DFS lineup with DraftFast from caller-supplied salary/projection data; this does not enter a contest or validate projection accuracy."""
    site = site.upper().strip()
    sport = sport.upper().strip()
    rule_names = {
        ("DK", "NFL"): "DK_NFL_RULE_SET",
        ("FD", "NFL"): "FD_NFL_RULE_SET",
        ("DK", "NBA"): "DK_NBA_RULE_SET",
        ("FD", "NBA"): "FD_NBA_RULE_SET",
        ("DK", "MLB"): "DK_MLB_RULE_SET",
        ("FD", "MLB"): "FD_MLB_RULE_SET",
        ("DK", "NHL"): "DK_NHL_RULE_SET",
    }
    rule_name = rule_names.get((site, sport))
    if not rule_name:
        return {
            "status": "UNSUPPORTED_RULE_SET",
            "site": site,
            "sport": sport,
            "supported": [f"{a}:{b}" for a, b in sorted(rule_names)],
        }
    if not players:
        return {"status": "INVALID_ARGUMENT", "error": "players must not be empty"}
    try:
        from draftfast import rules
        from draftfast.lineup_constraints import LineupConstraints
        from draftfast.optimize import run
        from draftfast.orm import Player

        pool = []
        seen: set[tuple[str, str, str | None]] = set()
        for index, raw in enumerate(players):
            missing = [key for key in ("name", "cost", "proj", "pos") if raw.get(key) in (None, "")]
            if missing:
                return {
                    "status": "INVALID_PLAYER",
                    "index": index,
                    "missing": missing,
                    "error": "DraftFast inputs require explicit name, cost, proj and pos; values are never invented",
                }
            name = str(raw["name"]).strip()
            pos = str(raw["pos"]).strip().upper()
            team = str(raw.get("team") or "").strip().upper() or None
            key = (name.casefold(), pos, team)
            if key in seen:
                return {"status": "INVALID_PLAYER", "index": index, "error": "duplicate player/position/team entry"}
            seen.add(key)
            pool.append(
                Player(
                    pos=pos,
                    name=name,
                    cost=float(raw["cost"]),
                    proj=float(raw["proj"]),
                    team=team,
                    matchup=str(raw.get("matchup") or "").strip() or None,
                )
            )
        constraints = LineupConstraints(locked=list(locked or []), banned=list(banned or []))
        roster = run(
            rule_set=getattr(rules, rule_name),
            player_pool=pool,
            constraints=constraints,
            verbose=False,
        )
        if roster is None:
            return {
                "status": "NO_FEASIBLE_LINEUP",
                "site": site,
                "sport": sport,
                "rule_set": rule_name,
            }
        lineup = [
            {
                "name": p.name,
                "position": p.pos,
                "team": p.team,
                "matchup": p.matchup,
                "salary": p.cost,
                "projection": p.proj,
            }
            for p in roster.sorted_players()
        ]
        return {
            "status": "OK",
            "source": "draftfast==3.12.5",
            "retrieved_at": _utc_now(),
            "mock_data_used": False,
            "site": site,
            "sport": sport,
            "rule_set": rule_name,
            "player_pool_count": len(pool),
            "constraints": {"locked": list(locked or []), "banned": list(banned or [])},
            "lineup": lineup,
            "salary_total": roster.spent(),
            "projected_total": roster.projected(),
            "projection_accuracy_verified": False,
            "contest_entry_executed": False,
        }
    except Exception as exc:
        return {
            "status": "OPTIMIZER_ERROR",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "mock_data_used": False,
        }


async def health_route(_: Request) -> JSONResponse:
    result = _backend_get("/health")
    return JSONResponse(
        {
            "status": "ok" if result.get("status") == "OK" else "degraded",
            "service": "philthysports-mcp",
            "version": SERVICE_VERSION,
            "protocol": "MCP dual-era via python-sdk 2.3.0",
            "backend": result,
        },
        status_code=200 if result.get("status") == "OK" else 503,
    )


async def root_route(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "service": "philthysports-mcp",
            "version": SERVICE_VERSION,
            "mcp": "/mcp",
            "health": "/health",
            "backend": BACKEND_BASE,
            "mock_data_used": False,
        }
    )


allowed_hosts = [PUBLIC_HOST, f"{PUBLIC_HOST}:*"] if PUBLIC_HOST else []
security = TransportSecuritySettings(
    enable_dns_rebinding_protection=bool(allowed_hosts),
    allowed_hosts=allowed_hosts,
    allowed_origins=["https://chatgpt.com", "https://chat.openai.com"],
)

app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
    transport_security=security,
    host=PUBLIC_HOST or "0.0.0.0",
    custom_starlette_routes=[
        Route("/", endpoint=root_route, methods=["GET"]),
        Route("/health", endpoint=health_route, methods=["GET"]),
    ],
)

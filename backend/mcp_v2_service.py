from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import requests
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

SERVICE_VERSION = "1.1.2"
BACKEND_BASE = os.getenv("PHILTHY_BACKEND_BASE_URL", "https://philthyparleys.floot.app/_api").rstrip("/")
PUBLIC_HOST = os.getenv("MCP_PUBLIC_HOST", "philthysports-mcp-v1.onrender.com").strip()
RETRYABLE = {429, 502, 503, 504}
SESSION = requests.Session()
SESSION.headers.update({"Accept": "application/json", "User-Agent": f"PhilthySports-MCP/{SERVICE_VERSION}"})

mcp = MCPServer(
    "philthysports-mcp",
    title="PhilthySports MCP",
    description="Governed PhilthySports diagnostics, live research routing, evidence inspection, and explicit-input DFS optimization.",
    instructions=(
        "Preserve source provenance and freshness. For predictive inputs enforce as_of < event_time. "
        "Never substitute mock/test data for production evidence. Never execute wagers or contest entries. "
        "Setfive FanDuel is research-only; Bytecode Viewer is authorized static-analysis guidance only. "
        "A trained model may replace the market baseline only after all PhilthySports v8 gates pass."
    ),
    version=SERVICE_VERSION,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unwrap(payload: Any) -> Any:
    """Normalize Floot's SuperJSON transport envelope without changing canonical JSON."""
    if (
        isinstance(payload, dict)
        and "json" in payload
        and set(payload).issubset({"json", "meta"})
    ):
        return payload["json"]
    return payload


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{BACKEND_BASE}{path}"
    last_status: int | None = None
    last_error: str | None = None
    for attempt in range(4):
        try:
            response = SESSION.get(url, params=params, timeout=(6, 50))
            last_status = response.status_code
            if response.status_code == 200:
                return {
                    "status": "OK",
                    "source": response.url,
                    "retrieved_at": _now(),
                    "mock_data_used": False,
                    "payload": _unwrap(response.json()),
                }
            last_error = f"HTTP_{response.status_code}"
            if response.status_code not in RETRYABLE:
                break
        except (requests.RequestException, ValueError) as exc:
            last_error = type(exc).__name__
        if attempt < 3:
            time.sleep(1.5 * (attempt + 1))
    return {
        "status": "UNAVAILABLE",
        "source": url,
        "retrieved_at": _now(),
        "mock_data_used": False,
        "http_status": last_status,
        "error": last_error or "unknown_backend_error",
    }


@mcp.tool()
def philthy_health() -> dict[str, Any]:
    """Return current PhilthySports API health without exposing credentials."""
    return _get("/health")


@mcp.tool()
def philthy_system_status() -> dict[str, Any]:
    """Return v8 chronology, calibration, leakage, provenance, promotion, credential and Android gate status."""
    return _get("/v1/system/status")


@mcp.tool()
def philthy_provider_status() -> dict[str, Any]:
    """Return safe provider inventory and routing roles; credential values are never returned."""
    return {
        "status": "OK",
        "retrieved_at": _now(),
        "mock_data_used": False,
        "routing_contract": {
            "sports_mcp_router": "multi-source routing; preserve source/retrieved_at/as_of/event IDs; enforce as_of < event_time",
            "sportradar": "credentialed sports context only; cannot bypass v8 promotion gates",
            "odds_api": "server-side live odds when authenticated; stale/missing markets fail closed",
            "draftfast": "explicit-input DFS optimizer only; projections are caller-provided evidence",
            "setfive_fanduel": "unofficial schema/research only; no production login/account automation",
            "bytecode_viewer": "authorized static APK/JAR/DEX analysis guidance only",
        },
        "system": _get("/v1/system/status"),
        "providers": _get("/v1/data/providers"),
    }


@mcp.tool()
def philthy_search(q: str = "", sport: str | None = None, date: str | None = None, include_props: bool = False, props_limit: int = 3) -> dict[str, Any]:
    """Run governed NFL/NBA/MLB/NHL research through the live PhilthySports backend."""
    if sport is not None:
        sport = sport.upper().strip()
        if sport not in {"NFL", "NBA", "MLB", "NHL"}:
            return {"status": "INVALID_ARGUMENT", "error": "sport must be NFL, NBA, MLB, or NHL"}
    params: dict[str, Any] = {
        "q": q,
        "include_props": str(bool(include_props)).lower(),
        "props_limit": max(0, min(int(props_limit), 20)),
    }
    if sport:
        params["sport"] = sport
    if date:
        params["date"] = date
    return _get("/v1/search", params)


@mcp.tool()
def philthy_best12(date: str | None = None) -> dict[str, Any]:
    """Return governed Best 12 sports analysis; missing evidence is never fabricated."""
    return _get("/v1/picks/best12", {"date": date} if date else None)


@mcp.tool()
def philthy_best3(date: str | None = None) -> dict[str, Any]:
    """Return governed Best 3-leg parlay research without executing a wager."""
    return _get("/v1/parlays/best3", {"date": date} if date else None)


@mcp.tool()
def philthy_evidence(sport: str | None = None, date: str | None = None, limit: int = 100) -> dict[str, Any]:
    """Read the PhilthySports evidence ledger with provenance/freshness metadata."""
    if sport is not None:
        sport = sport.upper().strip()
        if sport not in {"NFL", "NBA", "MLB", "NHL"}:
            return {"status": "INVALID_ARGUMENT", "error": "sport must be NFL, NBA, MLB, or NHL"}
    params: dict[str, Any] = {"limit": max(1, min(int(limit), 250))}
    if sport:
        params["sport"] = sport
    if date:
        params["date"] = date
    return _get("/v1/evidence/signals", params)


@mcp.tool()
def philthy_capability_inventory() -> dict[str, Any]:
    """Return all six incorporated MCP skill roles and their production boundaries."""
    return {
        "status": "OK",
        "retrieved_at": _now(),
        "mock_data_used": False,
        "skills": {
            "sports-mcp-router": {"role": "routing/provenance/freshness", "execution": "active"},
            "sportradar-sports-data": {"role": "sports context", "docs": "https://gitmcp.io/johnwmillr/SportradarAPIs", "execution": "credentialed backend when configured"},
            "odds-api-research": {"role": "odds/bookmaker research", "docs": "https://gitmcp.io/odds-api/odds-api", "execution": "server-side backend when authenticated"},
            "draftfast-lineup-optimizer": {"role": "DFS optimizer", "docs": "https://gitmcp.io/BenBrostoff/draftfast", "execution": "local MCP service"},
            "fanduel-api-research": {"role": "unofficial schema research", "docs": "https://gitmcp.io/Setfive/fanduel-api", "execution": "research-only"},
            "bytecode-viewer-analysis": {"role": "authorized static Android/Java analysis", "docs": "https://gitmcp.io/Konloch/bytecode-viewer", "execution": "static-analysis workflow only"},
        },
        "predictive_contract": "as_of < event_time; preserve provenance; fail closed; no production mock substitution",
    }


@mcp.tool()
def philthy_dfs_optimize(site: str, sport: str, players: list[dict[str, Any]], locked: list[str] | None = None, banned: list[str] | None = None) -> dict[str, Any]:
    """Optimize one DFS lineup with DraftFast from explicit salary/projection inputs; never enters a contest."""
    site, sport = site.upper().strip(), sport.upper().strip()
    rule_names = {
        ("DK", "NFL"): "DK_NFL_RULE_SET", ("FD", "NFL"): "FD_NFL_RULE_SET",
        ("DK", "NBA"): "DK_NBA_RULE_SET", ("FD", "NBA"): "FD_NBA_RULE_SET",
        ("DK", "MLB"): "DK_MLB_RULE_SET", ("FD", "MLB"): "FD_MLB_RULE_SET",
        ("DK", "NHL"): "DK_NHL_RULE_SET",
    }
    rule_name = rule_names.get((site, sport))
    if not rule_name:
        return {"status": "UNSUPPORTED_RULE_SET", "site": site, "sport": sport, "supported": [f"{a}:{b}" for a, b in sorted(rule_names)]}
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
                return {"status": "INVALID_PLAYER", "index": index, "missing": missing, "error": "name, cost, proj and pos are required and are never invented"}
            name = str(raw["name"]).strip()
            pos = str(raw["pos"]).strip().upper()
            team = str(raw.get("team") or "").strip().upper() or None
            key = (name.casefold(), pos, team)
            if key in seen:
                return {"status": "INVALID_PLAYER", "index": index, "error": "duplicate player/position/team entry"}
            seen.add(key)
            pool.append(Player(pos=pos, name=name, cost=float(raw["cost"]), proj=float(raw["proj"]), team=team, matchup=str(raw.get("matchup") or "").strip() or None))
        roster = run(
            rule_set=getattr(rules, rule_name),
            player_pool=pool,
            constraints=LineupConstraints(locked=list(locked or []), banned=list(banned or [])),
            verbose=False,
        )
        if roster is None:
            return {"status": "NO_FEASIBLE_LINEUP", "site": site, "sport": sport, "rule_set": rule_name}
        return {
            "status": "OK",
            "source": "draftfast==3.12.5",
            "retrieved_at": _now(),
            "mock_data_used": False,
            "site": site,
            "sport": sport,
            "rule_set": rule_name,
            "player_pool_count": len(pool),
            "lineup": [{"name": p.name, "position": p.pos, "team": p.team, "matchup": p.matchup, "salary": p.cost, "projection": p.proj} for p in roster.sorted_players()],
            "salary_total": roster.spent(),
            "projected_total": roster.projected(),
            "projection_accuracy_verified": False,
            "contest_entry_executed": False,
        }
    except Exception as exc:
        return {"status": "OPTIMIZER_ERROR", "error_type": type(exc).__name__, "message": str(exc), "mock_data_used": False}


security = TransportSecuritySettings(
    enable_dns_rebinding_protection=bool(PUBLIC_HOST),
    allowed_hosts=[PUBLIC_HOST, f"{PUBLIC_HOST}:*"] if PUBLIC_HOST else [],
    allowed_origins=["https://chatgpt.com", "https://chat.openai.com"],
)

app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
    transport_security=security,
    host=PUBLIC_HOST or "0.0.0.0",
)

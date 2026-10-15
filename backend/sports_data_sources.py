from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

SPORTS = ("NFL", "NBA", "MLB", "NHL")

LIVE_STRUCTURED = "LIVE_STRUCTURED"
HISTORICAL_STRUCTURED = "HISTORICAL_STRUCTURED"
MARKET = "MARKET"
SETTLEMENT = "SETTLEMENT"
CONTEXT = "CONTEXT"
WEB_RESEARCH = "WEB_RESEARCH"

FACTS_ONLY = "FACTS_ONLY"
CONTEXT_ONLY = "CONTEXT_ONLY"
CANONICALIZATION_REQUIRED = "CANONICALIZATION_REQUIRED"
SETTLEMENT_ONLY = "SETTLEMENT_ONLY"


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    name: str
    roles: tuple[str, ...]
    sports: tuple[str, ...]
    authentication: str
    runtime_env: str | None
    training_admission: str
    trusted_for_instructions: bool
    model_influence_default: bool
    current_use: str
    source_url: str


SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        source_id="espn_site_api",
        name="ESPN Site API",
        roles=(LIVE_STRUCTURED, SETTLEMENT, CONTEXT),
        sports=SPORTS,
        authentication="none",
        runtime_env=None,
        training_admission=CANONICALIZATION_REQUIRED,
        trusted_for_instructions=False,
        model_influence_default=False,
        current_use="schedules, scores, injuries/headlines and NFL/NBA settlement fallback",
        source_url="https://site.api.espn.com/",
    ),
    SourceSpec(
        source_id="sportradar",
        name="Sportradar league-specific APIs",
        roles=(LIVE_STRUCTURED, CONTEXT),
        sports=SPORTS,
        authentication="api_key",
        runtime_env="SPORTRADAR_API_KEY",
        training_admission=CANONICALIZATION_REQUIRED,
        trusted_for_instructions=False,
        model_influence_default=False,
        current_use="optional credentialed schedules, rosters, injuries, play-by-play and near-real-time statistics verification/context",
        source_url="https://developer.sportradar.com/",
    ),
    SourceSpec(
        source_id="nba_api",
        name="NBA Stats / nba_api",
        roles=(HISTORICAL_STRUCTURED,),
        sports=("NBA",),
        authentication="none",
        runtime_env=None,
        training_admission=CANONICALIZATION_REQUIRED,
        trusted_for_instructions=False,
        model_influence_default=False,
        current_use="team/player historical game logs for feature reconstruction",
        source_url="https://github.com/swar/nba_api",
    ),
    SourceSpec(
        source_id="nba_cdn",
        name="NBA CDN LiveData",
        roles=(LIVE_STRUCTURED,),
        sports=("NBA",),
        authentication="none",
        runtime_env=None,
        training_admission=CANONICALIZATION_REQUIRED,
        trusted_for_instructions=False,
        model_influence_default=False,
        current_use="live NBA scoreboard and box-score context",
        source_url="https://cdn.nba.com/",
    ),
    SourceSpec(
        source_id="mlb_statsapi",
        name="MLB StatsAPI",
        roles=(LIVE_STRUCTURED, HISTORICAL_STRUCTURED, SETTLEMENT),
        sports=("MLB",),
        authentication="none",
        runtime_env=None,
        training_admission=CANONICALIZATION_REQUIRED,
        trusted_for_instructions=False,
        model_influence_default=False,
        current_use="schedule, probable pitchers, live game data, venue data and final labels",
        source_url="https://statsapi.mlb.com/api/",
    ),
    SourceSpec(
        source_id="pybaseball",
        name="pybaseball / Baseball Savant / FanGraphs",
        roles=(HISTORICAL_STRUCTURED,),
        sports=("MLB",),
        authentication="none",
        runtime_env=None,
        training_admission=CANONICALIZATION_REQUIRED,
        trusted_for_instructions=False,
        model_influence_default=False,
        current_use="bounded historical Statcast and baseball feature research",
        source_url="https://github.com/jldbc/pybaseball",
    ),
    SourceSpec(
        source_id="nhl_web_api",
        name="NHL Web API",
        roles=(LIVE_STRUCTURED, HISTORICAL_STRUCTURED, SETTLEMENT),
        sports=("NHL",),
        authentication="none",
        runtime_env=None,
        training_admission=CANONICALIZATION_REQUIRED,
        trusted_for_instructions=False,
        model_influence_default=False,
        current_use="schedule, game centre/statistics and final labels",
        source_url="https://api-web.nhle.com/",
    ),
    SourceSpec(
        source_id="nflverse",
        name="nflverse / nflreadpy",
        roles=(HISTORICAL_STRUCTURED,),
        sports=("NFL",),
        authentication="none",
        runtime_env=None,
        training_admission=CANONICALIZATION_REQUIRED,
        trusted_for_instructions=False,
        model_influence_default=False,
        current_use="schedules, team/player stats, injuries and other reconstructable NFL history",
        source_url="https://nflreadpy.nflverse.com/",
    ),
    SourceSpec(
        source_id="keyless_sportsbook_gateway",
        name="PhilthySports keyless sportsbook gateway",
        roles=(MARKET,),
        sports=SPORTS,
        authentication="none",
        runtime_env=None,
        training_admission=CANONICALIZATION_REQUIRED,
        trusted_for_instructions=False,
        model_influence_default=False,
        current_use="current game odds and selected player props with per-event validation",
        source_url="internal:backend/free_odds_gateway.py",
    ),
    SourceSpec(
        source_id="the_odds_api",
        name="The Odds API v4",
        roles=(MARKET,),
        sports=SPORTS,
        authentication="api_key",
        runtime_env="ODDS_API_KEY",
        training_admission=CANONICALIZATION_REQUIRED,
        trusted_for_instructions=False,
        model_influence_default=False,
        current_use="credentialed current odds/props and optional paid historical market snapshots",
        source_url="https://api.the-odds-api.com/v4/",
    ),
    SourceSpec(
        source_id="nws",
        name="US National Weather Service",
        roles=(CONTEXT,),
        sports=("NFL", "MLB"),
        authentication="none",
        runtime_env=None,
        training_admission=CONTEXT_ONLY,
        trusted_for_instructions=False,
        model_influence_default=False,
        current_use="pregame outdoor weather context",
        source_url="https://api.weather.gov/",
    ),
    SourceSpec(
        source_id="scrapegraphai",
        name="ScrapeGraphAI V2",
        roles=(WEB_RESEARCH,),
        sports=SPORTS,
        authentication="api_key",
        runtime_env="SGAI_API_KEY",
        training_admission=CONTEXT_ONLY,
        trusted_for_instructions=False,
        model_influence_default=False,
        current_use="public-web injury, lineup, depth-chart, goalie/pitcher and role-change research sidecars",
        source_url="https://v2-api.scrapegraphai.com/",
    ),
)


def runtime_ready(spec: SourceSpec) -> bool:
    if not spec.runtime_env:
        return True
    return bool(os.getenv(spec.runtime_env, "").strip())


def source_inventory() -> dict[str, Any]:
    return {
        "sports": list(SPORTS),
        "sources": [
            {
                **asdict(spec),
                "roles": list(spec.roles),
                "sports": list(spec.sports),
                "runtime_ready": runtime_ready(spec),
            }
            for spec in SOURCES
        ],
        "governance": {
            "trusted_for_instructions_default": False,
            "web_research_model_influence_default": False,
            "scraped_context_training_eligible_default": False,
            "canonical_admission_required": True,
            "automatic_wagering": False,
        },
    }


def sources_for(sport: str, role: str | None = None) -> list[SourceSpec]:
    sport = sport.upper().strip()
    if sport not in SPORTS:
        raise ValueError(f"unsupported sport: {sport}")
    return [
        spec
        for spec in SOURCES
        if sport in spec.sports and (role is None or role in spec.roles)
    ]

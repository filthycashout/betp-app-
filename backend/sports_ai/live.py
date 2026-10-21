from __future__ import annotations

from datetime import date as date_cls, datetime, timezone
from typing import Any

from sports_ai import SUPPORTED_SPORTS
from sports_ai.ingestion.market import moneyline_candidate_from_event
from sports_ai.ingestion.ufc import fetch_ufc_events
from sports_ai.ingestion.sharp import extract_sharp_moneyline_anchor, fetch_pinnacle_moneyline_anchor
from sports_ai.orchestrator import SportsAIEngine


def _runtime_backend():
    import app

    return app


def _selected_probability(home_probability: float, selection: str, home: str, away: str) -> float:
    if selection.casefold() == home.casefold():
        return float(home_probability)
    if selection.casefold() == away.casefold():
        return 1.0 - float(home_probability)
    raise ValueError("selection does not match home or away team")


def _sharp_evidence(
    runtime: Any,
    engine: SportsAIEngine,
    *,
    sport: str,
    game: dict[str, Any],
    odds_events: list[dict[str, Any]],
    selection: str,
    now: datetime,
) -> dict[str, Any]:
    settings = engine.settings
    evidence = extract_sharp_moneyline_anchor(
        odds_events,
        game=game,
        selection=selection,
        allowed_book_keys=settings.sharp_book_keys,
        now=now,
        max_age_seconds=settings.sharp_max_age_seconds,
    )
    if evidence.get("verified"):
        evidence["retrieval"] = "existing_odds_event_pool"
        return evidence
    if "pinnacle" not in {key.lower() for key in settings.sharp_book_keys}:
        return evidence
    fetched = fetch_pinnacle_moneyline_anchor(
        runtime,
        sport=sport,
        game=game,
        selection=selection,
        now=now,
        max_age_seconds=settings.sharp_max_age_seconds,
    )
    return fetched if fetched.get("verified") else fetched




def _run_live_ufc(
    runtime: Any,
    *,
    day: date_cls,
    query: str,
    engine: SportsAIEngine,
) -> dict[str, Any]:
    """Run the UFC moneyline adapter without pretending UFC is a team league."""
    try:
        events = fetch_ufc_events(runtime, day)
    except Exception as exc:
        return {
            "sport": "UFC",
            "date": day.isoformat(),
            "status": "PROVIDER_UNAVAILABLE",
            "error_type": type(exc).__name__,
            "decisions": [],
            "execution_policy": {
                "automatic_wagering": False,
                "verified_sharp_anchor_required": True,
                "verified_sharp_anchor_available": False,
                "player_props_supported": False,
            },
        }

    decisions: list[dict[str, Any]] = []
    for event in events:
        home = str(event.get("home") or event.get("home_team") or "").strip()
        away = str(event.get("away") or event.get("away_team") or "").strip()
        matchup = f"{away} @ {home}"
        if query and query.casefold() not in f"{home} {away}".casefold():
            continue

        current = datetime.now(timezone.utc)
        try:
            candidate = moneyline_candidate_from_event(
                sport="UFC",
                game=event,
                odds_event=event,
                selection=None,
                context_ready=True,
                source_health_passed=event.get("market_source") == "THE_ODDS_API_V4_UFC",
                prediction_time=current,
                actionable=True,
            )
            governed = engine.evaluate_candidate(candidate)
            status = "EVALUATED"
            error_type = None
        except Exception as exc:
            governed = None
            status = "MARKET_EVIDENCE_UNAVAILABLE"
            error_type = type(exc).__name__

        decisions.append({
            "event_id": event.get("event_id"),
            "matchup": matchup,
            "event_time": event.get("event_time"),
            "status": status,
            "market_source": event.get("market_source"),
            "market_scope": "fight_winner_moneyline",
            "player_props_supported": False,
            "sharp_anchor": {
                "status": "SHARP_ANCHOR_NOT_VERIFIED",
                "verified": False,
                "anchor": None,
            },
            "model_runtime_mode": "MARKET_BASELINE_ONLY",
            "promotion_gate_passed": False,
            "promoted_model_contributed": False,
            "error_type": error_type,
            "decision": governed,
        })

    return {
        "sport": "UFC",
        "date": day.isoformat(),
        "status": "OK" if decisions else "NO_MATCHING_GAMES",
        "decisions": decisions,
        "execution_policy": {
            "automatic_wagering": False,
            "verified_sharp_anchor_required": True,
            "verified_sharp_anchor_available": False,
            "sharp_anchor_note": "UFC remains non-actionable until a verified, independent sharp anchor is available.",
            "player_props_supported": False,
            "market_scope": "fight_winner_moneyline",
        },
    }


def run_live_sport(
    sport: str,
    *,
    date: str | None = None,
    query: str = "",
    backend: Any | None = None,
    engine: SportsAIEngine | None = None,
) -> dict[str, Any]:
    runtime = backend or _runtime_backend()
    decision_engine = engine or SportsAIEngine()
    normalized = sport.upper()
    if normalized not in SUPPORTED_SPORTS:
        raise ValueError(f"unsupported sport: {sport}")

    day = date_cls.fromisoformat(date) if date else runtime._pacific_today()
    if normalized == "UFC":
        return _run_live_ufc(runtime, day=day, query=query, engine=decision_engine)
    try:
        schedule = runtime._schedule(normalized, day)
        odds_events = runtime._odds(normalized, day)
    except Exception as exc:
        return {
            "sport": normalized,
            "date": day.isoformat(),
            "status": "PROVIDER_UNAVAILABLE",
            "error_type": type(exc).__name__,
            "decisions": [],
            "execution_policy": {
                "automatic_wagering": False,
                "verified_sharp_anchor_required": True,
                "verified_sharp_anchor_available": False,
            },
        }

    decisions: list[dict[str, Any]] = []
    any_sharp = False
    for game in schedule:
        if query and not runtime._matches_search_query(query, game, normalized, day):
            continue

        odds_event = runtime._match_odds(game, odds_events)
        if odds_event is None:
            decisions.append({
                "event_id": game.get("event_id"),
                "matchup": f"{game.get('away')} @ {game.get('home')}",
                "status": "NO_MATCHED_ODDS_EVENT",
                "decision": None,
            })
            continue

        market = runtime._market(odds_event)
        market_home_probability = market.get("home_probability")
        if market_home_probability is None:
            decisions.append({
                "event_id": game.get("event_id"),
                "matchup": f"{game.get('away')} @ {game.get('home')}",
                "status": "NO_FRESH_TWO_SIDED_MONEYLINE",
                "market_source": odds_event.get("market_source"),
                "decision": None,
            })
            continue

        home = str(game.get("home") or "")
        away = str(game.get("away") or "")
        final_home_probability = float(market_home_probability)
        promoted = runtime.PROMOTED_MODELS.get(normalized)
        gate = runtime._promotion_gate_for(normalized)
        promoted_contributed = False
        inference_error: str | None = None

        if promoted is not None and gate.get("passed") is True:
            try:
                final_home_probability = float(runtime.predict_home_probability(
                    promoted,
                    {
                        "consensus_de_vig_home_probability": float(market_home_probability),
                        "home_spread": market.get("home_spread"),
                        "consensus_total": market.get("total"),
                    },
                ))
                promoted_contributed = True
            except Exception as exc:
                final_home_probability = float(market_home_probability)
                inference_error = type(exc).__name__

        selection = home if final_home_probability >= 0.5 else away
        selected_model_probability = (
            _selected_probability(final_home_probability, selection, home, away)
            if promoted_contributed
            else None
        )
        current = datetime.now(timezone.utc)
        sharp = _sharp_evidence(
            runtime,
            decision_engine,
            sport=normalized,
            game=game,
            odds_events=odds_events,
            selection=selection,
            now=current,
        )
        sharp_anchor = sharp.get("anchor") if sharp.get("verified") else None
        any_sharp = any_sharp or bool(sharp_anchor)
        source_health_passed = bool(str(odds_event.get("market_source") or "").strip())

        try:
            candidate = moneyline_candidate_from_event(
                sport=normalized,
                game=game,
                odds_event=odds_event,
                selection=selection,
                context_ready=True,
                source_health_passed=source_health_passed,
                prediction_time=current,
                actionable=True,
                sharp_anchor=sharp_anchor,
                model_prob=selected_model_probability,
                model_promotion_passed=promoted_contributed,
                model_includes_market=promoted_contributed,
            )
            governed = decision_engine.evaluate_candidate(candidate)
            status = "EVALUATED"
        except Exception as exc:
            governed = None
            status = "DECISION_INPUT_REJECTED"
            inference_error = inference_error or type(exc).__name__

        decisions.append({
            "event_id": game.get("event_id"),
            "matchup": f"{away} @ {home}",
            "event_time": game.get("event_time"),
            "status": status,
            "market_source": odds_event.get("market_source"),
            "source_health_passed": source_health_passed,
            "sharp_anchor": sharp,
            "model_runtime_mode": runtime._runtime_mode_for(normalized),
            "promotion_gate_passed": bool(gate.get("passed")),
            "promoted_model_contributed": promoted_contributed,
            "model_inference_error": inference_error,
            "decision": governed,
        })

    return {
        "sport": normalized,
        "date": day.isoformat(),
        "status": "OK" if decisions else "NO_MATCHING_GAMES",
        "decisions": decisions,
        "execution_policy": {
            "automatic_wagering": False,
            "verified_sharp_anchor_required": True,
            "verified_sharp_anchor_available": any_sharp,
            "sharp_book_keys": list(decision_engine.settings.sharp_book_keys),
            "sharp_max_age_seconds": decision_engine.settings.sharp_max_age_seconds,
        },
    }


def run_live_all(
    *,
    date: str | None = None,
    query: str = "",
    backend: Any | None = None,
    engine: SportsAIEngine | None = None,
) -> dict[str, Any]:
    runtime = backend or _runtime_backend()
    decision_engine = engine or SportsAIEngine()
    return {
        sport: run_live_sport(
            sport,
            date=date,
            query=query,
            backend=runtime,
            engine=decision_engine,
        )
        for sport in SUPPORTED_SPORTS
    }

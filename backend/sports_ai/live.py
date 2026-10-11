from __future__ import annotations

from datetime import date as date_cls
from typing import Any

from sports_ai import SUPPORTED_SPORTS
from sports_ai.ingestion.market import moneyline_candidate_from_event
from sports_ai.orchestrator import SportsAIEngine


def _runtime_backend():
    # Lazy import prevents the reusable decision package from importing FastAPI
    # or live provider clients during ordinary unit tests/offline analysis.
    import app

    return app


def _selected_probability(home_probability: float, selection: str, home: str, away: str) -> float:
    if selection.casefold() == home.casefold():
        return float(home_probability)
    if selection.casefold() == away.casefold():
        return 1.0 - float(home_probability)
    raise ValueError("selection does not match home or away team")


def run_live_sport(
    sport: str,
    *,
    date: str | None = None,
    query: str = "",
    backend: Any | None = None,
    engine: SportsAIEngine | None = None,
) -> dict[str, Any]:
    """Run the unified game-winner decision core against current backend data.

    Strict live mode intentionally requires a verified sharp anchor for an
    actionable recommendation. The repository currently has no authenticated
    sharp-anchor contract, so live results remain blocked from recommendation
    eligibility rather than silently treating ordinary consensus as sharp.
    """

    runtime = backend or _runtime_backend()
    decision_engine = engine or SportsAIEngine()
    normalized = sport.upper()
    if normalized not in SUPPORTED_SPORTS:
        raise ValueError(f"unsupported sport: {sport}")

    day = date_cls.fromisoformat(date) if date else runtime._pacific_today()
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
        source_health_passed = bool(str(odds_event.get("market_source") or "").strip())

        try:
            candidate = moneyline_candidate_from_event(
                sport=normalized,
                game=game,
                odds_event=odds_event,
                selection=selection if promoted_contributed else None,
                context_ready=True,
                source_health_passed=source_health_passed,
                actionable=True,
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
            "verified_sharp_anchor_available": False,
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

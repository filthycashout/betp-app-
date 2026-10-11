from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sports_ai.ingestion.odds import moneyline_snapshot_from_event
from sports_ai.orchestrator import MarketCandidate


def _utc(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _probability(value: Any, *, field: str) -> float:
    try:
        probability = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is required") from exc
    if not 0.0 < probability < 1.0:
        raise ValueError(f"{field} must be in (0, 1)")
    return probability


def _price(value: Any) -> float:
    try:
        price = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("moneyline_best_price is required") from exc
    if price == 0.0 or abs(price) < 100.0:
        raise ValueError("moneyline_best_price must be valid American odds")
    return price


def _market_quality(market: dict[str, Any]) -> float:
    """Evidence-quality score, not a win probability."""

    if market.get("freshness_verified") is not True:
        return 0.0
    if market.get("provider_timestamp_verified") is True:
        return 1.0
    if market.get("observed_at_verified") is True:
        return 0.80
    return 0.0


def _source_key(source: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", source.upper()).strip("_")
    if not normalized:
        raise ValueError("market source is invalid")
    return normalized


def moneyline_candidate_from_validated_market(
    *,
    sport: str,
    game: dict[str, Any],
    market: dict[str, Any],
    context_ready: bool,
    source_health_passed: bool,
    prediction_time: datetime | None = None,
    max_quote_age_seconds: int = 300,
    actionable: bool = True,
    sharp_anchor: dict[str, Any] | None = None,
    model_prob: float | None = None,
    model_promotion_passed: bool = False,
    model_includes_market: bool = False,
) -> MarketCandidate:
    """Convert a validated market payload into the unified decision contract."""

    normalized = sport.upper().strip()
    selection = str(market.get("moneyline_pick") or "").strip()
    if not selection:
        raise ValueError("validated market has no moneyline_pick")
    if market.get("freshness_verified") is not True:
        raise ValueError("validated market freshness is not verified")

    now = (prediction_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
    event_time = _utc(game.get("event_time") or game.get("commence_time"))
    if not now < event_time:
        raise ValueError("pregame candidate requires prediction_time < event_time")

    observed_at = _utc(market.get("moneyline_last_update") or market.get("last_update"))
    age = (now - observed_at).total_seconds()
    if not -30.0 <= age <= float(max_quote_age_seconds):
        raise ValueError("validated market quote is stale or future-dated")
    snapshot_age = max(0.0, age)

    anchor_probability = _probability(
        market.get("moneyline_pick_probability"),
        field="moneyline_pick_probability",
    )
    anchor_kind = "DEVIG_CONSENSUS"
    sharp_verified = False

    if sharp_anchor is not None:
        source = str(sharp_anchor.get("source") or "").strip()
        if not source:
            raise ValueError("sharp_anchor source is required")
        source_key = _source_key(source)
        soft_book = str(market.get("moneyline_best_book") or "").strip()
        if soft_book and source_key == _source_key(soft_book):
            raise ValueError("sharp_anchor source must differ from soft price book")
        if sharp_anchor.get("no_vig") is not True:
            raise ValueError("sharp_anchor must explicitly be no-vig")
        anchor_selection = str(sharp_anchor.get("selection") or "").strip()
        if anchor_selection.casefold() != selection.casefold():
            raise ValueError("sharp_anchor selection does not match market selection")
        sharp_observed = _utc(sharp_anchor.get("observed_at"))
        sharp_age = (now - sharp_observed).total_seconds()
        if not -30.0 <= sharp_age <= float(max_quote_age_seconds):
            raise ValueError("sharp_anchor is stale or future-dated")
        if sharp_observed >= event_time:
            raise ValueError("sharp_anchor must be observed before event_time")
        anchor_probability = _probability(
            sharp_anchor.get("probability"),
            field="sharp_anchor probability",
        )
        anchor_kind = f"{source_key}_NO_VIG"
        sharp_verified = True
        snapshot_age = max(snapshot_age, max(0.0, sharp_age))

    normalized_model_prob = None
    if model_prob is not None:
        normalized_model_prob = _probability(model_prob, field="model_prob")

    return MarketCandidate(
        sport=normalized,
        event_id=str(game.get("event_id") or game.get("id") or ""),
        market="moneyline",
        line=None,
        selection=selection,
        soft_american_odds=_price(market.get("moneyline_best_price")),
        market_anchor_prob=anchor_probability,
        snapshot_age_seconds=snapshot_age,
        market_quality=_market_quality(market),
        source_health_passed=bool(source_health_passed),
        context_ready=bool(context_ready),
        model_prob=normalized_model_prob,
        model_promotion_passed=bool(model_promotion_passed),
        model_includes_market=bool(model_includes_market),
        market_anchor_kind=anchor_kind,
        sharp_anchor_verified=sharp_verified,
        require_sharp_anchor=bool(actionable),
    )


def moneyline_candidate_from_event(
    *,
    sport: str,
    game: dict[str, Any],
    odds_event: dict[str, Any],
    selection: str | None,
    context_ready: bool,
    source_health_passed: bool,
    prediction_time: datetime | None = None,
    max_quote_age_seconds: int = 300,
    actionable: bool = True,
    sharp_anchor: dict[str, Any] | None = None,
    model_prob: float | None = None,
    model_promotion_passed: bool = False,
    model_includes_market: bool = False,
) -> MarketCandidate:
    """Build a candidate from side-complete fresh H2H evidence.

    `selection` may be the opposite side from the market consensus. The chosen
    side always receives its own consensus probability and its own best offered
    price, preventing the model from inheriting the other team's quote.
    """

    now = (prediction_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
    snapshot = moneyline_snapshot_from_event(
        odds_event,
        now=now,
        max_quote_age_seconds=max_quote_age_seconds,
    )
    if snapshot.get("status") != "OK":
        raise ValueError(f"side-complete moneyline unavailable: {snapshot.get('status')}")

    home = str(snapshot["home_team"])
    away = str(snapshot["away_team"])
    chosen = str(selection or "").strip()
    if not chosen:
        chosen = home if float(snapshot["home_probability"]) >= 0.5 else away

    if chosen.casefold() == home.casefold():
        probability = snapshot["home_probability"]
        best_price = snapshot["home_best_price"]
        best_book = snapshot["home_best_book"]
        best_update = snapshot["home_best_price_last_update"]
        chosen = home
    elif chosen.casefold() == away.casefold():
        probability = snapshot["away_probability"]
        best_price = snapshot["away_best_price"]
        best_book = snapshot["away_best_book"]
        best_update = snapshot["away_best_price_last_update"]
        chosen = away
    else:
        raise ValueError("selection does not match the event home or away team")

    adapted_market = {
        "freshness_verified": snapshot["freshness_verified"],
        "provider_timestamp_verified": snapshot["provider_timestamp_verified"],
        "observed_at_verified": snapshot["observed_at_verified"],
        "freshness_basis": snapshot["freshness_basis"],
        "moneyline_pick": chosen,
        "moneyline_pick_probability": probability,
        "moneyline_best_price": best_price,
        "moneyline_best_book": best_book,
        "moneyline_last_update": best_update or snapshot["last_update"],
        "last_update": snapshot["last_update"],
    }
    return moneyline_candidate_from_validated_market(
        sport=sport,
        game=game,
        market=adapted_market,
        context_ready=context_ready,
        source_health_passed=source_health_passed,
        prediction_time=now,
        max_quote_age_seconds=max_quote_age_seconds,
        actionable=actionable,
        sharp_anchor=sharp_anchor,
        model_prob=model_prob,
        model_promotion_passed=model_promotion_passed,
        model_includes_market=model_includes_market,
    )

from typing import Any
from freshness import freshness_status
SUPPORTED_SPORTS={"NFL","NBA","NHL","MLB"}

def validate_event(event:dict[str,Any])->list[str]:
    errors=[]
    for key in ("event_id","sport","start_time","home_team","away_team","source","observed_at"):
        if event.get(key) in (None,""): errors.append(f"missing:{key}")
    sport=str(event.get("sport","")).upper()
    if sport and sport not in SUPPORTED_SPORTS: errors.append(f"unsupported_sport:{sport}")
    if event.get("home_team") and event.get("home_team")==event.get("away_team"): errors.append("same_home_and_away_team")
    return errors

def validate_quote(quote:dict[str,Any],*,max_age_seconds:int,now=None)->list[str]:
    errors=[]
    for key in ("event_id","sport","market","selection","odds_american","book","source","observed_at"):
        if quote.get(key) in (None,""): errors.append(f"missing:{key}")
    try:
        if int(quote.get("odds_american"))==0: errors.append("invalid_american_odds_zero")
    except (TypeError,ValueError): errors.append("invalid_american_odds")
    status=freshness_status(quote,max_age_seconds=max_age_seconds,now=now)
    if not status["fresh"]: errors.append(f"not_fresh:{status['reason']}")
    if str(quote.get("sport","")).upper() not in SUPPORTED_SPORTS: errors.append(f"unsupported_sport:{quote.get('sport')}")
    return errors

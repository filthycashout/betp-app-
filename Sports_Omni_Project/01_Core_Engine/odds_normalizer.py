from typing import Any
from probability import american_to_implied_probability,devig_two_way

def normalize_quote(quote:dict[str,Any])->dict[str,Any]:
    required=("event_id","sport","market","selection","odds_american","book","source","observed_at")
    missing=[key for key in required if quote.get(key) in (None,"")]
    if missing: raise ValueError("quote missing required fields: "+", ".join(missing))
    odds=int(quote["odds_american"])
    result=dict(quote); result["odds_american"]=odds
    result["raw_implied_probability"]=american_to_implied_probability(odds)
    result["provider_timestamp"]=quote.get("provider_timestamp")
    return result

def normalize_two_way(a:dict[str,Any],b:dict[str,Any])->tuple[dict[str,Any],dict[str,Any]]:
    left,right=normalize_quote(a),normalize_quote(b)
    keys=("event_id","sport","market","book","line")
    if not all(left.get(k)==right.get(k) for k in keys): raise ValueError("two-way quotes must match event, sport, market, book, and line")
    left["no_vig_probability"],right["no_vig_probability"]=devig_two_way(left["odds_american"],right["odds_american"])
    return left,right

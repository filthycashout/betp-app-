from __future__ import annotations
import argparse,json
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from data_quality import validate_event,validate_quote
from odds_normalizer import normalize_quote
DEFAULT_MAX_QUOTE_AGE_SECONDS=900

def analyze_payload(payload:dict[str,Any],*,now:datetime|None=None,max_quote_age_seconds:int=DEFAULT_MAX_QUOTE_AGE_SECONDS)->dict[str,Any]:
    events,quotes=payload.get("events",[]),payload.get("quotes",[])
    if not isinstance(events,list) or not isinstance(quotes,list): raise ValueError("events and quotes must be arrays")
    event_results=[]; known=set()
    for event in events:
        if not isinstance(event,dict): event_results.append({"eligible":False,"errors":["event_not_object"]}); continue
        errors=validate_event(event)
        if event.get("event_id") in known: errors.append("duplicate_event_id")
        known.add(event.get("event_id"))
        event_results.append({"event_id":event.get("event_id"),"sport":str(event.get("sport","")).upper(),"eligible":not errors,"errors":errors})
    quote_results=[]
    for quote in quotes:
        if not isinstance(quote,dict): quote_results.append({"eligible":False,"errors":["quote_not_object"]}); continue
        errors=validate_quote(quote,max_age_seconds=max_quote_age_seconds,now=now)
        if quote.get("event_id") not in known: errors.append("unknown_event_id")
        normalized=normalize_quote(quote) if not errors else None
        quote_results.append({"event_id":quote.get("event_id"),"market":quote.get("market"),"selection":quote.get("selection"),"eligible":not errors,"errors":errors,"normalized":normalized})
    return {"schema_version":"1.0","generated_at":(now or datetime.now(timezone.utc)).isoformat(),"mode":"evidence_validation_only","events_seen":len(events),"quotes_seen":len(quotes),"eligible_events":sum(x.get("eligible",False) for x in event_results),"eligible_quotes":sum(x.get("eligible",False) for x in quote_results),"events":event_results,"quotes":quote_results,"prediction_status":"not_generated_no_promoted_model_or_provider_claimed"}

def main()->int:
    parser=argparse.ArgumentParser(description="Validate normalized Sports Omni evidence JSON")
    parser.add_argument("input",type=Path); parser.add_argument("--output",type=Path); parser.add_argument("--max-quote-age-seconds",type=int,default=DEFAULT_MAX_QUOTE_AGE_SECONDS)
    args=parser.parse_args()
    if args.max_quote_age_seconds<1: parser.error("max quote age must be positive")
    report=analyze_payload(json.loads(args.input.read_text(encoding="utf-8")),max_quote_age_seconds=args.max_quote_age_seconds)
    rendered=json.dumps(report,indent=2,sort_keys=True)
    if args.output: args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(rendered+"\n",encoding="utf-8")
    print(rendered); return 0 if report["eligible_events"]>0 else 2
if __name__=="__main__": raise SystemExit(main())

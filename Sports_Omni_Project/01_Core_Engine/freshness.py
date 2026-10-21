from datetime import datetime,timezone
from typing import Any

def parse_timestamp(value: str | datetime) -> datetime:
    if isinstance(value,datetime): parsed=value
    elif isinstance(value,str): parsed=datetime.fromisoformat(value.strip().replace("Z","+00:00"))
    else: raise ValueError("timestamp must be ISO-8601 string or datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None: raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)

def freshness_status(record: dict[str,Any], *, max_age_seconds:int, now:datetime|None=None)->dict[str,Any]:
    if not record.get("observed_at"): return {"fresh":False,"reason":"missing_observed_at","age_seconds":None}
    try: age=(parse_timestamp(now or datetime.now(timezone.utc))-parse_timestamp(record["observed_at"])).total_seconds()
    except (TypeError,ValueError) as exc: return {"fresh":False,"reason":f"invalid_timestamp:{exc}","age_seconds":None}
    if age < -60: return {"fresh":False,"reason":"timestamp_in_future","age_seconds":age}
    if age > max_age_seconds: return {"fresh":False,"reason":"stale","age_seconds":age}
    return {"fresh":True,"reason":"fresh","age_seconds":age}

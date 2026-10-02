from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import pandas as pd

MIN_PAIR_SAMPLES = 200


def phi(a: int, b: int, c: int, d: int) -> float | None:
    denom = math.sqrt((a+b)*(c+d)*(a+c)*(b+d))
    if denom == 0:
        return None
    return (a*d - b*c) / denom


def dependency_key(left: dict, right: dict) -> str:
    same_event = left["event_id"] == right["event_id"]
    sports = "+".join(sorted([left["sport"], right["sport"]]))
    markets = "+".join(sorted([left["market_type"], right["market_type"]]))
    return f"{'same_event' if same_event else 'cross_event'}|{sports}|{markets}"


def main() -> None:
    p=argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--min-pairs", type=int, default=MIN_PAIR_SAMPLES)
    args=p.parse_args()

    path=Path(args.input)
    raw=path.read_bytes()
    df=pd.read_csv(path)
    required={"slate_id","leg_id","event_id","sport","market_type","hit","settled_at"}
    missing=sorted(required-set(df.columns))
    if missing:
        raise SystemExit(f"Missing settled-leg columns: {missing}")
    df["hit"]=pd.to_numeric(df["hit"], errors="raise").astype(int)
    if not set(df["hit"].unique()).issubset({0,1}):
        raise SystemExit("hit must be binary")
    if df.duplicated(["slate_id","leg_id"]).any():
        raise SystemExit("duplicate settled leg ids")

    counts=defaultdict(lambda:[0,0,0,0,0])
    dates_by_key=defaultdict(set)
    for _, group in df.groupby("slate_id", sort=False):
        rows=group.to_dict("records")
        for left,right in combinations(rows,2):
            key=dependency_key(left,right)
            dates_by_key[key].add(str(pd.to_datetime(left["settled_at"], utc=True).date()))
            dates_by_key[key].add(str(pd.to_datetime(right["settled_at"], utc=True).date()))
            lh,rh=int(left["hit"]),int(right["hit"])
            bucket=counts[key]
            if lh and rh: bucket[0]+=1
            elif lh and not rh: bucket[1]+=1
            elif not lh and rh: bucket[2]+=1
            else: bucket[3]+=1
            bucket[4]+=1

    estimates={}
    for key,(a,b,c,d,n) in sorted(counts.items()):
        measured=phi(a,b,c,d)
        distinct_dates=len(dates_by_key[key])
        eligible=n>=args.min_pairs and distinct_dates>=60 and measured is not None
        # Empirical-Bayes style shrinkage toward independence. Never extrapolate
        # from small samples: runtime may consume only eligible rows.
        shrunk=(measured*n/(n+200.0)) if measured is not None else None
        estimates[key]={
            "pairs":n,
            "distinct_settled_dates":distinct_dates,
            "minimum_distinct_dates":60,
            "phi_raw":measured,
            "phi_shrunk":shrunk,
            "eligible_for_runtime":eligible,
            "minimum_pairs":args.min_pairs,
            "contingency":{"both_hit":a,"left_only":b,"right_only":c,"neither":d},
        }

    artifact={
        "schema_version":1,
        "method":"settled_binary_pair_phi_with_200_pair_zero_shrinkage",
        "source_sha256":hashlib.sha256(raw).hexdigest(),
        "settled_legs":len(df),
        "slates":int(df["slate_id"].nunique()),
        "minimum_pairs":args.min_pairs,
        "estimates":estimates,
    }
    canonical=json.dumps(artifact,sort_keys=True,separators=(",",":")).encode()
    artifact["artifact_sha256"]=hashlib.sha256(canonical).hexdigest()
    Path(args.output).write_text(json.dumps(artifact,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
        "eligible_keys":sum(1 for x in estimates.values() if x["eligible_for_runtime"]),
        "total_keys":len(estimates),
        "settled_legs":len(df),
        "artifact_sha256":artifact["artifact_sha256"],
    },indent=2))


if __name__=="__main__":
    main()

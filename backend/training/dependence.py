from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
POLICY = json.loads((ROOT / "policy.json").read_text())


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _read(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        return pd.read_json(path, lines=True)
    return pd.read_csv(path)


def build_dependence(input_path: Path, output_path: Path) -> dict[str, Any]:
    df = _read(input_path).copy()
    required = {
        "settlement_group",
        "event_date",
        "leg_family",
        "predicted_probability",
        "outcome",
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Dependence history missing required columns: {missing}")

    df["event_date"] = pd.to_datetime(df["event_date"], utc=True, errors="raise").dt.date.astype(str)
    df["leg_family"] = df["leg_family"].astype(str)
    df["settlement_group"] = df["settlement_group"].astype(str)
    df["predicted_probability"] = pd.to_numeric(df["predicted_probability"], errors="raise")
    df["outcome"] = pd.to_numeric(df["outcome"], errors="raise").astype(int)

    if not df["predicted_probability"].between(0.0, 1.0, inclusive="both").all():
        raise ValueError("predicted_probability must be within [0,1]")
    if not df["outcome"].isin([0, 1]).all():
        raise ValueError("outcome must be binary")

    df["residual"] = df["outcome"] - df["predicted_probability"]
    grouped = (
        df.groupby(["settlement_group", "event_date", "leg_family"], as_index=False)
        .agg(outcome=("outcome", "mean"), residual=("residual", "mean"))
    )

    residual = grouped.pivot_table(
        index=["settlement_group", "event_date"],
        columns="leg_family",
        values="residual",
        aggfunc="mean",
    )
    hits = grouped.pivot_table(
        index=["settlement_group", "event_date"],
        columns="leg_family",
        values="outcome",
        aggfunc="mean",
    )

    min_obs = int(POLICY["parlay_dependence_policy"]["minimum_pair_observations"])
    min_dates = int(POLICY["parlay_dependence_policy"]["minimum_distinct_event_dates"])
    families = sorted(set(grouped["leg_family"]))
    pairs: list[dict[str, Any]] = []

    for i, left in enumerate(families):
        for right in families[i + 1 :]:
            rpair = residual[[left, right]].dropna()
            hpair = hits[[left, right]].dropna()
            if rpair.empty or hpair.empty:
                continue
            common = rpair.index.intersection(hpair.index)
            rpair = rpair.loc[common]
            hpair = hpair.loc[common]
            observations = int(len(common))
            dates = int(len({idx[1] for idx in common}))
            qualified = observations >= min_obs and dates >= min_dates

            residual_corr = None
            hit_phi = None
            if observations >= 2:
                rv = np.corrcoef(rpair[left].to_numpy(), rpair[right].to_numpy())[0, 1]
                hv = np.corrcoef(hpair[left].to_numpy(), hpair[right].to_numpy())[0, 1]
                if np.isfinite(rv):
                    residual_corr = float(rv)
                if np.isfinite(hv):
                    hit_phi = float(hv)

            pairs.append(
                {
                    "left": left,
                    "right": right,
                    "observations": observations,
                    "distinct_event_dates": dates,
                    "residual_correlation": residual_corr,
                    "hit_phi": hit_phi,
                    "qualified": bool(qualified and residual_corr is not None and hit_phi is not None),
                }
            )

    artifact = {
        "schema_version": 1,
        "method": POLICY["parlay_dependence_policy"]["method"],
        "source_sha256": _sha256_file(input_path),
        "minimum_pair_observations": min_obs,
        "minimum_distinct_event_dates": min_dates,
        "families": families,
        "pairs": pairs,
        "qualified_pair_count": int(sum(1 for pair in pairs if pair["qualified"])),
        "status": "MEASURED_DEPENDENCE_AVAILABLE"
        if any(pair["qualified"] for pair in pairs)
        else "INSUFFICIENT_SETTLED_DEPENDENCE_HISTORY",
    }
    artifact["artifact_core_sha256"] = hashlib.sha256(_canonical(artifact)).hexdigest()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="Estimate parlay dependence from settled real outcomes")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build_dependence(args.input, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["status"] == "MEASURED_DEPENDENCE_AVAILABLE" else 2)


if __name__ == "__main__":
    main()

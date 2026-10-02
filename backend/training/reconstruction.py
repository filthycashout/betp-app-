from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / 'drive_reconstruction_manifest.json'

def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text())

def verify_file(path: str | Path, expected_sha256: str) -> bool:
    return sha256_file(path) == expected_sha256

def evaluate_settled_csv(path: str | Path) -> dict[str, Any]:
    with Path(path).open(newline='', encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))
    def rate(column: str) -> float | None:
        vals = [str(r.get(column, '')).strip().lower() == 'true' for r in rows if str(r.get(column, '')).strip()]
        return sum(vals) / len(vals) if vals else None
    return {
        'resolved_games': len(rows),
        'moneyline_accuracy': rate('ML_Correct'),
        'spread_accuracy': rate('Spread_Correct'),
        'total_accuracy': rate('Total_Correct'),
        'combined_outcome_accuracy': rate('Outcome_Correct'),
        'brier': None, 'log_loss': None, 'ece': None,
        'promotion_eligible': False,
        'reason': 'No calibrated probability field is present in this settled CSV.',
    }

def canonical_pregame_filter(row: dict[str, Any]) -> bool:
    status = str(row.get('Status') or row.get('status') or '').upper()
    live_adjusted = str(row.get('Live_Adjusted') or row.get('live_adjusted') or '').strip().lower()
    return 'LIVE' not in status and live_adjusted not in {'yes', 'true', '1', 'yes (from screenshot)'}

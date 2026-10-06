"""Synthetic safety fixtures only; none of these rows enter training evidence."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import nflverse_archive_backfill as archive
from strict_promote import source_quarantine_reasons


class ArchiveEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / "raw"
        self.cache.mkdir()
        self.row = {
            "game_id": "2024_01_A_B", "season": "2024", "home_team": "B",
            "away_team": "A", "gameday": "2024-09-08", "gametime": "13:00",
            "home_moneyline": "-150", "away_moneyline": "130",
            "spread_line": "3", "total_line": "44.5",
            "home_score": "NA", "away_score": "NA", "result": "NA", "total": "NA",
        }

    def snapshots(self, pregame_scored=False):
        final = dict(self.row, home_score="24", away_score="17", result="7", total="41")
        records = [
            ("2024-09-08T12:00:00Z", final if pregame_scored else self.row),
            # A live score matching the eventual final is still inadmissible.
            ("2024-09-08T19:00:00Z", final),
            ("2024-09-15T12:00:00Z", final),
        ]
        index = []
        for n, (time, row) in enumerate(records, 1):
            commit = str(n) * 40
            path = self.cache / f"{commit}.csv"
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
            index.append({
                "sha": commit, "as_of": time, "requested_at": time,
                "raw_file": path.name, "raw_bytes": path.stat().st_size,
                "raw_sha256": archive.digest(path),
                "url": f"https://raw.githubusercontent.com/nflverse/nfldata/{commit}/data/games.csv",
            })
        path = self.root / "index.json"
        path.write_text(json.dumps(index))
        return path

    def test_delayed_score_and_pregame_features(self):
        result = archive.rebuild(self.snapshots(), self.cache, self.root / "out")
        self.assertEqual(result["rows"], 1)
        with (self.root / "out/nfl.csv").open() as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual(row["event_time"], "2024-09-08T17:00:00+00:00")
        self.assertEqual(row["label_available_at"], "2024-09-15T12:00:00+00:00")
        self.assertEqual(float(row["home_spread"]), -3)
        self.assertAlmostEqual(float(row["market_home_probability"]), 0.6 / (0.6 + 100 / 230))
        self.assertFalse(result["promotion_ready"])

    def test_pregame_score_is_excluded(self):
        result = archive.rebuild(self.snapshots(pregame_scored=True), self.cache, self.root / "out")
        self.assertEqual(result["rows"], 0)
        self.assertEqual(result["rejections_or_exclusions"]["pregame_record_contains_score"], 1)

    def test_tampered_archive_fails_checksum(self):
        index = self.snapshots()
        path = next(self.cache.glob("*.csv"))
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "checksum"):
            archive.load_snapshots(index, self.cache, False)

    def test_path_and_timezone_cannot_be_ambiguous(self):
        index = self.snapshots()
        items = json.loads(index.read_text())
        items[0]["raw_file"] = "../different.csv"
        index.write_text(json.dumps(items))
        with self.assertRaisesRegex(ValueError, "path or URL"):
            archive.load_snapshots(index, self.cache, False)
        with self.assertRaisesRegex(ValueError, "timezone"):
            archive.utc("2024-09-08T12:00:00")
        winter = dict(self.row, gameday="2024-12-08")
        self.assertEqual(archive.event_time(winter).hour, 18)

    def test_explicit_source_hold_blocks_promotion(self):
        for flag in ("promotion_ready", "promotion_eligible", "independent_publication_timestamp_verified"):
            with self.subTest(flag=flag):
                self.assertEqual(source_quarantine_reasons({flag: False}), [f"{flag}=false"])
        # Compatibility only: missing flags do not certify provenance.
        self.assertEqual(source_quarantine_reasons({}), [])


if __name__ == "__main__":
    unittest.main()

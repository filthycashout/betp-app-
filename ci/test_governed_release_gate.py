from __future__ import annotations

import json
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("governed_release_gate.py")
CRITICAL_CHECKS = set(runpy.run_path(str(SCRIPT))["CRITICAL_CHECKS"])


def promoted_row() -> dict:
    return {
        "sha256": "a" * 64,
        "promoted_artifact_loaded": True,
        "runtime_mode": "PROMOTED_TRAINED_MODEL",
        "promotion_gate": {
            "passed": True,
            "checks": {name: True for name in sorted(CRITICAL_CHECKS)},
        },
    }


class GovernedReleaseGateTests(unittest.TestCase):
    def run_gate(self, payload: dict) -> tuple[subprocess.CompletedProcess[str], dict]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "models.json"
            output = root / "report.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--model-status",
                    str(source),
                    "--output",
                    str(output),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            report = json.loads(output.read_text(encoding="utf-8"))
            return result, report

    def test_canonical_top_level_sports_pass(self) -> None:
        result, report = self.run_gate({"NFL": promoted_row(), "NBA": promoted_row()})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(report["release_gate_passed"])

    def test_superjson_nested_models_pass(self) -> None:
        payload = {"json": {"models": {"NFL": promoted_row(), "NBA": promoted_row()}}}
        result, report = self.run_gate(payload)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(report["release_gate_passed"])

    def test_any_failed_runtime_check_blocks_release(self) -> None:
        nfl = promoted_row()
        nfl["promotion_gate"]["checks"]["leakage_audit"] = False
        nfl["promotion_gate"]["passed"] = False
        result, report = self.run_gate({"NFL": nfl, "NBA": promoted_row()})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(report["release_gate_passed"])
        self.assertTrue(any("leakage_audit" in failure for failure in report["failures"]))

    def test_missing_critical_check_blocks_release(self) -> None:
        nba = promoted_row()
        del nba["promotion_gate"]["checks"]["artifact_security"]
        result, report = self.run_gate({"NFL": promoted_row(), "NBA": nba})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(report["release_gate_passed"])
        self.assertTrue(any("artifact_security" in failure for failure in report["failures"]))


if __name__ == "__main__":
    unittest.main()

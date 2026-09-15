import json
from pathlib import Path
import tempfile
import unittest

from forecast_lab_skills.core import (
    DataPoint,
    RunManifest,
    TrialLedger,
    assert_point_in_time,
    build_postmortem,
    mutation_leakage_test,
)


class ForecastLabCoreTests(unittest.TestCase):
    def test_point_in_time_rejects_future_information(self):
        records = [
            DataPoint(key="earnings", value=1, available_at="2026-01-02T09:00:00+09:00", source="test")
        ]
        with self.assertRaises(ValueError):
            assert_point_in_time(records, "2026-01-02T08:59:59+09:00")

    def test_point_in_time_accepts_available_information(self):
        records = [
            DataPoint(key="earnings", value=1, available_at="2026-01-02T09:00:00+09:00", source="test")
        ]
        assert_point_in_time(records, "2026-01-02T09:00:00+09:00")

    def test_manifest_hashes_are_stable(self):
        manifest = RunManifest.create(
            trial_id="T1",
            as_of="2026-01-02T09:00:00+09:00",
            engine_version="0.1.0",
            data_snapshot={"prices": "abc"},
            skill_versions={"pit-auditor": "0.1.0"},
            config={"b": 2, "a": 1},
            inputs={"y": 2, "x": 1},
            created_at="2026-01-02T00:00:00Z",
        )
        twin = RunManifest.create(
            trial_id="T1",
            as_of="2026-01-02T09:00:00+09:00",
            engine_version="0.1.0",
            data_snapshot={"prices": "abc"},
            skill_versions={"pit-auditor": "0.1.0"},
            config={"a": 1, "b": 2},
            inputs={"x": 1, "y": 2},
            created_at="2026-01-02T00:00:00Z",
        )
        self.assertEqual(manifest.input_sha256, twin.input_sha256)
        self.assertEqual(manifest.config_sha256, twin.config_sha256)

    def test_trial_ledger_is_append_only_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "trial-ledger.jsonl"
            ledger = TrialLedger(path)
            ledger.append({"trial_id": "T1", "created_at": "2026-01-02T00:00:00Z", "status": "failed"})
            ledger.append({"trial_id": "T2", "created_at": "2026-01-03T00:00:00Z", "status": "passed"})
            lines = path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["status"], "failed")

    def test_mutation_leakage_test(self):
        rows = [1, 2, 3, 100]

        def safe_eval(values):
            return sum(values[:3])

        def mutate_future(values):
            values[3] = -999999

        passed, before, after = mutation_leakage_test(
            baseline_input=rows,
            evaluate=safe_eval,
            mutate_future=mutate_future,
        )
        self.assertTrue(passed)
        self.assertEqual(before, after)

        def unsafe_eval(values):
            return sum(values)

        passed, _, _ = mutation_leakage_test(
            baseline_input=rows,
            evaluate=unsafe_eval,
            mutate_future=mutate_future,
        )
        self.assertFalse(passed)

    def test_postmortem_returns_and_residuals(self):
        result = build_postmortem(
            horizon_sessions=5,
            security_start=100,
            security_end=112,
            market_start=100,
            market_end=103,
            sector_start=100,
            sector_end=108,
        )
        self.assertAlmostEqual(result.raw_return_pct, 12.0)
        self.assertAlmostEqual(result.market_residual_pct, 9.0)
        self.assertAlmostEqual(result.sector_residual_pct, 4.0)
        self.assertEqual(result.label, "target_hit")


if __name__ == "__main__":
    unittest.main()

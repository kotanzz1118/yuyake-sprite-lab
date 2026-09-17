from datetime import date
import unittest

from forecast_lab_skills.audit_v2 import (
    PriceFrameMetadata,
    SecurityLifecycle,
    audit_universe_membership,
    missing_delisting_returns,
    same_universe_random_control_gate,
    top_basket_stability,
)


class ForecastLabAuditV2Tests(unittest.TestCase):
    def test_price_frame_metadata_requires_explicit_units(self):
        good = PriceFrameMetadata(
            source="test",
            adjustment_caliber="split_adjusted",
            volume_unit="shares",
            retrieved_at="2026-09-17T00:00:00Z",
        )
        good.validate()

        bad = PriceFrameMetadata(
            source="test",
            adjustment_caliber="unknown",
            volume_unit="shares",
            retrieved_at="2026-09-17T00:00:00Z",
        )
        with self.assertRaises(ValueError):
            bad.validate()

    def test_universe_audit_catches_pre_listing_and_post_delisting(self):
        lifecycle = SecurityLifecycle("1234", date(2020, 1, 10), date(2021, 12, 31))
        findings = audit_universe_membership(
            membership={
                date(2020, 1, 1): ["1234"],
                date(2020, 6, 1): ["1234"],
                date(2022, 1, 4): ["1234"],
            },
            lifecycles={"1234": lifecycle},
        )
        self.assertEqual([f.problem for f in findings], ["present_before_listing", "present_after_delisting"])

    def test_missing_delisting_returns_are_not_silently_zeroed(self):
        lifecycles = {
            "1111": SecurityLifecycle("1111", date(2019, 1, 1), date(2020, 5, 1)),
            "2222": SecurityLifecycle("2222", date(2019, 1, 1), date(2020, 6, 1)),
        }
        missing = missing_delisting_returns(
            lifecycles=lifecycles,
            delisting_returns={"1111": -35.0},
            start=date(2020, 1, 1),
            end=date(2020, 12, 31),
        )
        self.assertEqual(missing, ["2222"])

    def test_same_universe_random_control_gate(self):
        result = same_universe_random_control_gate(
            candidate_oos_metric=1.6,
            random_control_oos_metrics=[0.1, 0.4, 0.7, 0.8, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5],
            required_quantile=0.90,
        )
        self.assertTrue(result.passed)
        failed = same_universe_random_control_gate(
            candidate_oos_metric=1.2,
            random_control_oos_metrics=[0.1, 0.4, 0.7, 0.8, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5],
            required_quantile=0.90,
        )
        self.assertFalse(failed.passed)

    def test_top_basket_jaccard(self):
        result = top_basket_stability(["A", "B", "C"], ["B", "C", "D"])
        self.assertEqual(result.intersection, 2)
        self.assertEqual(result.union, 4)
        self.assertAlmostEqual(result.jaccard, 0.5)


if __name__ == "__main__":
    unittest.main()

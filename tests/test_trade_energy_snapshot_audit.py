"""Regression tests for GACC, JODI, and UN Comtrade snapshots."""

from __future__ import annotations

import unittest

from src.data.audit_github_snapshot import PROJECT_ROOT
from src.data.audit_trade_energy_snapshot import run_audit


RAW_ROOT = PROJECT_ROOT / "data" / "raw" / "trade_energy"
RAW_FILES = [
    RAW_ROOT / "gacc_2026-06_total_exports_imports_cny.xls",
    RAW_ROOT / "gacc_2026-06_major_imports_cny.xls",
    RAW_ROOT / "gacc_2026-06_major_exports_cny.xls",
    RAW_ROOT / "jodi_oil_primary_2026.csv",
    RAW_ROOT / "jodi_oil_secondary_2026.csv",
]


@unittest.skipUnless(
    all(path.exists() for path in RAW_FILES)
    and len(list((RAW_ROOT / "comtrade_hs2709").glob("*.json"))) == 27,
    "Ignored trade-energy raw snapshot is not present in this checkout.",
)
class TradeEnergySnapshotAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.summary = run_audit(write=False)
        cls.details = cls.summary["details"]

    def test_all_logical_artifacts_are_structurally_valid(self) -> None:
        self.assertEqual(5, self.summary["artifact_count"])
        self.assertEqual(5, self.summary["structure_pass_count"])
        self.assertEqual(8, self.summary["manifest_artifact_count"])

    def test_gacc_endpoint_and_title_conflict_are_explicit(self) -> None:
        june = self.details["gacc"]["june_2026"]
        self.assertAlmostEqual(28206.68965572, june["total_exports_cny_100m"])
        self.assertAlmostEqual(2927.1645658, june["crude_import_10k_tonnes"])
        self.assertEqual(
            "1-6 Total, 2024",
            self.details["gacc"]["comparison_title_conflict"],
        )

    def test_jodi_candidates_retain_negative_and_above_one_values(self) -> None:
        candidates = self.details["jodi"]["may_2026_dependency_candidates"]
        self.assertGreater(candidates["KR"]["crude_dependency"], 1)
        self.assertLess(candidates["NO"]["broad_dependency"], 0)
        self.assertTrue(
            self.details["jodi"]["india_missing_required_fields"]
        )
        self.assertEqual(
            8,
            len(self.details["jodi"]["india_missing_required_fields"]),
        )
        self.assertEqual(
            3,
            len(
                self.details["jodi"][
                    "india_internal_inconsistency_2026q1"
                ]
            ),
        )
        jodi_audit = next(
            row for row in self.summary["series"]
            if row["artifact_id"] == "JODI_OIL_DEPENDENCY_20260729"
        )
        self.assertEqual("8191", jodi_audit["negative_value_count"])
        self.assertEqual("2026-05-01", jodi_audit["min_value_date"])

    def test_comtrade_missing_countries_are_na_not_zero(self) -> None:
        detail = self.details["comtrade"]
        self.assertEqual(["NOR", "SAU"], detail["no_record_reporters"])
        self.assertEqual(
            ["GBR_2022", "GBR_2024"],
            detail["world_weight_missing"],
        )
        self.assertEqual(
            ["GBR_2022", "GBR_2024"],
            detail["partner_weight_missing"],
        )
        self.assertEqual(2, detail["partner_weight_missing_record_count"])
        self.assertEqual(
            [
                {"reporter": "GBR", "year": 2022, "partner_code": 458},
                {"reporter": "GBR", "year": 2024, "partner_code": 31},
            ],
            [
                {
                    "reporter": row["reporter"],
                    "year": row["year"],
                    "partner_code": row["partner_code"],
                }
                for row in detail["partner_weight_missing_records"]
            ],
        )
        self.assertNotIn("SAU", detail["hhi_by_reporter_year"])
        self.assertNotIn("NOR", detail["hhi_by_reporter_year"])

    def test_partial_snapshots_do_not_pass_p0(self) -> None:
        self.assertEqual(0, self.summary["p0_pass_count"])
        self.assertEqual(5, self.summary["p0_fail_count"])


if __name__ == "__main__":
    unittest.main()

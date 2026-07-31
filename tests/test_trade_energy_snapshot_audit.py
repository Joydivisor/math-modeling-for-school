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
    and len(list((RAW_ROOT / "jodi_history").glob("*/*.csv"))) == 32
    and len(
        list((RAW_ROOT / "comtrade_hs2709_history").glob("*.json"))
    ) == 153
    and len(
        list((RAW_ROOT / "comtrade_hs2709_headers").glob("*.txt"))
    ) == 153,
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
        self.assertEqual(346, self.summary["manifest_artifact_count"])

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
        panel = self.details["jodi"]["panel_summary"]
        self.assertEqual(34, self.details["jodi"]["history_file_count"])
        self.assertEqual(34, self.details["jodi"]["history_structure_pass_count"])
        self.assertEqual(110, panel["all_nine_common_complete_month_count"])
        self.assertEqual(193, panel["excluding_india_common_complete_month_count"])
        self.assertTrue(panel["eight_country_panel_feasible_at_95pct"])
        self.assertFalse(panel["full_2010_2026_panel_feasible"])
        india = next(
            row for row in self.details["jodi"]["panel_coverage"]
            if row["area"] == "IN"
        )
        self.assertEqual(111, india["both_complete_months"])
        self.assertEqual(195, india["totcrude_zero_inconsistency_count"])
        jodi_audit = next(
            row for row in self.summary["series"]
            if row["artifact_id"]
            == "JODI_OIL_DEPENDENCY_2010_2026_20260730"
        )
        self.assertEqual("584", jodi_audit["negative_value_count"])
        self.assertEqual("2024-01-01", jodi_audit["min_value_date"])
        self.assertEqual("1.000000", jodi_audit["calendar_row_coverage_ratio"])
        self.assertEqual("0.949239", jodi_audit["core_value_coverage_ratio"])
        self.assertEqual("FAIL", jodi_audit["p0_status"])

    def test_comtrade_codes_hhi_quality_and_release_lag(self) -> None:
        detail = self.details["comtrade"]
        self.assertEqual(153, detail["file_count"])
        self.assertEqual(121, detail["full_hhi_count"])
        self.assertEqual(26, len(detail["no_record_reporter_years"]))
        self.assertEqual(
            [
                "GBR_2017",
                "GBR_2018",
                "GBR_2020",
                "GBR_2022",
                "GBR_2024",
                "GBR_2025",
            ],
            detail["conditional_reporter_years"],
        )
        self.assertEqual(842, detail["reporter_area_codes"]["USA"])
        self.assertEqual(699, detail["reporter_area_codes"]["IND"])
        self.assertEqual(579, detail["reporter_area_codes"]["NOR"])
        self.assertEqual(840, detail["m49_reference_codes"]["USA"])
        self.assertEqual(356, detail["m49_reference_codes"]["IND"])
        self.assertEqual(578, detail["m49_reference_codes"]["NOR"])
        norway = detail["full_hhi_by_reporter_year"]["NOR"]
        self.assertAlmostEqual(0.466650729292109, norway["2022"])
        self.assertAlmostEqual(0.533210070268918, norway["2023"])
        self.assertAlmostEqual(0.411186265532901, norway["2024"])
        self.assertNotIn("SAU", detail["full_hhi_by_reporter_year"])
        self.assertEqual(
            ["DEU", "GBR", "IND", "JPN", "KOR", "NOR", "USA"],
            detail["available_2025_reporters"],
        )
        self.assertEqual(9, len(detail["release_lag_2026_reporters"]))
        self.assertEqual(400, detail["estimated_record_count"])
        self.assertEqual(
            {"490": 6, "899": 9},
            detail["residual_partner_code_counts"],
        )
        supplier_audit = next(
            row for row in self.summary["series"]
            if row["variable_id"] == "supplier_hhi"
        )
        self.assertEqual("121", supplier_audit["valid_count"])
        self.assertEqual("FAIL", supplier_audit["p0_status"])

    def test_partial_snapshots_do_not_pass_p0(self) -> None:
        self.assertEqual(0, self.summary["p0_pass_count"])
        self.assertEqual(5, self.summary["p0_fail_count"])


if __name__ == "__main__":
    unittest.main()

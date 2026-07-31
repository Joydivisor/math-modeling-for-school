"""Regression tests for full-area OECD snapshot auditing."""

from __future__ import annotations

import unittest

from src.data.audit_github_snapshot import PROJECT_ROOT
from src.data.audit_oecd_snapshot_v2 import run_audit


RAW_FILES = [
    PROJECT_ROOT
    / "data"
    / "raw"
    / "cross_country"
    / "oecd_peer_real_gdp_2010Q1_2026Q2_20260729.csv",
    PROJECT_ROOT
    / "data"
    / "raw"
    / "cross_country"
    / "oecd_peer_industrial_production_2010M01_2026M06_20260729.csv",
    PROJECT_ROOT
    / "data"
    / "raw"
    / "cross_country"
    / "oecd_peer_cpi_2010M01_2026M06_20260729.csv",
]


@unittest.skipUnless(
    all(path.exists() for path in RAW_FILES),
    "Ignored OECD raw snapshot is not present in this checkout.",
)
class OECDSnapshotAuditV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.summary = run_audit(write=False)
        cls.audit = {
            row["variable_id"]: row for row in cls.summary["series"]
        }
        cls.detail = {
            row["variable_id"]: row for row in cls.summary["details"]
        }

    def test_every_downloaded_area_and_row_is_audited(self) -> None:
        self.assertEqual(3, self.summary["structure_pass_count"])
        self.assertEqual(
            517,
            self.detail["peer_real_gdp"]["file_row_count"],
        )
        self.assertEqual(
            1380,
            self.detail["peer_industrial_production"]["file_row_count"],
        )
        self.assertEqual(1582, self.detail["peer_cpi"]["file_row_count"])
        self.assertEqual(
            {"CHN", "JPN", "KOR", "DEU", "USA", "IND", "GBR", "SAU"},
            set(self.detail["peer_real_gdp"]["area_ranges"]),
        )
        self.assertIn(
            "NOR",
            self.detail["peer_industrial_production"]["area_ranges"],
        )

    def test_statuses_and_methodology_are_preserved(self) -> None:
        self.assertEqual(
            {"A": 494, "P": 23},
            self.detail["peer_real_gdp"]["status_counts"],
        )
        self.assertEqual(
            {"A": 1581, "B": 1},
            self.detail["peer_cpi"]["status_counts"],
        )
        self.assertEqual(
            ["HICP"],
            self.detail["peer_cpi"]["methodology_by_area"]["DEU"],
        )
        self.assertEqual(
            ["HICP"],
            self.detail["peer_cpi"]["methodology_by_area"]["GBR"],
        )

    def test_internal_gap_is_explicit_and_prevents_p0_pass(self) -> None:
        self.assertEqual(
            ["2025-10"],
            self.detail["peer_cpi"]["interior_missing_periods_by_area"][
                "USA"
            ],
        )
        self.assertEqual("FAIL", self.audit["peer_cpi"]["p0_status"])
        self.assertEqual(
            "BLOCKED_RELEASE_LAG",
            self.audit["peer_real_gdp"]["p0_status"],
        )
        self.assertEqual(
            "BLOCKED_RELEASE_LAG",
            self.audit["peer_industrial_production"]["p0_status"],
        )

    def test_transformation_codes_match_already_transformed_values(self) -> None:
        self.assertIn(
            "year-on-year real GDP growth",
            self.audit["peer_real_gdp"]["unit"],
        )
        self.assertIn(
            "year-on-year CPI change",
            self.audit["peer_cpi"]["unit"],
        )


if __name__ == "__main__":
    unittest.main()

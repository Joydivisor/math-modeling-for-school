"""Tests for the IEA qualitative policy-coverage snapshot."""

from __future__ import annotations

import unittest

from src.data.audit_github_snapshot import PROJECT_ROOT
from src.data.audit_iea_policy_snapshot_v2 import run_audit


RAW_FILE = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "cross_country"
    / "iea_2026_energy_crisis_policy_response_20260729.js"
)


@unittest.skipUnless(
    RAW_FILE.exists(),
    "Ignored IEA raw snapshot is not present in this checkout.",
)
class IEAPolicySnapshotAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.summary = run_audit(write=False)

    def test_static_resource_structure_matches_snapshot(self) -> None:
        self.assertEqual(1, self.summary["structure_pass_count"])
        observed = {
            name: detail["row_count"]
            for name, detail in self.summary["table_details"].items()
        }
        self.assertEqual(
            {
                "energy_conservation": 59,
                "consumer_support": 93,
                "structural_policies": 29,
            },
            observed,
        )
        self.assertEqual(178, self.summary["country_table_row_count"])
        self.assertEqual(114, self.summary["distinct_country_count"])
        self.assertEqual(3, self.summary["legend_row_count"])
        self.assertEqual(800, self.summary["policy_cell_count"])
        self.assertEqual(309, self.summary["nonempty_policy_cell_count"])
        self.assertEqual(491, self.summary["null_policy_cell_count"])

    def test_qualitative_coverage_is_not_promoted_to_an_index(self) -> None:
        self.assertEqual("FAIL", self.summary["series"][0]["p0_status"])
        self.assertEqual(
            "coverage_snapshot_only",
            self.summary["semantic_disposition"],
        )


if __name__ == "__main__":
    unittest.main()

"""Tests for the NDRC refined-oil price adjustment registry."""

import unittest

from src.data.audit_ndrc_snapshot import run_audit


class NDRCSnapshotAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.summary = run_audit(write=False)

    def test_both_adjustment_series_pass_p0(self) -> None:
        self.assertEqual(2, self.summary["artifact_count"])
        self.assertEqual(2, self.summary["structure_pass_count"])
        self.assertEqual(2, self.summary["p0_pass_count"])

    def test_policy_window_checksums_match_official_pages(self) -> None:
        self.assertEqual(
            ["2026-03-23", "2026-04-07"],
            self.summary["temporary_policy_windows"],
        )
        self.assertEqual(["2026-01-06"], self.summary["zero_adjustment_windows"])

    def test_full_period_net_changes_are_reproducible(self) -> None:
        self.assertEqual(890.0, self.summary["gasoline_net_change"])
        self.assertEqual(860.0, self.summary["diesel_net_change"])


if __name__ == "__main__":
    unittest.main()

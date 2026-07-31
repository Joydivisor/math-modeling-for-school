"""Tests for the commit-pinned collaborator-data audit."""

import unittest

from src.data.audit_github_snapshot import run_audit


class GitHubSnapshotAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.summary = run_audit(write=False)

    def test_all_snapshot_artifacts_pass_structural_audit(self) -> None:
        self.assertEqual(
            self.summary["artifact_count"],
            self.summary["structure_pass_count"],
        )

    def test_snapshot_is_not_mistaken_for_full_p0_pass(self) -> None:
        self.assertEqual(0, self.summary["p0_pass_count"])
        self.assertEqual(4, self.summary["p0_blocked_count"])

    def test_all_p0_variables_receive_a_disposition(self) -> None:
        self.assertEqual(36, self.summary["p0_variable_count"])
        self.assertEqual(25, self.summary["not_acquired_count"])
        self.assertEqual(7, self.summary["derived_blocked_count"])

    def test_common_daily_windows_are_recorded(self) -> None:
        self.assertEqual(4107, self.summary["oil_common_valid_date_count"])
        self.assertEqual(4053, self.summary["all_four_common_valid_date_count"])


if __name__ == "__main__":
    unittest.main()

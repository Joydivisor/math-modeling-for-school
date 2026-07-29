"""Tests for the locally retained official EIA snapshot."""

from __future__ import annotations

import unittest

from src.data.audit_eia_gulf_pdf import audit_gulf_pdf
from src.data.audit_eia_snapshot import PROJECT_ROOT, run_audit
from src.data.run_data_audit import run_combined_audit


RAW_FILES = [
    PROJECT_ROOT / "data" / "raw" / "eia" / "WCESTUS1w.xls",
    PROJECT_ROOT / "data" / "raw" / "eia" / "STEO.zip",
    PROJECT_ROOT / "data" / "raw" / "eia" / "jul26.pdf",
]


@unittest.skipUnless(
    all(path.exists() for path in RAW_FILES),
    "Ignored EIA raw snapshot is not present in this checkout.",
)
class EIASnapshotAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bulk = run_audit(write=False)
        cls.gulf = audit_gulf_pdf(write=False)
        cls.combined = run_combined_audit(write=False)

    def test_all_eia_artifacts_are_structurally_valid(self) -> None:
        self.assertEqual(
            self.bulk["artifact_count"],
            self.bulk["structure_pass_count"],
        )
        self.assertEqual(1, self.gulf["structure_pass_count"])

    def test_release_lags_are_not_mistaken_for_p0_passes(self) -> None:
        self.assertEqual(0, self.bulk["p0_pass_count"])
        self.assertEqual(3, self.bulk["p0_blocked_count"])
        self.assertEqual(1, self.gulf["p0_blocked_count"])

    def test_combined_disposition_records_public_access_blocker(self) -> None:
        self.assertEqual(36, self.combined["p0_variable_count"])
        self.assertEqual(20, self.combined["not_acquired_count"])
        self.assertEqual(1, self.combined["external_blocked_count"])

    def test_quarterly_gulf_forecast_is_kept_separate(self) -> None:
        self.assertEqual(5.427, self.gulf["quarterly_forecasts_mbd"]["2026-Q3"])
        self.assertEqual(1.44, self.gulf["quarterly_forecasts_mbd"]["2026-Q4"])


if __name__ == "__main__":
    unittest.main()

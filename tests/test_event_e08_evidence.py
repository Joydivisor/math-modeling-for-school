"""Regression tests for the frozen E08 event-evidence chain."""

from __future__ import annotations

import unittest

from src.data.audit_event_e08_evidence import PROJECT_ROOT, run_audit


RAW_FILES = [
    PROJECT_ROOT / "data" / "raw" / "events" / "e08_centcom_dvids_20260730.html",
    PROJECT_ROOT / "data" / "raw" / "events" / "e08_iea_omr_july_2026_20260730.html",
    PROJECT_ROOT / "data" / "raw" / "events" / "e08_ap_20260730.html",
    (
        PROJECT_ROOT
        / "data"
        / "raw"
        / "events"
        / "e08_iea_omr_publication_20260730.html"
    ),
]


@unittest.skipUnless(
    all(path.exists() for path in RAW_FILES),
    "Ignored E08 source snapshots are not present in this checkout.",
)
class E08EventEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.summary = run_audit(write=False)

    def test_all_four_sources_are_hash_and_marker_verified(self) -> None:
        self.assertEqual(4, self.summary["source_count"])
        self.assertEqual(4, self.summary["source_pass_count"])
        self.assertEqual("PASS", self.summary["structure_status"])

    def test_primary_and_independent_sources_are_present(self) -> None:
        checks = self.summary["evidence_checks"]
        self.assertTrue(checks["primary_source_present"])
        self.assertTrue(checks["independent_institutional_source_present"])
        self.assertTrue(checks["independent_news_source_present"])
        self.assertTrue(checks["publication_metadata_present"])

    def test_timeline_uses_occurrence_interval_not_publication_date(self) -> None:
        self.assertEqual("2026-07-07", self.summary["date_start"])
        self.assertEqual("2026-07-08", self.summary["date_end"])
        self.assertTrue(all(self.summary["timeline_checks"].values()))


if __name__ == "__main__":
    unittest.main()
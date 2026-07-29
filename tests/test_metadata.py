"""Tests for metadata integrity."""

import unittest

from src.data.validate_metadata import collect_issues, metadata_counts


class MetadataValidationTests(unittest.TestCase):
    def test_metadata_has_no_validation_issues(self) -> None:
        issues = collect_issues()
        self.assertEqual([], [issue.render() for issue in issues])

    def test_metadata_tables_are_not_empty(self) -> None:
        for file_name, count in metadata_counts().items():
            with self.subTest(file_name=file_name):
                self.assertGreater(count, 0)


if __name__ == "__main__":
    unittest.main()

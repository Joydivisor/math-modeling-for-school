"""Validate the project's data dictionary, source registry, and event timeline."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[2]
METADATA_DIR = PROJECT_ROOT / "data" / "metadata"
DATA_CUTOFF = "2026-07-29"


EXPECTED_COLUMNS = {
    "source_registry.csv": [
        "source_id",
        "provider",
        "dataset_or_page",
        "frequency",
        "coverage",
        "access_url",
        "access_method",
        "license_or_terms",
        "priority",
        "status",
        "retrieved_at_utc",
        "notes",
    ],
    "event_timeline.csv": [
        "event_id",
        "date_start",
        "date_end",
        "event_type",
        "direction",
        "severity",
        "mechanism",
        "causal_role",
        "source_ids",
        "verification_status",
        "data_cutoff",
        "notes",
    ],
    "data_dictionary.csv": [
        "variable_id",
        "question",
        "variable_name_cn",
        "variable_name_en",
        "symbol",
        "frequency",
        "unit",
        "transform",
        "role",
        "priority",
        "source_id",
        "start_date",
        "end_date",
        "status",
        "notes",
    ],
    "download_manifest.csv": [
        "artifact_id",
        "variable_id",
        "source_id",
        "repository",
        "repository_branch",
        "repository_commit",
        "repository_blob_sha",
        "official_url",
        "download_url",
        "local_path",
        "retrieved_at_utc",
        "sha256",
        "size_bytes",
        "format",
        "underlying_provider",
        "distributor",
        "license_or_terms",
        "official_byte_identical_at_snapshot",
        "status",
        "notes",
    ],
    "audit_results.csv": [
        "variable_id",
        "artifact_id",
        "series_id",
        "snapshot_commit",
        "sha256",
        "row_count",
        "valid_count",
        "missing_marker_count",
        "invalid_row_count",
        "duplicate_date_count",
        "start_date",
        "last_calendar_row_date",
        "last_valid_date",
        "required_end_date",
        "frequency",
        "unit",
        "calendar_row_coverage_ratio",
        "core_value_coverage_ratio",
        "event_calendar_coverage_ratio",
        "event_value_coverage_ratio",
        "publication_lag_calendar_days",
        "min_value",
        "min_value_date",
        "max_value",
        "max_value_date",
        "negative_value_count",
        "structure_status",
        "p0_status",
        "notes",
    ],
    "data_availability.csv": [
        "variable_id",
        "question",
        "priority",
        "source_id",
        "artifact_id",
        "availability_status",
        "blocker",
        "next_action",
    ],
}


@dataclass(frozen=True)
class ValidationIssue:
    file_name: str
    row_number: int | None
    message: str

    def render(self) -> str:
        location = self.file_name
        if self.row_number is not None:
            location += f":{self.row_number}"
        return f"{location}: {self.message}"


def read_csv(file_name: str) -> tuple[list[str], list[dict[str, str]]]:
    path = METADATA_DIR / file_name
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def duplicate_values(rows: Iterable[dict[str, str]], key: str) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row in rows:
        value = row[key].strip()
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)


def validate_headers() -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for file_name, expected in EXPECTED_COLUMNS.items():
        path = METADATA_DIR / file_name
        if not path.exists():
            issues.append(ValidationIssue(file_name, None, "file is missing"))
            continue
        actual, _ = read_csv(file_name)
        if actual != expected:
            issues.append(
                ValidationIssue(
                    file_name,
                    1,
                    f"columns differ; expected {expected!r}, got {actual!r}",
                )
            )
    return issues


def validate_sources() -> tuple[set[str], list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    _, rows = read_csv("source_registry.csv")
    ids = {row["source_id"].strip() for row in rows}

    for value in duplicate_values(rows, "source_id"):
        issues.append(
            ValidationIssue("source_registry.csv", None, f"duplicate source_id {value}")
        )

    for row_number, row in enumerate(rows, start=2):
        source_id = row["source_id"].strip()
        if not source_id:
            issues.append(
                ValidationIssue("source_registry.csv", row_number, "empty source_id")
            )
        url = row["access_url"].strip()
        if not (is_http_url(url) or url.startswith("local://")):
            issues.append(
                ValidationIssue(
                    "source_registry.csv",
                    row_number,
                    f"invalid access_url {url!r}",
                )
            )
        if row["priority"] not in {"P0", "P1", "P2"}:
            issues.append(
                ValidationIssue(
                    "source_registry.csv",
                    row_number,
                    f"invalid priority {row['priority']!r}",
                )
            )
    return ids, issues


def validate_dictionary(source_ids: set[str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    _, rows = read_csv("data_dictionary.csv")

    for value in duplicate_values(rows, "variable_id"):
        issues.append(
            ValidationIssue("data_dictionary.csv", None, f"duplicate variable_id {value}")
        )

    for row_number, row in enumerate(rows, start=2):
        if row["source_id"] not in source_ids:
            issues.append(
                ValidationIssue(
                    "data_dictionary.csv",
                    row_number,
                    f"unknown source_id {row['source_id']!r}",
                )
            )
        if row["priority"] not in {"P0", "P1", "P2"}:
            issues.append(
                ValidationIssue(
                    "data_dictionary.csv",
                    row_number,
                    f"invalid priority {row['priority']!r}",
                )
            )
        if not row["question"].startswith("Q"):
            issues.append(
                ValidationIssue(
                    "data_dictionary.csv",
                    row_number,
                    f"question must start with Q: {row['question']!r}",
                )
            )
    return issues


def validate_timeline(source_ids: set[str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    _, rows = read_csv("event_timeline.csv")
    permitted_causal_roles = {"treatment", "outcome_marker", "control"}
    permitted_verification = {"verified", "provisional"}

    for value in duplicate_values(rows, "event_id"):
        issues.append(
            ValidationIssue("event_timeline.csv", None, f"duplicate event_id {value}")
        )

    for row_number, row in enumerate(rows, start=2):
        try:
            start = parse_iso_date(row["date_start"])
            end = parse_iso_date(row["date_end"])
            if end < start:
                issues.append(
                    ValidationIssue(
                        "event_timeline.csv",
                        row_number,
                        "date_end precedes date_start",
                    )
                )
        except ValueError as exc:
            issues.append(
                ValidationIssue(
                    "event_timeline.csv",
                    row_number,
                    f"invalid ISO date: {exc}",
                )
            )

        if row["data_cutoff"] != DATA_CUTOFF:
            issues.append(
                ValidationIssue(
                    "event_timeline.csv",
                    row_number,
                    f"data_cutoff must be {DATA_CUTOFF}",
                )
            )
        if row["causal_role"] not in permitted_causal_roles:
            issues.append(
                ValidationIssue(
                    "event_timeline.csv",
                    row_number,
                    f"invalid causal_role {row['causal_role']!r}",
                )
            )
        if row["verification_status"] not in permitted_verification:
            issues.append(
                ValidationIssue(
                    "event_timeline.csv",
                    row_number,
                    f"invalid verification_status {row['verification_status']!r}",
                )
            )
        for source_id in row["source_ids"].split("|"):
            if source_id not in source_ids:
                issues.append(
                    ValidationIssue(
                        "event_timeline.csv",
                        row_number,
                        f"unknown source_id {source_id!r}",
                    )
                )
        if row["event_type"] == "price_peak" and row["causal_role"] == "treatment":
            issues.append(
                ValidationIssue(
                    "event_timeline.csv",
                    row_number,
                    "price_peak cannot be encoded as a treatment",
                )
            )
    return issues


def validate_audit_outputs(source_ids: set[str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    _, dictionary = read_csv("data_dictionary.csv")
    _, availability = read_csv("data_availability.csv")
    _, manifest = read_csv("download_manifest.csv")
    _, audits = read_csv("audit_results.csv")

    expected_p0 = {
        row["variable_id"] for row in dictionary if row["priority"] == "P0"
    }
    available_p0 = {row["variable_id"] for row in availability}
    if expected_p0 != available_p0:
        issues.append(
            ValidationIssue(
                "data_availability.csv",
                None,
                "P0 variable disposition set differs from data_dictionary.csv",
            )
        )
    for value in duplicate_values(availability, "variable_id"):
        issues.append(
            ValidationIssue(
                "data_availability.csv",
                None,
                f"duplicate variable_id {value}",
            )
        )

    manifest_ids = {row["artifact_id"] for row in manifest}
    for value in duplicate_values(manifest, "artifact_id"):
        issues.append(
            ValidationIssue("download_manifest.csv", None, f"duplicate artifact_id {value}")
        )
    for row_number, row in enumerate(manifest, start=2):
        if row["source_id"] not in source_ids:
            issues.append(
                ValidationIssue(
                    "download_manifest.csv",
                    row_number,
                    f"unknown source_id {row['source_id']!r}",
                )
            )
        if len(row["sha256"]) != 64 or any(
            char not in "0123456789abcdef" for char in row["sha256"].lower()
        ):
            issues.append(
                ValidationIssue(
                    "download_manifest.csv", row_number, "invalid SHA-256"
                )
            )
        if not is_http_url(row["official_url"]) or not is_http_url(
            row["download_url"]
        ):
            issues.append(
                ValidationIssue(
                    "download_manifest.csv",
                    row_number,
                    "official_url and download_url must be HTTP(S)",
                )
            )
        if not row["retrieved_at_utc"] or not row["license_or_terms"]:
            issues.append(
                ValidationIssue(
                    "download_manifest.csv",
                    row_number,
                    "retrieved_at_utc and license_or_terms are required",
                )
            )
        if not (PROJECT_ROOT / row["local_path"]).exists():
            issues.append(
                ValidationIssue(
                    "download_manifest.csv",
                    row_number,
                    f"missing local artifact {row['local_path']!r}",
                )
            )

    for value in duplicate_values(audits, "artifact_id"):
        issues.append(
            ValidationIssue("audit_results.csv", None, f"duplicate artifact_id {value}")
        )
    for row_number, row in enumerate(audits, start=2):
        if row["artifact_id"] not in manifest_ids:
            issues.append(
                ValidationIssue(
                    "audit_results.csv",
                    row_number,
                    f"unknown artifact_id {row['artifact_id']!r}",
                )
            )
        if row["structure_status"] not in {"PASS", "FAIL"}:
            issues.append(
                ValidationIssue(
                    "audit_results.csv",
                    row_number,
                    f"invalid structure_status {row['structure_status']!r}",
                )
            )
        if row["p0_status"] not in {"PASS", "FAIL", "BLOCKED_RELEASE_LAG"}:
            issues.append(
                ValidationIssue(
                    "audit_results.csv",
                    row_number,
                    f"invalid p0_status {row['p0_status']!r}",
                )
            )
        for key in (
            "calendar_row_coverage_ratio",
            "core_value_coverage_ratio",
            "event_calendar_coverage_ratio",
            "event_value_coverage_ratio",
        ):
            try:
                value = float(row[key])
            except ValueError:
                value = -1.0
            if not 0.0 <= value <= 1.0:
                issues.append(
                    ValidationIssue(
                        "audit_results.csv",
                        row_number,
                        f"{key} must be between 0 and 1",
                    )
                )
    return issues


def collect_issues() -> list[ValidationIssue]:
    issues = validate_headers()
    if issues:
        return issues
    source_ids, source_issues = validate_sources()
    issues.extend(source_issues)
    issues.extend(validate_dictionary(source_ids))
    issues.extend(validate_timeline(source_ids))
    issues.extend(validate_audit_outputs(source_ids))
    return issues


def metadata_counts() -> dict[str, int]:
    return {
        file_name: len(read_csv(file_name)[1])
        for file_name in EXPECTED_COLUMNS
    }


def main() -> int:
    issues = collect_issues()
    if issues:
        print("Metadata validation failed:")
        for issue in issues:
            print(f"- {issue.render()}")
        return 1

    counts = metadata_counts()
    print("Metadata validation passed.")
    for file_name, count in counts.items():
        print(f"- {file_name}: {count} records")
    print(f"- data cutoff: {DATA_CUTOFF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

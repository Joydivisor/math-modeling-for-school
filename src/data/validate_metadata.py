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


def collect_issues() -> list[ValidationIssue]:
    issues = validate_headers()
    if issues:
        return issues
    source_ids, source_issues = validate_sources()
    issues.extend(source_issues)
    issues.extend(validate_dictionary(source_ids))
    issues.extend(validate_timeline(source_ids))
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

"""Audit commit-pinned collaborator data mirrored from official FRED series."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "github_data_snapshot.json"
METADATA_DIR = PROJECT_ROOT / "data" / "metadata"
MISSING_MARKERS = {"", ".", "NA", "NaN", "nan"}

AUDIT_COLUMNS = [
    "variable_id", "artifact_id", "series_id", "snapshot_commit", "sha256",
    "row_count", "valid_count", "missing_marker_count", "invalid_row_count",
    "duplicate_date_count", "start_date", "last_calendar_row_date",
    "last_valid_date", "required_end_date", "frequency", "unit",
    "calendar_row_coverage_ratio", "core_value_coverage_ratio",
    "event_calendar_coverage_ratio", "event_value_coverage_ratio",
    "publication_lag_calendar_days", "min_value", "min_value_date",
    "max_value", "max_value_date", "negative_value_count",
    "structure_status", "p0_status", "notes",
]
MANIFEST_COLUMNS = [
    "artifact_id", "variable_id", "source_id", "repository",
    "repository_branch", "repository_commit", "repository_blob_sha",
    "official_url", "download_url", "local_path", "retrieved_at_utc",
    "sha256", "size_bytes", "format", "underlying_provider", "distributor",
    "license_or_terms", "official_byte_identical_at_snapshot", "status", "notes",
]
AVAILABILITY_COLUMNS = [
    "variable_id", "question", "priority", "source_id", "artifact_id",
    "availability_status", "blocker", "next_action",
]


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git_blob_sha(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def weekday_count(start: date, end: date) -> int:
    if end < start:
        return 0
    return sum(
        (start + timedelta(days=offset)).weekday() < 5
        for offset in range((end - start).days + 1)
    )


def ratio(numerator: int, denominator: int) -> str:
    return "" if denominator == 0 else f"{numerator / denominator:.6f}"


def read_dictionary() -> list[dict[str, str]]:
    path = METADATA_DIR / "data_dictionary.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def audit_one(
    snapshot: dict[str, Any],
    entry: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str], set[date]]:
    path = PROJECT_ROOT / entry["path"]
    payload = path.read_bytes()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    expected_fields = ["observation_date", entry["series_id"]]
    invalid_rows: list[int] = []
    dates: list[date] = []
    valid_values: list[tuple[date, float]] = []
    missing_dates: list[date] = []

    for row_number, row in enumerate(rows, start=2):
        try:
            observation_date = date.fromisoformat(row["observation_date"])
        except (KeyError, TypeError, ValueError):
            invalid_rows.append(row_number)
            continue
        dates.append(observation_date)
        raw_value = row.get(entry["series_id"], "").strip()
        if raw_value in MISSING_MARKERS:
            missing_dates.append(observation_date)
            continue
        try:
            valid_values.append((observation_date, float(raw_value)))
        except ValueError:
            invalid_rows.append(row_number)

    unique_dates = set(dates)
    duplicate_count = len(dates) - len(unique_dates)
    strictly_increasing = all(left < right for left, right in zip(dates, dates[1:]))
    first_date = min(dates)
    last_calendar_date = max(dates)
    last_valid_date = max(item[0] for item in valid_values)
    required_end = date.fromisoformat(entry["required_end"])
    event_start = date.fromisoformat(snapshot["event_start"])
    event_end = date.fromisoformat(snapshot["event_end"])

    expected_calendar_rows = weekday_count(first_date, last_calendar_date)
    event_expected_rows = weekday_count(event_start, event_end)
    event_calendar_rows = sum(event_start <= item <= event_end for item in dates)
    event_valid_rows = sum(
        event_start <= item_date <= event_end for item_date, _ in valid_values
    )
    negative_values = sum(value < 0 for _, value in valid_values)
    minimum_date, minimum_value = min(valid_values, key=lambda item: item[1])
    maximum_date, maximum_value = max(valid_values, key=lambda item: item[1])

    byte_hash_ok = sha256_bytes(payload) == entry["sha256"]
    blob_hash_ok = git_blob_sha(payload) == entry["github_blob_sha"]
    size_ok = len(payload) == entry["size_bytes"]
    header_ok = fieldnames == expected_fields
    calendar_complete_to_last = len(rows) == expected_calendar_rows
    core_value_coverage = len(valid_values) / expected_calendar_rows
    forbidden_negative = negative_values > 0 and not entry["allow_negative"]

    structure_ok = all([
        byte_hash_ok,
        blob_hash_ok,
        size_ok,
        header_ok,
        not invalid_rows,
        duplicate_count == 0,
        strictly_increasing,
        calendar_complete_to_last,
        core_value_coverage >= snapshot["core_minimum_ratio"],
        not forbidden_negative,
    ])
    event_calendar_coverage = event_calendar_rows / event_expected_rows
    p0_ok = (
        structure_ok
        and event_calendar_coverage >= snapshot["event_minimum_ratio"]
        and last_valid_date >= required_end
    )

    if p0_ok:
        p0_status = "PASS"
        notes = "Complete through required event end; missing markers retained."
    elif structure_ok and last_valid_date < required_end:
        p0_status = "BLOCKED_RELEASE_LAG"
        notes = (
            "Structurally valid official snapshot, but the published series does not "
            "reach the event-window end; no values were imputed."
        )
    else:
        p0_status = "FAIL"
        notes = "One or more structural, hash, coverage, or sign checks failed."

    audit_row = {
        "variable_id": entry["variable_id"],
        "artifact_id": entry["artifact_id"],
        "series_id": entry["series_id"],
        "snapshot_commit": snapshot["commit_sha"],
        "sha256": sha256_bytes(payload),
        "row_count": str(len(rows)),
        "valid_count": str(len(valid_values)),
        "missing_marker_count": str(len(missing_dates)),
        "invalid_row_count": str(len(invalid_rows)),
        "duplicate_date_count": str(duplicate_count),
        "start_date": first_date.isoformat(),
        "last_calendar_row_date": last_calendar_date.isoformat(),
        "last_valid_date": last_valid_date.isoformat(),
        "required_end_date": required_end.isoformat(),
        "frequency": entry["frequency"],
        "unit": entry["unit"],
        "calendar_row_coverage_ratio": ratio(len(rows), expected_calendar_rows),
        "core_value_coverage_ratio": ratio(len(valid_values), expected_calendar_rows),
        "event_calendar_coverage_ratio": ratio(
            event_calendar_rows, event_expected_rows
        ),
        "event_value_coverage_ratio": ratio(event_valid_rows, event_expected_rows),
        "publication_lag_calendar_days": str((required_end - last_valid_date).days),
        "min_value": str(minimum_value),
        "min_value_date": minimum_date.isoformat(),
        "max_value": str(maximum_value),
        "max_value_date": maximum_date.isoformat(),
        "negative_value_count": str(negative_values),
        "structure_status": "PASS" if structure_ok else "FAIL",
        "p0_status": p0_status,
        "notes": notes,
    }
    manifest_row = {
        "artifact_id": entry["artifact_id"],
        "variable_id": entry["variable_id"],
        "source_id": entry["source_id"],
        "repository": snapshot["repository"],
        "repository_branch": snapshot["branch"],
        "repository_commit": snapshot["commit_sha"],
        "repository_blob_sha": entry["github_blob_sha"],
        "official_url": entry["official_url"],
        "download_url": entry["download_url"],
        "local_path": entry["path"],
        "retrieved_at_utc": snapshot["retrieved_at_utc"],
        "sha256": entry["sha256"],
        "size_bytes": str(entry["size_bytes"]),
        "format": "csv",
        "underlying_provider": entry["underlying_provider"],
        "distributor": entry["distributor"],
        "license_or_terms": entry["license_or_terms"],
        "official_byte_identical_at_snapshot": str(
            entry["official_byte_identical_at_snapshot"]
        ).lower(),
        "status": "audited" if structure_ok else "failed_audit",
        "notes": (
            "Commit-pinned collaborator upload; bytes matched the official FRED "
            "CSV snapshot recorded in the configuration."
        ),
    }
    return audit_row, manifest_row, {item[0] for item in valid_values}


def build_availability(
    audit_rows: list[dict[str, str]],
    entries: list[dict[str, Any]],
) -> list[dict[str, str]]:
    audit_by_variable = {row["variable_id"]: row for row in audit_rows}
    artifact_by_variable = {
        entry["variable_id"]: entry["artifact_id"] for entry in entries
    }
    rows: list[dict[str, str]] = []

    for variable in read_dictionary():
        if variable["priority"] != "P0":
            continue
        variable_id = variable["variable_id"]
        if variable_id in audit_by_variable:
            audit = audit_by_variable[variable_id]
            if audit["p0_status"] == "PASS":
                availability_status = "audited_p0_pass"
                blocker = ""
                next_action = "Freeze this artifact for the P0 snapshot."
            else:
                availability_status = "audited_blocked_release_lag"
                blocker = (
                    f"Latest valid date {audit['last_valid_date']} is earlier than "
                    f"required end {audit['required_end_date']}."
                )
                next_action = "Refresh after the next official release and rerun audit."
        elif variable["source_id"] == "SRC_DERIVED":
            availability_status = "blocked_upstream"
            blocker = "Required upstream raw variables are not all frozen."
            next_action = "Compute only after upstream files pass P0 audit."
        else:
            availability_status = "not_acquired"
            blocker = "No frozen raw artifact has been audited."
            next_action = f"Acquire and audit from {variable['source_id']}."

        rows.append({
            "variable_id": variable_id,
            "question": variable["question"],
            "priority": variable["priority"],
            "source_id": variable["source_id"],
            "artifact_id": artifact_by_variable.get(variable_id, ""),
            "availability_status": availability_status,
            "blocker": blocker,
            "next_action": next_action,
        })
    return rows


def write_csv(
    path: Path,
    fieldnames: list[str],
    rows: Iterable[dict[str, str]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run_audit(config_path: Path = DEFAULT_CONFIG, write: bool = True) -> dict[str, Any]:
    config = load_config(config_path)
    snapshot = config["snapshot"]
    entries = config["series"]
    audit_rows: list[dict[str, str]] = []
    manifest_rows: list[dict[str, str]] = []
    valid_dates: dict[str, set[date]] = {}

    for entry in entries:
        audit_row, manifest_row, dates = audit_one(snapshot, entry)
        audit_rows.append(audit_row)
        manifest_rows.append(manifest_row)
        valid_dates[entry["series_id"]] = dates

    availability_rows = build_availability(audit_rows, entries)
    oil_common = valid_dates["DCOILBRENTEU"] & valid_dates["DCOILWTICO"]
    all_common = set.intersection(*valid_dates.values())
    summary = {
        "snapshot": snapshot,
        "artifact_count": len(audit_rows),
        "structure_pass_count": sum(
            row["structure_status"] == "PASS" for row in audit_rows
        ),
        "p0_pass_count": sum(row["p0_status"] == "PASS" for row in audit_rows),
        "p0_blocked_count": sum(
            row["p0_status"].startswith("BLOCKED") for row in audit_rows
        ),
        "p0_variable_count": len(availability_rows),
        "audited_variable_count": len(audit_rows),
        "not_acquired_count": sum(
            row["availability_status"] == "not_acquired"
            for row in availability_rows
        ),
        "derived_blocked_count": sum(
            row["availability_status"] == "blocked_upstream"
            for row in availability_rows
        ),
        "oil_common_valid_date_count": len(oil_common),
        "oil_common_start": min(oil_common).isoformat(),
        "oil_common_end": max(oil_common).isoformat(),
        "all_four_common_valid_date_count": len(all_common),
        "all_four_common_start": min(all_common).isoformat(),
        "all_four_common_end": max(all_common).isoformat(),
        "series": audit_rows,
    }

    if write:
        write_csv(METADATA_DIR / "audit_results.csv", AUDIT_COLUMNS, audit_rows)
        write_csv(
            METADATA_DIR / "download_manifest.csv", MANIFEST_COLUMNS, manifest_rows
        )
        write_csv(
            METADATA_DIR / "data_availability.csv",
            AVAILABILITY_COLUMNS,
            availability_rows,
        )
        with (METADATA_DIR / "github_snapshot_audit.json").open(
            "w", encoding="utf-8"
        ) as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        with (METADATA_DIR / "checksums.sha256").open(
            "w", encoding="utf-8", newline="\n"
        ) as handle:
            for entry in entries:
                handle.write(f"{entry['sha256']}  {entry['path']}\n")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Run checks without rewriting metadata outputs.",
    )
    args = parser.parse_args()
    summary = run_audit(args.config, write=not args.check_only)
    print(f"Snapshot commit: {summary['snapshot']['commit_sha']}")
    print(f"Artifacts audited: {summary['artifact_count']}")
    print(f"Structural PASS: {summary['structure_pass_count']}")
    print(f"P0 PASS: {summary['p0_pass_count']}")
    print(f"P0 blocked: {summary['p0_blocked_count']}")
    print(f"P0 variables tracked: {summary['p0_variable_count']}")
    print(f"P0 external variables not acquired: {summary['not_acquired_count']}")
    print(f"P0 derived variables blocked upstream: {summary['derived_blocked_count']}")
    return 0 if summary["structure_pass_count"] == summary["artifact_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

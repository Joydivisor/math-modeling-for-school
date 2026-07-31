"""Audit the official NDRC refined-oil adjustment event registry."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from src.data.audit_github_snapshot import (
    AUDIT_COLUMNS,
    MANIFEST_COLUMNS,
    METADATA_DIR,
    PROJECT_ROOT,
)


DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "ndrc_data_snapshot.json"
EXPECTED_COLUMNS = [
    "window_date",
    "announcement_date",
    "effective_at",
    "gasoline_actual_cny_per_ton",
    "diesel_actual_cny_per_ton",
    "gasoline_formula_cny_per_ton",
    "diesel_formula_cny_per_ton",
    "formula_disclosure_type",
    "zero_adjustment",
    "threshold_carryover",
    "temporary_policy_buffer",
    "gasoline_policy_wedge",
    "diesel_policy_wedge",
    "gasoline_execution_ratio",
    "diesel_execution_ratio",
    "announcement_url",
    "supporting_url",
    "source_html_sha256",
    "supporting_html_sha256",
    "license_note",
]


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_hash(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def parse_bool(value: str) -> bool:
    if value not in {"true", "false"}:
        raise ValueError(f"Invalid boolean marker {value!r}")
    return value == "true"


def logical_manifest(
    config: dict[str, Any],
    logical: dict[str, str],
    digest: str,
    integrity_ok: bool,
) -> dict[str, str]:
    snapshot = config["snapshot"]
    artifact = config["artifact"]
    return {
        "artifact_id": logical["artifact_id"],
        "variable_id": logical["variable_id"],
        "source_id": logical["source_id"],
        "repository": "Joydivisor/math-modeling-for-school",
        "repository_branch": "agent/data-pipeline",
        "repository_commit": "",
        "repository_blob_sha": "",
        "official_url": artifact["official_url"],
        "download_url": artifact["download_url"],
        "local_path": artifact["path"],
        "retrieved_at_utc": snapshot["retrieved_at_utc"],
        "sha256": digest,
        "size_bytes": str(artifact["size_bytes"]),
        "format": artifact["format"],
        "underlying_provider": "National Development and Reform Commission",
        "distributor": "Project-structured facts from official NDRC pages",
        "license_or_terms": artifact["license_or_terms"],
        "official_byte_identical_at_snapshot": "false",
        "status": "audited",
        "notes": (
            "Structured factual registry; each row retains the official page URL "
            "and SHA-256 of the downloaded HTML. Raw copyrighted pages are ignored."
            if integrity_ok
            else "Structured registry failed its integrity audit."
        ),
    }


def run_audit(
    config_path: Path = DEFAULT_CONFIG,
    write: bool = True,
) -> dict[str, Any]:
    config = load_config(config_path)
    snapshot = config["snapshot"]
    artifact = config["artifact"]
    expected = config["expected"]
    path = PROJECT_ROOT / artifact["path"]
    digest = sha256_file(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows = list(reader)

    invalid_count = 0
    parsed_dates: list[date] = []
    gasoline: list[tuple[date, float]] = []
    diesel: list[tuple[date, float]] = []
    temporary_dates: list[str] = []
    zero_dates: list[str] = []
    utc_plus_eight = timezone(timedelta(hours=8))

    for row in rows:
        try:
            window = date.fromisoformat(row["window_date"])
            announcement = date.fromisoformat(row["announcement_date"])
            gas_value = float(row["gasoline_actual_cny_per_ton"])
            diesel_value = float(row["diesel_actual_cny_per_ton"])
            zero = parse_bool(row["zero_adjustment"])
            carryover = parse_bool(row["threshold_carryover"])
            temporary = parse_bool(row["temporary_policy_buffer"])
            if window != announcement:
                raise ValueError("Window and announcement dates differ")
            if not valid_hash(row["source_html_sha256"]):
                raise ValueError("Invalid source HTML hash")
            if row["supporting_url"] and not valid_hash(
                row["supporting_html_sha256"]
            ):
                raise ValueError("Missing supporting-page hash")
            if zero:
                zero_dates.append(window.isoformat())
                if gas_value != 0 or diesel_value != 0 or not carryover:
                    raise ValueError("Zero-adjustment semantics failed")
                if row["effective_at"]:
                    raise ValueError("Zero adjustment must not invent an effective time")
            else:
                expected_effective = datetime.combine(
                    window + timedelta(days=1),
                    time.min,
                    tzinfo=utc_plus_eight,
                )
                if datetime.fromisoformat(row["effective_at"]) != expected_effective:
                    raise ValueError("Effective timestamp is not announcement 24:00")
            if temporary:
                temporary_dates.append(window.isoformat())
                gas_formula = float(row["gasoline_formula_cny_per_ton"])
                diesel_formula = float(row["diesel_formula_cny_per_ton"])
                if float(row["gasoline_policy_wedge"]) != gas_formula - gas_value:
                    raise ValueError("Gasoline policy wedge failed")
                if float(row["diesel_policy_wedge"]) != diesel_formula - diesel_value:
                    raise ValueError("Diesel policy wedge failed")
                if abs(
                    float(row["gasoline_execution_ratio"])
                    - gas_value / gas_formula
                ) > 1e-9:
                    raise ValueError("Gasoline execution ratio failed")
                if abs(
                    float(row["diesel_execution_ratio"])
                    - diesel_value / diesel_formula
                ) > 1e-9:
                    raise ValueError("Diesel execution ratio failed")
            parsed_dates.append(window)
            gasoline.append((window, gas_value))
            diesel.append((window, diesel_value))
        except (KeyError, TypeError, ValueError):
            invalid_count += 1

    duplicate_count = len(parsed_dates) - len(set(parsed_dates))
    ordered = all(
        left < right for left, right in zip(parsed_dates, parsed_dates[1:])
    )
    integrity_ok = all(
        [
            columns == EXPECTED_COLUMNS,
            digest == artifact["sha256"],
            path.stat().st_size == artifact["size_bytes"],
            len(rows) == snapshot["adjustment_windows"],
            invalid_count == 0,
            duplicate_count == 0,
            ordered,
            min(parsed_dates).isoformat() == expected["first_window"],
            max(parsed_dates).isoformat() == expected["last_window_at_cutoff"],
            temporary_dates == expected["temporary_policy_windows"],
            zero_dates == expected["zero_adjustment_windows"],
            sum(value for _, value in gasoline) == expected["gasoline_net_change"],
            sum(value for _, value in diesel) == expected["diesel_net_change"],
        ]
    )

    audit_rows: list[dict[str, str]] = []
    manifest_rows: list[dict[str, str]] = []
    for logical in config["logical_artifacts"]:
        values = (
            gasoline
            if logical["value_column"].startswith("gasoline")
            else diesel
        )
        minimum_date, minimum_value = min(values, key=lambda item: item[1])
        maximum_date, maximum_value = max(values, key=lambda item: item[1])
        audit_rows.append(
            {
                "variable_id": logical["variable_id"],
                "artifact_id": logical["artifact_id"],
                "series_id": logical["series_id"],
                "snapshot_commit": "",
                "sha256": digest,
                "row_count": str(len(rows)),
                "valid_count": str(len(values)),
                "missing_marker_count": "0",
                "invalid_row_count": str(invalid_count),
                "duplicate_date_count": str(duplicate_count),
                "start_date": min(parsed_dates).isoformat(),
                "last_calendar_row_date": max(parsed_dates).isoformat(),
                "last_valid_date": max(parsed_dates).isoformat(),
                "required_end_date": snapshot["data_cutoff"],
                "frequency": "event",
                "unit": "CNY per tonne",
                "calendar_row_coverage_ratio": "1.000000",
                "core_value_coverage_ratio": "1.000000",
                "event_calendar_coverage_ratio": "1.000000",
                "event_value_coverage_ratio": "1.000000",
                "publication_lag_calendar_days": "0",
                "min_value": str(minimum_value),
                "min_value_date": minimum_date.isoformat(),
                "max_value": str(maximum_value),
                "max_value_date": maximum_date.isoformat(),
                "negative_value_count": str(
                    sum(value < 0 for _, value in values)
                ),
                "structure_status": "PASS" if integrity_ok else "FAIL",
                "p0_status": "PASS" if integrity_ok else "FAIL",
                "notes": (
                    "All official NDRC adjustment windows at or before the cutoff "
                    "are registered. Announcement date and effective time are "
                    "separate; undisclosed formula values remain blank."
                ),
            }
        )
        manifest_rows.append(
            logical_manifest(config, logical, digest, integrity_ok)
        )

    summary = {
        "snapshot": snapshot,
        "artifact_count": len(audit_rows),
        "structure_pass_count": sum(
            row["structure_status"] == "PASS" for row in audit_rows
        ),
        "p0_pass_count": sum(row["p0_status"] == "PASS" for row in audit_rows),
        "gasoline_net_change": sum(value for _, value in gasoline),
        "diesel_net_change": sum(value for _, value in diesel),
        "temporary_policy_windows": temporary_dates,
        "zero_adjustment_windows": zero_dates,
        "series": audit_rows,
        "manifest": manifest_rows,
        "audit_columns": AUDIT_COLUMNS,
        "manifest_columns": MANIFEST_COLUMNS,
    }
    if write:
        with (METADATA_DIR / "ndrc_snapshot_audit.json").open(
            "w", encoding="utf-8"
        ) as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    summary = run_audit(args.config, write=not args.check_only)
    print(f"NDRC logical artifacts audited: {summary['artifact_count']}")
    print(f"Structural PASS: {summary['structure_pass_count']}")
    print(f"P0 PASS: {summary['p0_pass_count']}")
    print(f"Gasoline net change: {summary['gasoline_net_change']}")
    print(f"Diesel net change: {summary['diesel_net_change']}")
    return (
        0
        if summary["structure_pass_count"] == summary["artifact_count"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())

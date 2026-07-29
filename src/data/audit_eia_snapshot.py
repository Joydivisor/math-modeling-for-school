"""Audit the commit-independent EIA raw snapshot used by the Q1 data gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.data.audit_github_snapshot import AUDIT_COLUMNS, MANIFEST_COLUMNS, ratio


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "eia_data_snapshot.json"
METADATA_DIR = PROJECT_ROOT / "data" / "metadata"


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def friday_count(start: date, end: date) -> int:
    if end < start:
        return 0
    return sum(
        (start + timedelta(days=offset)).weekday() == 4
        for offset in range((end - start).days + 1)
    )


def month_range(start: str, end: str) -> list[str]:
    start_year, start_month = map(int, start.split("-"))
    end_year, end_month = map(int, end.split("-"))
    result: list[str] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return result


def normalize_month(period: str) -> str:
    return f"{period[:4]}-{period[4:6]}"


def month_as_date(period: str) -> date:
    normalized = normalize_month(period) if "-" not in period else period
    return date.fromisoformat(f"{normalized}-01")


def validate_artifact(entry: dict[str, Any]) -> tuple[Path, str, bool]:
    path = PROJECT_ROOT / entry["path"]
    if not path.exists():
        raise FileNotFoundError(
            f"Missing ignored raw artifact {entry['path']}; download it from "
            f"{entry['download_url']} before rerunning this component audit."
        )
    digest = sha256_file(path)
    valid = digest == entry["sha256"] and path.stat().st_size == entry["size_bytes"]
    return path, digest, valid


def manifest_row(
    *,
    artifact_id: str,
    variable_id: str,
    source_id: str,
    artifact: dict[str, Any],
    snapshot: dict[str, Any],
    digest: str,
    integrity_ok: bool,
    notes: str,
) -> dict[str, str]:
    return {
        "artifact_id": artifact_id,
        "variable_id": variable_id,
        "source_id": source_id,
        "repository": "",
        "repository_branch": "",
        "repository_commit": "",
        "repository_blob_sha": "",
        "official_url": artifact["official_url"],
        "download_url": artifact["download_url"],
        "local_path": artifact["path"],
        "retrieved_at_utc": snapshot["retrieved_at_utc"],
        "sha256": digest,
        "size_bytes": str(artifact["size_bytes"]),
        "format": artifact["format"],
        "underlying_provider": "U.S. Energy Information Administration",
        "distributor": "U.S. Energy Information Administration",
        "license_or_terms": artifact["license_or_terms"],
        "official_byte_identical_at_snapshot": str(integrity_ok).lower(),
        "status": (
            "audited_external_not_committed"
            if integrity_ok
            else "failed_audit"
        ),
        "notes": notes,
    }


def audit_inventory(
    config: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    try:
        import xlrd
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "xlrd is required to audit the legacy EIA XLS workbook; "
            "install the project requirements first."
        ) from exc

    snapshot = config["snapshot"]
    entry = config["artifacts"]["inventory"]
    path, digest, artifact_ok = validate_artifact(entry)
    workbook = xlrd.open_workbook(path)
    sheet = workbook.sheet_by_name("Data 1")

    source_key_ok = sheet.cell_value(1, 1).strip() == entry["series_id"]
    title = str(sheet.cell_value(2, 1))
    unit_ok = entry["unit"].lower() in title.lower()
    observations: list[tuple[date, float]] = []
    invalid_count = 0
    for row_index in range(3, sheet.nrows):
        try:
            observed = xlrd.xldate_as_datetime(
                sheet.cell_value(row_index, 0), workbook.datemode
            ).date()
            value = float(sheet.cell_value(row_index, 1))
        except (TypeError, ValueError, xlrd.XLRDError):
            invalid_count += 1
            continue
        if observed >= date(2010, 1, 1):
            observations.append((observed, value))

    dates = [item[0] for item in observations]
    values = [item[1] for item in observations]
    unique_dates = set(dates)
    duplicate_count = len(dates) - len(unique_dates)
    start_date = min(dates)
    last_date = max(dates)
    expected_core = friday_count(start_date, last_date)
    event_start = date.fromisoformat("2026-02-28")
    required_end = date.fromisoformat(entry["required_end"])
    expected_event = friday_count(event_start, required_end)
    event_rows = sum(event_start <= item <= required_end for item in dates)
    minimum = min(observations, key=lambda item: item[1])
    maximum = max(observations, key=lambda item: item[1])

    structure_ok = all(
        [
            artifact_ok,
            source_key_ok,
            unit_ok,
            invalid_count == 0,
            duplicate_count == 0,
            all(item.weekday() == 4 for item in dates),
            len(observations) == expected_core,
        ]
    )
    p0_status = (
        "PASS"
        if structure_ok and last_date >= required_end
        else "BLOCKED_RELEASE_LAG"
        if structure_ok
        else "FAIL"
    )
    notes = (
        "Official weekly commercial crude stocks excluding SPR. Raw values are "
        "thousand barrels and must be divided by 1,000 for the dictionary unit "
        "million barrels. The snapshot is structurally complete through its last "
        "published Friday but is not published through the data cutoff."
    )
    audit = {
        "variable_id": entry["variable_id"],
        "artifact_id": entry["artifact_id"],
        "series_id": entry["series_id"],
        "snapshot_commit": "",
        "sha256": digest,
        "row_count": str(len(observations)),
        "valid_count": str(len(observations)),
        "missing_marker_count": "0",
        "invalid_row_count": str(invalid_count),
        "duplicate_date_count": str(duplicate_count),
        "start_date": start_date.isoformat(),
        "last_calendar_row_date": last_date.isoformat(),
        "last_valid_date": last_date.isoformat(),
        "required_end_date": required_end.isoformat(),
        "frequency": "weekly",
        "unit": "thousand barrels",
        "calendar_row_coverage_ratio": ratio(len(observations), expected_core),
        "core_value_coverage_ratio": ratio(len(observations), expected_core),
        "event_calendar_coverage_ratio": ratio(event_rows, expected_event),
        "event_value_coverage_ratio": ratio(event_rows, expected_event),
        "publication_lag_calendar_days": str((required_end - last_date).days),
        "min_value": str(min(values)),
        "min_value_date": minimum[0].isoformat(),
        "max_value": str(max(values)),
        "max_value_date": maximum[0].isoformat(),
        "negative_value_count": str(sum(value < 0 for value in values)),
        "structure_status": "PASS" if structure_ok else "FAIL",
        "p0_status": p0_status,
        "notes": notes,
    }
    manifest = manifest_row(
        artifact_id=entry["artifact_id"],
        variable_id=entry["variable_id"],
        source_id=entry["source_id"],
        artifact=entry,
        snapshot=snapshot,
        digest=digest,
        integrity_ok=artifact_ok,
        notes=(
            "Direct official EIA XLS download. The ignored raw file is identified "
            "by retrieval time, byte size, and SHA-256."
        ),
    )
    return audit, manifest


def read_steo_series(
    path: Path,
    requested_ids: set[str],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(path) as archive:
        with archive.open("STEO.txt") as handle:
            for payload in handle:
                record = json.loads(payload)
                series_id = record.get("series_id")
                if series_id in requested_ids:
                    result[series_id] = record
    return result


def audit_steo_series(
    *,
    config: dict[str, Any],
    entry: dict[str, Any],
    artifact: dict[str, Any],
    digest: str,
    artifact_ok: bool,
    record: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    snapshot = config["snapshot"]
    definition_mismatch = entry.get("definition_mismatch", "")
    core_start = (
        snapshot["event_start_month"]
        if definition_mismatch
        else snapshot["core_start_month"]
    )
    required_month = entry["required_end"][:7]
    expected_months = month_range(core_start, required_month)
    event_months = month_range(
        snapshot["event_start_month"], snapshot["event_end_month"]
    )

    values_by_month: dict[str, float] = {}
    invalid_count = 0
    for period, raw_value in record.get("data", []):
        if len(period) != 6 or not period.isdigit():
            continue
        normalized = normalize_month(period)
        if not (core_start <= normalized <= required_month):
            continue
        try:
            values_by_month[normalized] = float(raw_value)
        except (TypeError, ValueError):
            invalid_count += 1

    last_historical_period = str(record["lastHistoricalPeriod"])
    last_historical_month = normalize_month(last_historical_period)
    historical_months = {
        month
        for month in values_by_month
        if month <= last_historical_month
    }
    available_event_months = set(values_by_month) & set(event_months)
    historical_event_months = historical_months & set(event_months)
    values = list(values_by_month.values())
    minimum_month, minimum_value = min(
        values_by_month.items(), key=lambda item: item[1]
    )
    maximum_month, maximum_value = max(
        values_by_month.items(), key=lambda item: item[1]
    )

    metadata_ok = all(
        [
            record.get("name") == entry["expected_name"],
            record.get("units") == entry["unit"],
            record.get("f") == "M",
        ]
    )
    structure_ok = artifact_ok and metadata_ok and invalid_count == 0
    event_calendar_ratio = ratio(
        len(available_event_months), len(event_months)
    )
    event_historical_ratio = ratio(
        len(historical_event_months), len(event_months)
    )
    if definition_mismatch:
        p0_status = "FAIL"
        notes = (
            f"Definition mismatch: {definition_mismatch} The candidate is retained "
            "as audit evidence and must not be relabeled as Gulf shut-ins."
        )
    elif structure_ok and last_historical_month >= required_month:
        p0_status = "PASS"
        notes = "Official EIA monthly series is historical through the required month."
    elif structure_ok:
        p0_status = "BLOCKED_RELEASE_LAG"
        notes = (
            f"Official EIA bulk series is complete as a published vintage, but "
            f"lastHistoricalPeriod={last_historical_period}; later values through "
            f"{required_month} are estimates or forecasts and are not counted as "
            "observed event-period coverage."
        )
    else:
        p0_status = "FAIL"
        notes = "Artifact hash, series metadata, or numeric parsing failed."

    last_calendar_month = max(values_by_month)
    last_historical_date = month_as_date(last_historical_month)
    required_date = date.fromisoformat(entry["required_end"])
    audit = {
        "variable_id": entry["variable_id"],
        "artifact_id": entry["artifact_id"],
        "series_id": entry["series_id"],
        "snapshot_commit": "",
        "sha256": digest,
        "row_count": str(len(values_by_month)),
        "valid_count": str(len(values_by_month)),
        "missing_marker_count": str(
            len(set(expected_months) - set(values_by_month))
        ),
        "invalid_row_count": str(invalid_count),
        "duplicate_date_count": "0",
        "start_date": month_as_date(min(values_by_month)).isoformat(),
        "last_calendar_row_date": month_as_date(last_calendar_month).isoformat(),
        "last_valid_date": last_historical_date.isoformat(),
        "required_end_date": required_date.isoformat(),
        "frequency": "monthly",
        "unit": entry["unit"],
        "calendar_row_coverage_ratio": ratio(
            len(values_by_month), len(expected_months)
        ),
        "core_value_coverage_ratio": ratio(
            len(values_by_month), len(expected_months)
        ),
        "event_calendar_coverage_ratio": event_calendar_ratio,
        "event_value_coverage_ratio": event_historical_ratio,
        "publication_lag_calendar_days": str(
            max(0, (required_date - last_historical_date).days)
        ),
        "min_value": str(minimum_value),
        "min_value_date": month_as_date(minimum_month).isoformat(),
        "max_value": str(maximum_value),
        "max_value_date": month_as_date(maximum_month).isoformat(),
        "negative_value_count": str(sum(value < 0 for value in values)),
        "structure_status": "PASS" if structure_ok else "FAIL",
        "p0_status": p0_status,
        "notes": notes,
    }
    manifest = manifest_row(
        artifact_id=entry["artifact_id"],
        variable_id=entry["variable_id"],
        source_id=entry["source_id"],
        artifact=artifact,
        snapshot=snapshot,
        digest=digest,
        integrity_ok=artifact_ok,
        notes=(
            f"Logical series {entry['series_id']} extracted from the official EIA "
            "STEO bulk ZIP; the same physical ZIP is referenced by multiple "
            "logical audit artifacts."
        ),
    )
    return audit, manifest


def run_audit(
    config_path: Path = DEFAULT_CONFIG,
    write: bool = True,
) -> dict[str, Any]:
    config = load_config(config_path)
    inventory_audit, inventory_manifest = audit_inventory(config)

    steo_artifact = config["artifacts"]["steo_bulk"]
    steo_path, steo_digest, steo_ok = validate_artifact(steo_artifact)
    requested_ids = {entry["series_id"] for entry in config["series"]}
    records = read_steo_series(steo_path, requested_ids)
    missing_ids = requested_ids - set(records)
    if missing_ids:
        raise KeyError(f"Missing requested STEO series: {sorted(missing_ids)}")

    audit_rows = [inventory_audit]
    manifest_rows = [inventory_manifest]
    for entry in config["series"]:
        audit, manifest = audit_steo_series(
            config=config,
            entry=entry,
            artifact=steo_artifact,
            digest=steo_digest,
            artifact_ok=steo_ok,
            record=records[entry["series_id"]],
        )
        audit_rows.append(audit)
        manifest_rows.append(manifest)

    summary = {
        "snapshot": config["snapshot"],
        "artifact_count": len(audit_rows),
        "structure_pass_count": sum(
            row["structure_status"] == "PASS" for row in audit_rows
        ),
        "p0_pass_count": sum(row["p0_status"] == "PASS" for row in audit_rows),
        "p0_blocked_count": sum(
            row["p0_status"] == "BLOCKED_RELEASE_LAG" for row in audit_rows
        ),
        "p0_fail_count": sum(row["p0_status"] == "FAIL" for row in audit_rows),
        "series": audit_rows,
        "manifest": manifest_rows,
        "audit_columns": AUDIT_COLUMNS,
        "manifest_columns": MANIFEST_COLUMNS,
    }
    if write:
        with (METADATA_DIR / "eia_snapshot_audit.json").open(
            "w", encoding="utf-8"
        ) as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Run checks without rewriting the component audit JSON.",
    )
    args = parser.parse_args()
    summary = run_audit(args.config, write=not args.check_only)
    print(f"EIA logical artifacts audited: {summary['artifact_count']}")
    print(f"Structural PASS: {summary['structure_pass_count']}")
    print(f"P0 PASS: {summary['p0_pass_count']}")
    print(f"P0 blocked by release lag: {summary['p0_blocked_count']}")
    print(f"P0 definition failures: {summary['p0_fail_count']}")
    return (
        0
        if summary["structure_pass_count"] == summary["artifact_count"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())

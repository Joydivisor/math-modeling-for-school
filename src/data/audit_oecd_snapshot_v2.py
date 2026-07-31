"""Audit every area and status field in the OECD peer-country snapshots."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from src.data.audit_github_snapshot import (
    AUDIT_COLUMNS,
    MANIFEST_COLUMNS,
    METADATA_DIR,
    PROJECT_ROOT,
    ratio,
)


DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "oecd_data_snapshot_v2.json"


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def period_range(start: str, end: str, frequency: str) -> list[str]:
    if frequency == "monthly":
        year, month = map(int, start.split("-"))
        end_year, end_month = map(int, end.split("-"))
        periods: list[str] = []
        while (year, month) <= (end_year, end_month):
            periods.append(f"{year:04d}-{month:02d}")
            month += 1
            if month == 13:
                year += 1
                month = 1
        return periods
    start_year, start_quarter = start.split("-Q")
    end_year, end_quarter = end.split("-Q")
    year, quarter = int(start_year), int(start_quarter)
    periods = []
    while (year, quarter) <= (int(end_year), int(end_quarter)):
        periods.append(f"{year:04d}-Q{quarter}")
        quarter += 1
        if quarter == 5:
            year += 1
            quarter = 1
    return periods


def period_date(period: str) -> date:
    if "-Q" in period:
        year_text, quarter_text = period.split("-Q")
        return date(int(year_text), 1 + (int(quarter_text) - 1) * 3, 1)
    year_text, month_text = period.split("-")
    return date(int(year_text), int(month_text), 1)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_one(
    snapshot: dict[str, Any],
    entry: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str], dict[str, Any]]:
    path = PROJECT_ROOT / entry["path"]
    if not path.exists():
        raise FileNotFoundError(
            f"Missing ignored OECD raw file {entry['path']}; rerun the "
            "official SDMX download before this component audit."
        )
    digest = sha256_file(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows = list(reader)

    expected_areas = entry["expected_areas"]
    core_areas = snapshot["core_areas"]
    observations: dict[tuple[str, str], float] = {}
    periods_by_area: dict[str, set[str]] = {
        area: set() for area in expected_areas
    }
    blank_value_periods: dict[str, list[str]] = defaultdict(list)
    methodology_by_area: dict[str, set[str]] = defaultdict(set)
    status_periods: dict[str, list[dict[str, str]]] = defaultdict(list)
    status_counts: Counter[str] = Counter()
    invalid_value_count = 0
    duplicate_key_count = 0
    filter_mismatch_count = 0
    unexpected_area_count = 0

    for row in rows:
        area = row.get("REF_AREA", "")
        period = row.get("TIME_PERIOD", "")
        if area not in expected_areas:
            unexpected_area_count += 1
            continue
        if any(
            row.get(key) != expected
            for key, expected in entry["filters"].items()
        ):
            filter_mismatch_count += 1
        if "METHODOLOGY" in columns:
            methodology_by_area[area].add(row.get("METHODOLOGY", ""))
        status = row.get("OBS_STATUS", "")
        status_counts[status] += 1
        if status not in {"", "A"}:
            status_periods[status].append(
                {"area": area, "period": period}
            )
        if row.get("OBS_VALUE", "") == "":
            blank_value_periods[area].append(period)
            continue
        try:
            value = float(row["OBS_VALUE"])
        except (KeyError, TypeError, ValueError):
            invalid_value_count += 1
            continue
        key = (area, period)
        if key in observations:
            duplicate_key_count += 1
            continue
        observations[key] = value
        periods_by_area[area].add(period)

    expected_periods_by_area = {
        area: period_range(
            entry["area_start_periods"][area],
            entry["required_end_period"],
            entry["frequency"],
        )
        for area in expected_areas
    }
    interior_missing: dict[str, list[str]] = {}
    right_edge_missing: dict[str, list[str]] = {}
    for area, expected_periods in expected_periods_by_area.items():
        observed_periods = periods_by_area[area]
        if not observed_periods:
            interior_missing[area] = []
            right_edge_missing[area] = expected_periods
            continue
        last_observed = max(observed_periods)
        interior_missing[area] = [
            period
            for period in expected_periods
            if period <= last_observed and period not in observed_periods
        ]
        right_edge_missing[area] = [
            period
            for period in expected_periods
            if period > last_observed
        ]

    common_periods = set.intersection(
        *(periods_by_area[area] for area in core_areas)
    )
    latest_common = max(common_periods)
    required_period = entry["required_end_period"]
    required_period_area_count = sum(
        required_period in periods_by_area[area] for area in core_areas
    )
    expected_pair_count = sum(
        len(periods) for periods in expected_periods_by_area.values()
    )
    observed_expected_count = sum(
        len(set(periods) & periods_by_area[area])
        for area, periods in expected_periods_by_area.items()
    )
    observed_methodology = {
        area: sorted(values)
        for area, values in methodology_by_area.items()
    }
    expected_methodology = entry.get("expected_methodology_by_area")
    methodology_ok = (
        expected_methodology is None
        or observed_methodology == expected_methodology
    )
    expected_interior = {
        area: periods
        for area, periods in entry.get(
            "expected_interior_missing_by_area", {}
        ).items()
    }
    observed_interior_nonempty = {
        area: periods
        for area, periods in interior_missing.items()
        if periods
    }
    known_missing_ok = observed_interior_nonempty == expected_interior
    required_columns = {
        "REF_AREA",
        "TIME_PERIOD",
        "OBS_VALUE",
        "OBS_STATUS",
    } | set(entry["filters"])
    structure_ok = all(
        [
            digest == entry["sha256"],
            path.stat().st_size == entry["size_bytes"],
            len(rows) == entry["expected_file_row_count"],
            required_columns.issubset(columns),
            set(periods_by_area) == set(expected_areas),
            all(periods_by_area.values()),
            invalid_value_count == 0,
            duplicate_key_count == 0,
            filter_mismatch_count == 0,
            unexpected_area_count == 0,
            dict(status_counts) == entry["expected_status_counts"],
            methodology_ok,
            known_missing_ok,
        ]
    )
    core_interior_missing = any(
        interior_missing[area] for area in core_areas
    )
    core_blank_values = any(
        blank_value_periods[area] for area in core_areas
    )
    if not structure_ok or core_interior_missing or core_blank_values:
        p0_status = "FAIL"
    elif required_period_area_count == len(core_areas):
        p0_status = "PASS"
    else:
        p0_status = "BLOCKED_RELEASE_LAG"

    values = list(observations.values())
    minimum_key, minimum_value = min(
        observations.items(), key=lambda item: item[1]
    )
    maximum_key, maximum_value = max(
        observations.items(), key=lambda item: item[1]
    )
    notes = (
        f"Official OECD SDMX snapshot; all requested areas were audited. "
        f"Core peer areas are {'|'.join(core_areas)} and their latest common "
        f"period is {latest_common}. Interior missing periods and right-edge "
        "release lags are reported separately; raw order is not assumed."
    )
    if entry["variable_id"] == "peer_real_gdp":
        notes += (
            " Values are already year-on-year real GDP growth; provisional "
            "periods are retained and must not be treated as final."
        )
    if entry["variable_id"] == "peer_cpi":
        notes += (
            " Values are already year-on-year inflation. Germany and the "
            "United Kingdom use HICP; other areas use national CPI. USA "
            "2025-10 is an absent row and must remain missing."
        )

    audit = {
        "variable_id": entry["variable_id"],
        "artifact_id": entry["artifact_id"],
        "series_id": entry["series_id"],
        "snapshot_commit": "",
        "sha256": digest,
        "row_count": str(len(rows)),
        "valid_count": str(len(observations)),
        "missing_marker_count": str(
            sum(len(periods) for periods in blank_value_periods.values())
        ),
        "invalid_row_count": str(
            invalid_value_count
            + filter_mismatch_count
            + unexpected_area_count
        ),
        "duplicate_date_count": str(duplicate_key_count),
        "start_date": period_date(
            min(period for _, period in observations)
        ).isoformat(),
        "last_calendar_row_date": period_date(
            max(period for _, period in observations)
        ).isoformat(),
        "last_valid_date": period_date(latest_common).isoformat(),
        "required_end_date": period_date(required_period).isoformat(),
        "frequency": entry["frequency"],
        "unit": entry["unit"],
        "calendar_row_coverage_ratio": ratio(
            observed_expected_count,
            expected_pair_count,
        ),
        "core_value_coverage_ratio": ratio(
            sum(len(periods_by_area[area]) for area in core_areas),
            sum(
                len(expected_periods_by_area[area])
                for area in core_areas
            ),
        ),
        "event_calendar_coverage_ratio": ratio(
            required_period_area_count,
            len(core_areas),
        ),
        "event_value_coverage_ratio": ratio(
            required_period_area_count,
            len(core_areas),
        ),
        "publication_lag_calendar_days": "",
        "min_value": str(minimum_value),
        "min_value_date": period_date(minimum_key[1]).isoformat(),
        "max_value": str(maximum_value),
        "max_value_date": period_date(maximum_key[1]).isoformat(),
        "negative_value_count": str(sum(value < 0 for value in values)),
        "structure_status": "PASS" if structure_ok else "FAIL",
        "p0_status": p0_status,
        "notes": notes,
    }
    manifest = {
        "artifact_id": entry["artifact_id"],
        "variable_id": entry["variable_id"],
        "source_id": entry["source_id"],
        "repository": "",
        "repository_branch": "",
        "repository_commit": "",
        "repository_blob_sha": "",
        "official_url": entry["official_url"],
        "download_url": entry["download_url"],
        "local_path": entry["path"],
        "retrieved_at_utc": entry["retrieved_at_utc"],
        "sha256": digest,
        "size_bytes": str(entry["size_bytes"]),
        "format": "csv",
        "underlying_provider": "Organisation for Economic Co-operation and Development",
        "distributor": "OECD SDMX API",
        "license_or_terms": entry["license_or_terms"],
        "official_byte_identical_at_snapshot": "true",
        "status": (
            "audited_external_not_committed"
            if structure_ok
            else "failed_audit"
        ),
        "notes": (
            "Direct official SDMX CSV response with exact endpoint, retrieval "
            "time, byte size, SHA-256, requested areas, statuses, and schema."
        ),
    }
    detail = {
        "variable_id": entry["variable_id"],
        "file_row_count": len(rows),
        "valid_observation_count": len(observations),
        "area_ranges": {
            area: {
                "start": min(periods),
                "end": max(periods),
                "count": len(periods),
            }
            for area, periods in periods_by_area.items()
        },
        "latest_common_period": latest_common,
        "required_period_area_count": required_period_area_count,
        "interior_missing_periods_by_area": interior_missing,
        "right_edge_missing_periods_by_area": right_edge_missing,
        "blank_value_periods_by_area": dict(blank_value_periods),
        "status_counts": dict(status_counts),
        "non_normal_status_periods": dict(status_periods),
        "methodology_by_area": observed_methodology,
        "invalid_value_count": invalid_value_count,
        "duplicate_key_count": duplicate_key_count,
        "filter_mismatch_count": filter_mismatch_count,
        "unexpected_area_count": unexpected_area_count,
    }
    return audit, manifest, detail


def run_audit(
    config_path: Path = DEFAULT_CONFIG,
    write: bool = True,
) -> dict[str, Any]:
    config = load_config(config_path)
    results = [
        audit_one(config["snapshot"], entry) for entry in config["series"]
    ]
    audits = [result[0] for result in results]
    manifests = [result[1] for result in results]
    details = [result[2] for result in results]
    summary = {
        "snapshot": config["snapshot"],
        "artifact_count": len(audits),
        "structure_pass_count": sum(
            row["structure_status"] == "PASS" for row in audits
        ),
        "p0_pass_count": sum(row["p0_status"] == "PASS" for row in audits),
        "p0_blocked_count": sum(
            row["p0_status"] == "BLOCKED_RELEASE_LAG" for row in audits
        ),
        "p0_fail_count": sum(row["p0_status"] == "FAIL" for row in audits),
        "series": audits,
        "manifest": manifests,
        "details": details,
        "audit_columns": AUDIT_COLUMNS,
        "manifest_columns": MANIFEST_COLUMNS,
    }
    if write:
        with (METADATA_DIR / "oecd_snapshot_audit.json").open(
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
    print(f"OECD artifacts audited: {summary['artifact_count']}")
    print(f"Structural PASS: {summary['structure_pass_count']}")
    print(f"P0 PASS: {summary['p0_pass_count']}")
    print(f"P0 blocked by common-period lag: {summary['p0_blocked_count']}")
    print(f"P0 failed by internal completeness: {summary['p0_fail_count']}")
    return (
        0
        if summary["structure_pass_count"] == summary["artifact_count"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())

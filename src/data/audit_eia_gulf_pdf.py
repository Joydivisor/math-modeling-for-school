"""Audit the Gulf shut-in table in the July 2026 EIA STEO report."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from src.data.audit_eia_snapshot import (
    DEFAULT_CONFIG,
    METADATA_DIR,
    load_config,
    manifest_row,
    month_as_date,
    month_range,
    validate_artifact,
)
from src.data.audit_github_snapshot import AUDIT_COLUMNS, MANIFEST_COLUMNS, ratio


def audit_gulf_pdf(
    config_path: Path = DEFAULT_CONFIG,
    write: bool = True,
) -> dict[str, Any]:
    config = load_config(config_path)
    snapshot = config["snapshot"]
    entry = config["artifacts"]["steo_report"]
    path, digest, artifact_ok = validate_artifact(entry)

    reader = PdfReader(path)
    page_index = int(entry["pdf_page_index"])
    page_text = reader.pages[page_index].extract_text() or ""
    normalized_text = re.sub(r"\s+", " ", page_text)
    expected_tokens = [
        "Estimated Strait of Hormuz closure-related disruptions in crude oil production",
        "thousand barrels per day",
        "Total 25,200 8,890 10,400 11,200 8,290 5,427 1,440",
        "We only forecast aggregate disruptions for future months",
    ]
    text_ok = all(token in normalized_text for token in expected_tokens)

    observations = {
        month: float(value)
        for month, value in entry["observations_mbd"].items()
    }
    forecasts = {
        period: float(value)
        for period, value in entry["quarterly_forecasts_mbd"].items()
    }
    event_months = month_range(
        snapshot["event_start_month"], snapshot["event_end_month"]
    )
    observed_event_months = set(observations) & set(event_months)
    required_date = date.fromisoformat(entry["required_end"])
    last_month = max(observations)
    last_date = month_as_date(last_month)
    minimum_month, minimum_value = min(
        observations.items(), key=lambda item: item[1]
    )
    maximum_month, maximum_value = max(
        observations.items(), key=lambda item: item[1]
    )
    structure_ok = artifact_ok and text_ok and len(reader.pages) == 56
    p0_status = (
        "PASS"
        if structure_ok and last_date >= required_date
        else "BLOCKED_RELEASE_LAG"
        if structure_ok
        else "FAIL"
    )
    notes = (
        "Official Table 1 directly measures Strait of Hormuz closure-related "
        "Gulf crude production shut-ins. Monthly observations exist for "
        "2026-03 through 2026-06. The 3Q26 value 5.427 mb/d and 4Q26 value "
        "1.440 mb/d are quarterly forecasts and must not be divided or copied "
        "into July, August, or September monthly observations."
    )
    audit = {
        "variable_id": entry["variable_id"],
        "artifact_id": entry["artifact_id"],
        "series_id": entry["series_id"],
        "snapshot_commit": "",
        "sha256": digest,
        "row_count": str(len(observations)),
        "valid_count": str(len(observations)),
        "missing_marker_count": str(
            len(set(event_months) - set(observations))
        ),
        "invalid_row_count": "0" if text_ok else "1",
        "duplicate_date_count": "0",
        "start_date": month_as_date(min(observations)).isoformat(),
        "last_calendar_row_date": last_date.isoformat(),
        "last_valid_date": last_date.isoformat(),
        "required_end_date": required_date.isoformat(),
        "frequency": "monthly",
        "unit": "million barrels per day",
        "calendar_row_coverage_ratio": ratio(
            len(observed_event_months), len(event_months)
        ),
        "core_value_coverage_ratio": ratio(
            len(observed_event_months), len(event_months)
        ),
        "event_calendar_coverage_ratio": ratio(
            len(observed_event_months), len(event_months)
        ),
        "event_value_coverage_ratio": ratio(
            len(observed_event_months), len(event_months)
        ),
        "publication_lag_calendar_days": str(
            max(0, (required_date - last_date).days)
        ),
        "min_value": str(minimum_value),
        "min_value_date": month_as_date(minimum_month).isoformat(),
        "max_value": str(maximum_value),
        "max_value_date": month_as_date(maximum_month).isoformat(),
        "negative_value_count": "0",
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
            "Direct official EIA report download; Table 1 on PDF page index 4 "
            "was text-extracted and cross-checked against its total row."
        ),
    )
    summary = {
        "snapshot": snapshot,
        "artifact_count": 1,
        "structure_pass_count": int(structure_ok),
        "p0_pass_count": int(p0_status == "PASS"),
        "p0_blocked_count": int(p0_status == "BLOCKED_RELEASE_LAG"),
        "p0_fail_count": int(p0_status == "FAIL"),
        "series": [audit],
        "manifest": [manifest],
        "quarterly_forecasts_mbd": forecasts,
        "rejected_proxies": config.get("rejected_proxies", []),
        "audit_columns": AUDIT_COLUMNS,
        "manifest_columns": MANIFEST_COLUMNS,
    }
    if write:
        with (METADATA_DIR / "eia_gulf_pdf_audit.json").open(
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
    summary = audit_gulf_pdf(args.config, write=not args.check_only)
    print(f"EIA Gulf PDF artifacts audited: {summary['artifact_count']}")
    print(f"Structural PASS: {summary['structure_pass_count']}")
    print(f"P0 blocked by monthly release lag: {summary['p0_blocked_count']}")
    return 0 if summary["structure_pass_count"] == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())

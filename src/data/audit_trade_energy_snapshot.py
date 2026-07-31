"""Audit official GACC, JODI Oil, and UN Comtrade trade-energy snapshots."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import xlrd

from src.data.audit_github_snapshot import (
    AUDIT_COLUMNS,
    MANIFEST_COLUMNS,
    METADATA_DIR,
    PROJECT_ROOT,
    ratio,
)


DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "trade_energy_snapshot.json"
JODI_HISTORY_CONFIG = (
    PROJECT_ROOT / "configs" / "jodi_history_snapshot_20260730.json"
)
REQUIRED_JODI_COLUMNS = [
    "REF_AREA",
    "TIME_PERIOD",
    "ENERGY_PRODUCT",
    "FLOW_BREAKDOWN",
    "UNIT_MEASURE",
    "OBS_VALUE",
    "ASSESSMENT_CODE",
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


def manifest_row(
    *,
    artifact_id: str,
    variable_id: str,
    source_id: str,
    official_url: str,
    download_url: str,
    local_path: str,
    retrieved_at_utc: str,
    digest: str,
    size_bytes: int,
    format_name: str,
    provider: str,
    distributor: str,
    terms: str,
    notes: str,
    verified: bool = True,
) -> dict[str, str]:
    return {
        "artifact_id": artifact_id,
        "variable_id": variable_id,
        "source_id": source_id,
        "repository": "",
        "repository_branch": "",
        "repository_commit": "",
        "repository_blob_sha": "",
        "official_url": official_url,
        "download_url": download_url,
        "local_path": local_path,
        "retrieved_at_utc": retrieved_at_utc,
        "sha256": digest,
        "size_bytes": str(size_bytes),
        "format": format_name,
        "underlying_provider": provider,
        "distributor": distributor,
        "license_or_terms": terms,
        "official_byte_identical_at_snapshot": (
            "true" if verified else "false"
        ),
        "status": (
            "audited_external_not_committed"
            if verified
            else "audit_failed_do_not_use"
        ),
        "notes": notes,
    }


def audit_row(
    *,
    variable_id: str,
    artifact_id: str,
    series_id: str,
    digest: str,
    row_count: int,
    valid_count: int,
    missing_count: int,
    invalid_count: int,
    duplicate_count: int,
    start_date: str,
    last_date: str,
    required_end_date: str,
    frequency: str,
    unit: str,
    row_coverage: float,
    value_coverage: float,
    endpoint_coverage: float,
    minimum: float | None,
    maximum: float | None,
    structure_ok: bool,
    p0_status: str,
    notes: str,
    negative_count: int = 0,
    minimum_date: str | None = None,
    maximum_date: str | None = None,
) -> dict[str, str]:
    return {
        "variable_id": variable_id,
        "artifact_id": artifact_id,
        "series_id": series_id,
        "snapshot_commit": "",
        "sha256": digest,
        "row_count": str(row_count),
        "valid_count": str(valid_count),
        "missing_marker_count": str(missing_count),
        "invalid_row_count": str(invalid_count),
        "duplicate_date_count": str(duplicate_count),
        "start_date": start_date,
        "last_calendar_row_date": last_date,
        "last_valid_date": last_date,
        "required_end_date": required_end_date,
        "frequency": frequency,
        "unit": unit,
        "calendar_row_coverage_ratio": f"{row_coverage:.6f}",
        "core_value_coverage_ratio": f"{value_coverage:.6f}",
        "event_calendar_coverage_ratio": f"{endpoint_coverage:.6f}",
        "event_value_coverage_ratio": f"{endpoint_coverage:.6f}",
        "publication_lag_calendar_days": "",
        "min_value": "" if minimum is None else str(minimum),
        "min_value_date": (
            "" if minimum is None else minimum_date or last_date
        ),
        "max_value": "" if maximum is None else str(maximum),
        "max_value_date": (
            "" if maximum is None else maximum_date or last_date
        ),
        "negative_value_count": str(negative_count),
        "structure_status": "PASS" if structure_ok else "FAIL",
        "p0_status": p0_status,
        "notes": notes,
    }


def open_verified_xls(entry: dict[str, Any]) -> tuple[Path, str, Any]:
    path = PROJECT_ROOT / entry["path"]
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if not payload.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
        raise ValueError(f"{entry['path']} is not an OLE2/BIFF XLS file")
    if digest != entry["sha256"] or len(payload) != entry["size_bytes"]:
        raise ValueError(f"Frozen XLS fingerprint mismatch: {entry['path']}")
    return path, digest, xlrd.open_workbook(file_contents=payload)


def audit_gacc(
    config: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    gacc = config["gacc"]
    files = gacc["files"]
    total_path, total_digest, total_book = open_verified_xls(
        files["total_exports_imports"]
    )
    import_path, import_digest, import_book = open_verified_xls(
        files["major_imports"]
    )
    export_path, export_digest, export_book = open_verified_xls(
        files["major_exports"]
    )
    total_sheet = total_book.sheet_by_name("Sheet1")
    import_sheet = import_book.sheet_by_index(0)
    export_sheet = export_book.sheet_by_index(0)

    export_value = float(total_sheet.cell_value(11, 2))
    export_cumulative = float(total_sheet.cell_value(11, 3))
    crude_quantity = float(import_sheet.cell_value(21, 3))
    crude_value = float(import_sheet.cell_value(21, 4))
    crude_quantity_cumulative = float(import_sheet.cell_value(21, 5))
    crude_value_cumulative = float(import_sheet.cell_value(21, 6))
    refined_export_quantity = float(export_sheet.cell_value(13, 3))
    refined_export_value = float(export_sheet.cell_value(13, 4))
    comparison_title = str(import_sheet.cell_value(10, 7))
    unit_value_cny_tonne = crude_value * 1e8 / (crude_quantity * 1e4)

    structure_ok = all(
        [
            total_sheet.nrows == 15,
            total_sheet.ncols == 7,
            import_sheet.nrows == 48,
            import_sheet.ncols == 11,
            export_sheet.nrows == 43,
            export_sheet.ncols == 11,
            math.isclose(export_value, 28206.68965572),
            math.isclose(export_cumulative, 147314.43286081),
            math.isclose(crude_quantity, 2927.1645658),
            math.isclose(crude_value, 1532.31473372),
            math.isclose(crude_quantity_cumulative, 24761.0046924),
            math.isclose(crude_value_cumulative, 10470.76285389),
            math.isclose(refined_export_quantity, 436.050044),
            math.isclose(refined_export_value, 304.96910359),
            comparison_title == "1-6 Total, 2024",
        ]
    )
    note = (
        "Official June 2026 endpoint is structurally valid, but this snapshot "
        "does not supply the required 2010-2026 monthly history; P0 therefore "
        "fails on historical coverage. The import workbook labels its "
        "comparison block '1-6 Total, 2024' next to a YoY label, an internal "
        "conflict that must be checked against the Chinese or USD table before "
        "using comparison columns."
    )
    audits = [
        audit_row(
            variable_id="china_exports",
            artifact_id="GACC_TOTAL_EXPORTS_CNY_202606",
            series_id="GACC_TOTAL_EXPORT_JUN_2026_CNY",
            digest=total_digest,
            row_count=9,
            valid_count=1,
            missing_count=0,
            invalid_count=0,
            duplicate_count=0,
            start_date="2026-06-01",
            last_date="2026-06-01",
            required_end_date="2026-06-01",
            frequency="monthly endpoint plus year-to-date",
            unit="CNY 100 million",
            row_coverage=1 / 198,
            value_coverage=1 / 198,
            endpoint_coverage=1,
            minimum=export_value,
            maximum=export_value,
            structure_ok=structure_ok,
            p0_status="FAIL",
            notes=note,
        ),
        audit_row(
            variable_id="china_crude_import_qty",
            artifact_id="GACC_CRUDE_IMPORT_QTY_202606",
            series_id="GACC_CRUDE_IMPORT_QTY_JUN_2026",
            digest=import_digest,
            row_count=40,
            valid_count=1,
            missing_count=0,
            invalid_count=0,
            duplicate_count=0,
            start_date="2026-06-01",
            last_date="2026-06-01",
            required_end_date="2026-06-01",
            frequency="monthly endpoint plus year-to-date",
            unit="10,000 tonnes",
            row_coverage=1 / 198,
            value_coverage=1 / 198,
            endpoint_coverage=1,
            minimum=crude_quantity,
            maximum=crude_quantity,
            structure_ok=structure_ok,
            p0_status="FAIL",
            notes=note,
        ),
        audit_row(
            variable_id="china_crude_import_value",
            artifact_id="GACC_CRUDE_IMPORT_VALUE_202606",
            series_id="GACC_CRUDE_IMPORT_VALUE_JUN_2026",
            digest=import_digest,
            row_count=40,
            valid_count=1,
            missing_count=0,
            invalid_count=0,
            duplicate_count=0,
            start_date="2026-06-01",
            last_date="2026-06-01",
            required_end_date="2026-06-01",
            frequency="monthly endpoint plus year-to-date",
            unit="CNY 100 million",
            row_coverage=1 / 198,
            value_coverage=1 / 198,
            endpoint_coverage=1,
            minimum=crude_value,
            maximum=crude_value,
            structure_ok=structure_ok,
            p0_status="FAIL",
            notes=note,
        ),
    ]
    manifests = [
        manifest_row(
            artifact_id="GACC_TOTAL_EXPORTS_CNY_202606",
            variable_id="china_exports",
            source_id="SRC_GACC_STATS",
            official_url=files["total_exports_imports"]["official_url"],
            download_url=files["total_exports_imports"]["download_url"],
            local_path=str(total_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            retrieved_at_utc=files["total_exports_imports"]["retrieved_at_utc"],
            digest=total_digest,
            size_bytes=files["total_exports_imports"]["size_bytes"],
            format_name="xls",
            provider="General Administration of Customs of China",
            distributor="GACC English statistics",
            terms="Official website terms",
            notes="Untouched official OLE2/BIFF workbook.",
        ),
        manifest_row(
            artifact_id="GACC_CRUDE_IMPORT_QTY_202606",
            variable_id="china_crude_import_qty",
            source_id="SRC_GACC_STATS",
            official_url=files["major_imports"]["official_url"],
            download_url=files["major_imports"]["download_url"],
            local_path=str(import_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            retrieved_at_utc=files["major_imports"]["retrieved_at_utc"],
            digest=import_digest,
            size_bytes=files["major_imports"]["size_bytes"],
            format_name="xls",
            provider="General Administration of Customs of China",
            distributor="GACC English statistics",
            terms="Official website terms",
            notes="Untouched official OLE2/BIFF workbook; quantity view.",
        ),
        manifest_row(
            artifact_id="GACC_CRUDE_IMPORT_VALUE_202606",
            variable_id="china_crude_import_value",
            source_id="SRC_GACC_STATS",
            official_url=files["major_imports"]["official_url"],
            download_url=files["major_imports"]["download_url"],
            local_path=str(import_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            retrieved_at_utc=files["major_imports"]["retrieved_at_utc"],
            digest=import_digest,
            size_bytes=files["major_imports"]["size_bytes"],
            format_name="xls",
            provider="General Administration of Customs of China",
            distributor="GACC English statistics",
            terms="Official website terms",
            notes="Untouched official OLE2/BIFF workbook; value view.",
        ),
        manifest_row(
            artifact_id="GACC_REFINED_EXPORTS_202606",
            variable_id="china_refined_product_exports",
            source_id="SRC_GACC_STATS",
            official_url=files["major_exports"]["official_url"],
            download_url=files["major_exports"]["download_url"],
            local_path=str(export_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            retrieved_at_utc=files["major_exports"]["retrieved_at_utc"],
            digest=export_digest,
            size_bytes=files["major_exports"]["size_bytes"],
            format_name="xls",
            provider="General Administration of Customs of China",
            distributor="GACC English statistics",
            terms="Official website terms",
            notes="Auxiliary refined-product export endpoint; not total exports.",
        ),
    ]
    details = {
        "structure_status": "PASS" if structure_ok else "FAIL",
        "june_2026": {
            "total_exports_cny_100m": export_value,
            "crude_import_10k_tonnes": crude_quantity,
            "crude_import_cny_100m": crude_value,
            "crude_import_unit_value_cny_tonne": unit_value_cny_tonne,
            "refined_product_export_10k_tonnes": refined_export_quantity,
            "refined_product_export_cny_100m": refined_export_value,
        },
        "ytd_2026": {
            "total_exports_cny_100m": export_cumulative,
            "crude_import_10k_tonnes": crude_quantity_cumulative,
            "crude_import_cny_100m": crude_value_cumulative,
        },
        "comparison_title_conflict": comparison_title,
    }
    return audits, manifests, details


def read_jodi_file(
    entry: dict[str, Any],
) -> tuple[dict[str, Any], dict[tuple[str, str, str, str, str], float]]:
    path = PROJECT_ROOT / entry["path"]
    digest = sha256_file(path)
    rows = 0
    dash_count = 0
    x_count = 0
    dotdot_count = 0
    invalid_count = 0
    duplicate_count = 0
    periods: set[str] = set()
    areas: set[str] = set()
    values: list[float] = []
    dated_values: list[tuple[float, str]] = []
    keyed_values: dict[tuple[str, str, str, str, str], float] = {}
    seen: set[tuple[str, str, str, str, str]] = set()
    assessment_counts: Counter[str] = Counter()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        for row in reader:
            rows += 1
            key = tuple(row[column] for column in REQUIRED_JODI_COLUMNS[:5])
            if key in seen:
                duplicate_count += 1
            seen.add(key)
            areas.add(row["REF_AREA"])
            periods.add(row["TIME_PERIOD"])
            assessment_counts[row["ASSESSMENT_CODE"]] += 1
            token = row["OBS_VALUE"]
            if token == "-":
                dash_count += 1
            elif token == "x":
                x_count += 1
            elif token == "..":
                dotdot_count += 1
            else:
                try:
                    numeric = float(token)
                    values.append(numeric)
                    dated_values.append((numeric, row["TIME_PERIOD"]))
                    keyed_values[key] = numeric
                except ValueError:
                    invalid_count += 1
    structure_ok = all(
        [
            digest == entry["sha256"],
            path.stat().st_size == entry["size_bytes"],
            columns == REQUIRED_JODI_COLUMNS,
            rows == entry["row_count"],
            dash_count == entry["missing_dash_count"],
            x_count == entry["missing_x_count"],
            dotdot_count == entry["missing_dotdot_count"],
            duplicate_count == 0,
            invalid_count == 0,
            len(areas) == 96,
            periods == {
                "2026-01",
                "2026-02",
                "2026-03",
                "2026-04",
                "2026-05",
            },
        ]
    )
    return (
        {
            "path": path,
            "digest": digest,
            "row_count": rows,
            "valid_count": len(values),
            "dash_count": dash_count,
            "x_count": x_count,
            "dotdot_count": dotdot_count,
            "invalid_count": invalid_count,
            "duplicate_count": duplicate_count,
            "areas": sorted(areas),
            "periods": sorted(periods),
            "minimum": min(values),
            "minimum_date": min(dated_values)[1],
            "maximum": max(values),
            "maximum_date": max(dated_values)[1],
            "negative_count": sum(value < 0 for value in values),
            "assessment_counts": dict(assessment_counts),
            "structure_ok": structure_ok,
        },
        keyed_values,
    )


def audit_jodi(
    config: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    jodi = config["jodi"]
    primary, primary_values = read_jodi_file(jodi["files"]["primary"])
    secondary, secondary_values = read_jodi_file(jodi["files"]["secondary"])

    def get_value(
        values: dict[tuple[str, str, str, str, str], float],
        area: str,
        product: str,
        flow: str,
    ) -> float:
        return values[(area, "2026-05", product, flow, "KBBL")]

    dependencies: dict[str, dict[str, float]] = {}
    candidate_ok = True
    for area, expected in jodi["expected_may_2026_dependency"].items():
        crude_imports = get_value(
            primary_values, area, "CRUDEOIL", "TOTIMPSB"
        )
        crude_exports = get_value(
            primary_values, area, "CRUDEOIL", "TOTEXPSB"
        )
        refinery_intake = get_value(
            primary_values, area, "CRUDEOIL", "REFINOBS"
        )
        total_crude_imports = get_value(
            primary_values, area, "TOTCRUDE", "TOTIMPSB"
        )
        total_crude_exports = get_value(
            primary_values, area, "TOTCRUDE", "TOTEXPSB"
        )
        product_imports = get_value(
            secondary_values, area, "TOTPRODS", "TOTIMPSB"
        )
        product_exports = get_value(
            secondary_values, area, "TOTPRODS", "TOTEXPSB"
        )
        total_demand = get_value(
            secondary_values, area, "TOTPRODS", "TOTDEMO"
        )
        crude_ratio = (crude_imports - crude_exports) / refinery_intake
        broad_ratio = (
            total_crude_imports
            - total_crude_exports
            + product_imports
            - product_exports
        ) / total_demand
        dependencies[area] = {
            "crude_dependency": crude_ratio,
            "broad_dependency": broad_ratio,
        }
        candidate_ok = candidate_ok and math.isclose(
            crude_ratio,
            expected["crude"],
            abs_tol=5e-7,
        )
        candidate_ok = candidate_ok and math.isclose(
            broad_ratio,
            expected["broad"],
            abs_tol=5e-7,
        )

    india = jodi["incomplete_area"]
    india_missing = []
    for source_name, values, product, flow in [
        ("primary", primary_values, "CRUDEOIL", "TOTEXPSB"),
        ("primary", primary_values, "CRUDEOIL", "TOTIMPSB"),
        ("primary", primary_values, "CRUDEOIL", "REFINOBS"),
        ("primary", primary_values, "TOTCRUDE", "TOTEXPSB"),
        ("primary", primary_values, "TOTCRUDE", "TOTIMPSB"),
        ("secondary", secondary_values, "TOTPRODS", "TOTEXPSB"),
        ("secondary", secondary_values, "TOTPRODS", "TOTIMPSB"),
        ("secondary", secondary_values, "TOTPRODS", "TOTDEMO"),
    ]:
        key = (india, "2026-05", product, flow, "KBBL")
        if key not in values:
            india_missing.append(
                {"source": source_name, "product": product, "flow": flow}
            )
    india_internal_inconsistency = []
    for period in ("2026-01", "2026-02", "2026-03"):
        crude_key = (
            india, period, "CRUDEOIL", "TOTIMPSB", "KBBL"
        )
        total_key = (
            india, period, "TOTCRUDE", "TOTIMPSB", "KBBL"
        )
        if (
            crude_key in primary_values
            and total_key in primary_values
            and primary_values[crude_key] > 0
            and primary_values[total_key] == 0
        ):
            india_internal_inconsistency.append(
                {
                    "period": period,
                    "crudeoil_import_kbbl": primary_values[crude_key],
                    "totcrude_import_kbbl": primary_values[total_key],
                }
            )
    structure_ok = (
        primary["structure_ok"]
        and secondary["structure_ok"]
        and candidate_ok
        and len(india_missing) == 8
        and len(india_internal_inconsistency) == 3
    )
    notes = (
        "Official JODI 2026 monthly files are structurally valid, but they "
        "cover only 2026-01 through 2026-05 instead of 2010 onward. India is "
        "not computable at the May endpoint because required values are "
        "missing. In January-March India reports positive CRUDEOIL imports "
        "but zero TOTCRUDE imports, an internal reporting inconsistency. "
        "CONVBBL is a conversion factor, "
        "not a quantity; dependency candidates use KBBL. Negative and >1 "
        "ratios are retained rather than clipped. ASSESSMENT_CODE is a display "
        "assessment category and is not used as a numeric weight."
    )
    collection_payload = (
        f"primary {primary['digest']}\n"
        f"secondary {secondary['digest']}\n"
    ).encode("utf-8")
    collection_digest = hashlib.sha256(collection_payload).hexdigest()
    minimum_value, minimum_period = min(
        (primary["minimum"], primary["minimum_date"]),
        (secondary["minimum"], secondary["minimum_date"]),
    )
    maximum_value, maximum_period = max(
        (primary["maximum"], primary["maximum_date"]),
        (secondary["maximum"], secondary["maximum_date"]),
    )
    audits = [
        audit_row(
            variable_id="net_oil_import_dependency",
            artifact_id="JODI_OIL_DEPENDENCY_20260729",
            series_id="JODI_OIL_PRIMARY_SECONDARY_2026",
            digest=collection_digest,
            row_count=primary["row_count"] + secondary["row_count"],
            valid_count=primary["valid_count"] + secondary["valid_count"],
            missing_count=(
                primary["dash_count"]
                + primary["x_count"]
                + primary["dotdot_count"]
                + secondary["dash_count"]
                + secondary["x_count"]
                + secondary["dotdot_count"]
            ),
            invalid_count=(
                primary["invalid_count"] + secondary["invalid_count"]
            ),
            duplicate_count=(
                primary["duplicate_count"] + secondary["duplicate_count"]
            ),
            start_date="2026-01-01",
            last_date="2026-05-01",
            required_end_date="2026-06-01",
            frequency="monthly",
            unit="multiple raw units; dependency candidates use KBBL",
            row_coverage=5 / 198,
            value_coverage=8 / 9,
            endpoint_coverage=0,
            minimum=minimum_value,
            maximum=maximum_value,
            structure_ok=structure_ok,
            p0_status="FAIL",
            notes=notes,
            negative_count=(
                primary["negative_count"] + secondary["negative_count"]
            ),
            minimum_date=minimum_period + "-01",
            maximum_date=maximum_period + "-01",
        )
    ]
    manifests: list[dict[str, str]] = []
    for name, result, entry in [
        ("primary", primary, jodi["files"]["primary"]),
        ("secondary", secondary, jodi["files"]["secondary"]),
    ]:
        manifests.append(
            manifest_row(
                artifact_id=f"JODI_OIL_{name.upper()}_20260729",
                variable_id=f"jodi_oil_{name}_snapshot",
                source_id="SRC_JODI_OIL",
                official_url=jodi["official_url"],
                download_url=entry.get("download_url", jodi["official_url"]),
                local_path=str(
                    result["path"].relative_to(PROJECT_ROOT)
                ).replace("\\", "/"),
                retrieved_at_utc=entry["retrieved_at_utc"],
                digest=result["digest"],
                size_bytes=entry["size_bytes"],
                format_name="csv",
                provider="Joint Organisations Data Initiative",
                distributor="JODI Oil",
                terms="JODI terms of use",
                notes=(
                    f"Untouched official {name} CSV; Last-Modified was "
                    "2026-07-21 and assessment codes are retained."
                ),
            )
        )
    manifests.append(
        manifest_row(
            artifact_id="JODI_OIL_DEPENDENCY_20260729",
            variable_id="net_oil_import_dependency",
            source_id="SRC_JODI_OIL",
            official_url=jodi["official_url"],
            download_url=jodi["official_url"],
            local_path="data/raw/trade_energy",
            retrieved_at_utc=jodi["files"]["secondary"][
                "retrieved_at_utc"
            ],
            digest=collection_digest,
            size_bytes=(
                jodi["files"]["primary"]["size_bytes"]
                + jodi["files"]["secondary"]["size_bytes"]
            ),
            format_name="csv collection",
            provider="Joint Organisations Data Initiative",
            distributor="JODI Oil",
            terms="JODI terms of use",
            notes=(
                "Logical aggregate fingerprint over the primary and "
                "secondary file SHA-256 values; individual raw manifests "
                "are retained separately."
            ),
        )
    )
    details = {
        "structure_status": "PASS" if structure_ok else "FAIL",
        "primary": {
            key: value
            for key, value in primary.items()
            if key not in {"path"}
        },
        "secondary": {
            key: value
            for key, value in secondary.items()
            if key not in {"path"}
        },
        "may_2026_dependency_candidates": dependencies,
        "india_missing_required_fields": india_missing,
        "india_internal_inconsistency_2026q1": (
            india_internal_inconsistency
        ),
        "common_complete_window_excluding_india": ["2026-01", "2026-05"],
    }
    return audits, manifests, details


def audit_jodi_history(
    config: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    """Audit the hash-pinned 2010--2026 JODI annual collection."""
    with JODI_HISTORY_CONFIG.open("r", encoding="utf-8") as handle:
        history = json.load(handle)

    expected_columns = history["required_columns"]
    target_areas = history["target_areas"]
    missing_tokens = {"-", "x", ".."}
    primary_components = {
        ("CRUDEOIL", "TOTIMPSB"),
        ("CRUDEOIL", "TOTEXPSB"),
        ("CRUDEOIL", "REFINOBS"),
        ("TOTCRUDE", "TOTIMPSB"),
        ("TOTCRUDE", "TOTEXPSB"),
    }
    secondary_components = {
        ("TOTPRODS", "TOTIMPSB"),
        ("TOTPRODS", "TOTEXPSB"),
        ("TOTPRODS", "TOTDEMO"),
    }
    primary_values: dict[tuple[str, str, str, str], float] = {}
    secondary_values: dict[tuple[str, str, str, str], float] = {}
    file_results: list[dict[str, Any]] = []

    for entry in history["files"]:
        path = PROJECT_ROOT / entry["path"]
        digest = sha256_file(path)
        row_count = 0
        periods: set[str] = set()
        areas: set[str] = set()
        missing = {token: 0 for token in missing_tokens}
        invalid_count = 0
        duplicate_count = 0
        year_mismatch_count = 0
        valid_count = 0
        negative_count = 0
        seen: set[tuple[str, str, str, str, str]] = set()
        minimum: float | None = None
        maximum: float | None = None
        minimum_date = ""
        maximum_date = ""
        component_values = (
            primary_values if entry["kind"] == "primary" else secondary_values
        )
        component_set = (
            primary_components
            if entry["kind"] == "primary"
            else secondary_components
        )
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = list(reader.fieldnames or [])
            for row in reader:
                row_count += 1
                period = row["TIME_PERIOD"]
                area = row["REF_AREA"]
                product = row["ENERGY_PRODUCT"]
                flow = row["FLOW_BREAKDOWN"]
                unit = row["UNIT_MEASURE"]
                token = row["OBS_VALUE"]
                key = (area, period, product, flow, unit)
                if key in seen:
                    duplicate_count += 1
                seen.add(key)
                periods.add(period)
                areas.add(area)
                if not period.startswith(f"{entry['year']}-"):
                    year_mismatch_count += 1
                if token in missing_tokens:
                    missing[token] += 1
                    continue
                try:
                    value = float(token)
                except ValueError:
                    invalid_count += 1
                    continue
                valid_count += 1
                if value < 0:
                    negative_count += 1
                if minimum is None or value < minimum:
                    minimum = value
                    minimum_date = period
                if maximum is None or value > maximum:
                    maximum = value
                    maximum_date = period
                if (
                    area in target_areas
                    and unit == "KBBL"
                    and (product, flow) in component_set
                ):
                    component_values[(area, period, product, flow)] = value
        structure_ok = all(
            [
                digest == entry["sha256"],
                path.stat().st_size == entry["size_bytes"],
                columns == expected_columns,
                row_count == entry["row_count"],
                periods
                == {
                    f"{entry['year']}-{month:02d}"
                    for month in range(1, 6 if entry["year"] == 2026 else 13)
                },
                len(areas) == entry["area_count"],
                missing["-"] == entry["missing_dash_count"],
                missing["x"] == entry["missing_x_count"],
                missing[".."] == entry["missing_dotdot_count"],
                invalid_count == 0,
                duplicate_count == 0,
                year_mismatch_count == 0,
            ]
        )
        file_results.append(
            {
                "entry": entry,
                "path": path,
                "digest": digest,
                "row_count": row_count,
                "valid_count": valid_count,
                "missing_count": sum(missing.values()),
                "invalid_count": invalid_count,
                "duplicate_count": duplicate_count,
                "negative_count": negative_count,
                "minimum": minimum,
                "maximum": maximum,
                "minimum_date": minimum_date,
                "maximum_date": maximum_date,
                "structure_ok": structure_ok,
            }
        )

    periods = [
        f"{year}-{month:02d}"
        for year in range(2010, 2026)
        for month in range(1, 13)
    ] + [f"2026-{month:02d}" for month in range(1, 6)]
    panel_rows: list[dict[str, Any]] = []
    complete_by_area: dict[str, set[str]] = {}
    dependency_values: list[tuple[float, str, str]] = []
    for area, country in target_areas.items():
        crude_complete: list[str] = []
        broad_complete: list[str] = []
        inconsistent: list[str] = []
        for period in periods:
            crude_keys = [
                (area, period, "CRUDEOIL", "TOTIMPSB"),
                (area, period, "CRUDEOIL", "TOTEXPSB"),
                (area, period, "CRUDEOIL", "REFINOBS"),
            ]
            broad_primary = [
                (area, period, "TOTCRUDE", "TOTIMPSB"),
                (area, period, "TOTCRUDE", "TOTEXPSB"),
            ]
            broad_secondary = [
                (area, period, "TOTPRODS", "TOTIMPSB"),
                (area, period, "TOTPRODS", "TOTEXPSB"),
                (area, period, "TOTPRODS", "TOTDEMO"),
            ]
            crude_ok = (
                all(key in primary_values for key in crude_keys)
                and primary_values[crude_keys[2]] != 0
            )
            broad_ok = (
                all(key in primary_values for key in broad_primary)
                and all(key in secondary_values for key in broad_secondary)
                and secondary_values[broad_secondary[2]] != 0
            )
            if crude_ok:
                crude_complete.append(period)
            if broad_ok:
                broad_complete.append(period)
            if crude_ok and broad_ok:
                broad_ratio = (
                    primary_values[broad_primary[0]]
                    - primary_values[broad_primary[1]]
                    + secondary_values[broad_secondary[0]]
                    - secondary_values[broad_secondary[1]]
                ) / secondary_values[broad_secondary[2]]
                dependency_values.append((broad_ratio, period, area))
            crude_import = (area, period, "CRUDEOIL", "TOTIMPSB")
            total_import = (area, period, "TOTCRUDE", "TOTIMPSB")
            if (
                crude_import in primary_values
                and total_import in primary_values
                and primary_values[crude_import] > 0
                and primary_values[total_import] == 0
            ):
                inconsistent.append(period)
        both = set(crude_complete) & set(broad_complete)
        complete_by_area[area] = both
        panel_rows.append(
            {
                "area": area,
                "country": country,
                "expected_months": len(periods),
                "crude_complete_months": len(crude_complete),
                "broad_complete_months": len(broad_complete),
                "both_complete_months": len(both),
                "both_coverage_ratio": len(both) / len(periods),
                "first_both_complete": min(both) if both else "",
                "last_both_complete": max(both) if both else "",
                "missing_both_periods": sorted(set(periods) - both),
                "totcrude_zero_inconsistency_count": len(inconsistent),
                "totcrude_zero_inconsistency_periods": inconsistent,
            }
        )
    all_nine = set(periods)
    eight_country = set(periods)
    for area, complete in complete_by_area.items():
        all_nine &= complete
        if area != "IN":
            eight_country &= complete
    panel = {
        "expected_period_start": periods[0],
        "expected_period_end": periods[-1],
        "expected_month_count": len(periods),
        "all_nine_common_complete_month_count": len(all_nine),
        "all_nine_common_coverage_ratio": len(all_nine) / len(periods),
        "all_nine_common_first": min(all_nine) if all_nine else "",
        "all_nine_common_last": max(all_nine) if all_nine else "",
        "excluding_india_common_complete_month_count": len(eight_country),
        "excluding_india_common_coverage_ratio": len(eight_country) / len(periods),
        "excluding_india_common_first": min(eight_country),
        "excluding_india_common_last": max(eight_country),
        "required_2026_06_available": False,
        "full_2010_2026_panel_feasible": len(all_nine) / len(periods) >= 0.95,
        "eight_country_panel_feasible_at_95pct": (
            len(eight_country) / len(periods) >= 0.95
        ),
    }
    expected = history["expected_panel"]
    expected_area_rows = {
        row["area"]: row for row in history["expected_area_coverage"]
    }
    area_assertions: list[bool] = []
    for row in panel_rows:
        expected_area = expected_area_rows[row["area"]]
        area_assertions.extend(
            [
                row["expected_months"] == int(expected_area["expected_months"]),
                row["crude_complete_months"]
                == int(expected_area["crude_complete_months"]),
                row["broad_complete_months"]
                == int(expected_area["broad_complete_months"]),
                row["both_complete_months"]
                == int(expected_area["both_complete_months"]),
                math.isclose(
                    row["both_coverage_ratio"],
                    float(expected_area["both_coverage_ratio"]),
                    abs_tol=1e-12,
                ),
                row["first_both_complete"]
                == expected_area["first_both_complete"],
                row["last_both_complete"]
                == expected_area["last_both_complete"],
                row["totcrude_zero_inconsistency_count"]
                == int(expected_area["totcrude_zero_inconsistency_count"]),
                "|".join(row["totcrude_zero_inconsistency_periods"])
                == expected_area["totcrude_zero_inconsistency_periods"],
            ]
        )
    india_row = next(row for row in panel_rows if row["area"] == "IN")
    china_row = next(row for row in panel_rows if row["area"] == "CN")
    panel_ok = all(
        [
            *area_assertions,
            panel["expected_period_start"] == history["expected_period_start"],
            panel["expected_period_end"] == history["expected_period_end"],
            panel["expected_month_count"] == expected["expected_month_count"],
            panel["all_nine_common_complete_month_count"]
            == expected["all_nine_common_complete_month_count"],
            math.isclose(
                panel["all_nine_common_coverage_ratio"],
                expected["all_nine_common_coverage_ratio"],
                abs_tol=1e-12,
            ),
            panel["excluding_india_common_complete_month_count"]
            == expected["excluding_india_common_complete_month_count"],
            math.isclose(
                panel["excluding_india_common_coverage_ratio"],
                expected["excluding_india_common_coverage_ratio"],
                abs_tol=1e-12,
            ),
            panel["required_2026_06_available"]
            == expected["required_2026_06_available"],
            panel["eight_country_panel_feasible_at_95pct"]
            == expected["eight_country_panel_feasible_at_95pct"],
            india_row["both_complete_months"]
            == expected["india_both_complete_months"],
            india_row["totcrude_zero_inconsistency_count"]
            == expected["india_totcrude_zero_inconsistency_count"],
            china_row["missing_both_periods"]
            == expected["china_missing_both_periods"],
        ]
    )

    endpoint_audits, _, endpoint_details = audit_jodi(config)
    endpoint_ok = endpoint_audits[0]["structure_status"] == "PASS"
    structure_ok = (
        all(result["structure_ok"] for result in file_results)
        and panel_ok
        and endpoint_ok
    )
    collection_payload = "".join(
        f"{result['entry']['kind']}/{result['entry']['year']} "
        f"{result['digest']}\n"
        for result in sorted(
            file_results,
            key=lambda row: (row["entry"]["kind"], row["entry"]["year"]),
        )
    ).encode("utf-8")
    collection_digest = hashlib.sha256(collection_payload).hexdigest()
    minimum_value, minimum_period, minimum_area = min(dependency_values)
    maximum_value, maximum_period, maximum_area = max(dependency_values)
    complete_area_month_count = sum(
        len(complete) for complete in complete_by_area.values()
    )
    expected_area_month_count = len(periods) * len(target_areas)
    notes = (
        "All 34 official JODI annual CSVs for 2010--2026 YTD are hash-pinned "
        "and structurally valid. The eight-country panel excluding India has "
        "193/197 common months (97.97%), but the nine-country panel has only "
        "110/197. India has 111 complete months and 195 months where positive "
        "CRUDEOIL imports conflict with zero TOTCRUDE imports. China lacks four "
        "component-complete months. June 2026 is not yet released. Therefore "
        "the original nine-country P0 variable remains FAIL; the eight-country "
        "panel is an explicit M1 candidate, not an automatic substitution. Raw "
        "files remain uncommitted pending JODI redistribution review. Audit "
        "row statistics use the broad KBBL dependency ratio only on area-months "
        "where both crude and broad candidates are computable."
    )
    audits = [
        audit_row(
            variable_id="net_oil_import_dependency",
            artifact_id="JODI_OIL_DEPENDENCY_2010_2026_20260730",
            series_id="JODI_OIL_PRIMARY_SECONDARY_2010_2026YTD",
            digest=collection_digest,
            row_count=expected_area_month_count,
            valid_count=complete_area_month_count,
            missing_count=expected_area_month_count - complete_area_month_count,
            invalid_count=0,
            duplicate_count=0,
            start_date="2010-01-01",
            last_date="2026-05-01",
            required_end_date=history["required_end_date"],
            frequency="monthly",
            unit="broad net-oil dependency ratio; KBBL components",
            row_coverage=1.0,
            value_coverage=complete_area_month_count / expected_area_month_count,
            endpoint_coverage=0,
            minimum=minimum_value,
            maximum=maximum_value,
            structure_ok=structure_ok,
            p0_status="FAIL",
            notes=notes,
            negative_count=sum(value < 0 for value, _, _ in dependency_values),
            minimum_date=minimum_period + "-01",
            maximum_date=maximum_period + "-01",
        )
    ]
    manifests = [
        manifest_row(
            artifact_id=(
                f"JODI_OIL_{result['entry']['kind'].upper()}_"
                f"{result['entry']['year']}_20260730"
            ),
            variable_id=f"jodi_oil_{result['entry']['kind']}_raw",
            source_id="SRC_JODI_OIL",
            official_url=history["official_url"],
            download_url=result["entry"]["download_url"],
            local_path=result["entry"]["path"],
            retrieved_at_utc=result["entry"]["retrieved_at_utc"],
            digest=result["digest"],
            size_bytes=result["entry"]["size_bytes"],
            format_name="csv",
            provider="Joint Organisations Data Initiative",
            distributor="JODI Oil",
            terms="JODI terms of use",
            verified=result["structure_ok"],
            notes=(
                "Untouched official annual CSV; raw file is ignored and is not "
                "redistributed by this repository."
            ),
        )
        for result in file_results
    ]
    manifests.append(
        manifest_row(
            artifact_id="JODI_OIL_DEPENDENCY_2010_2026_20260730",
            variable_id="net_oil_import_dependency",
            source_id="SRC_JODI_OIL",
            official_url=history["official_url"],
            download_url=history["official_url"],
            local_path="data/raw/trade_energy",
            retrieved_at_utc=max(
                entry["retrieved_at_utc"] for entry in history["files"]
            ),
            digest=collection_digest,
            size_bytes=sum(entry["size_bytes"] for entry in history["files"]),
            format_name="csv collection",
            provider="Joint Organisations Data Initiative",
            distributor="JODI Oil",
            terms="JODI terms of use",
            verified=structure_ok,
            notes=(
                "Logical fingerprint over 34 sorted annual-file hashes; raw "
                "files remain ignored pending redistribution review."
            ),
        )
    )
    details = {
        **endpoint_details,
        "structure_status": "PASS" if structure_ok else "FAIL",
        "history_file_count": len(file_results),
        "history_structure_pass_count": sum(
            result["structure_ok"] for result in file_results
        ),
        "history_collection_sha256": collection_digest,
        "dependency_statistic_scope": (
            "broad KBBL ratio on both-candidate-complete area-months"
        ),
        "dependency_minimum_area": minimum_area,
        "dependency_maximum_area": maximum_area,
        "panel_coverage": panel_rows,
        "panel_summary": panel,
        "common_complete_window_excluding_india": [
            panel["excluding_india_common_first"],
            panel["excluding_india_common_last"],
        ],
    }
    return audits, manifests, details

def run_audit(
    config_path: Path = DEFAULT_CONFIG,
    write: bool = True,
) -> dict[str, Any]:
    from src.data.audit_comtrade_history_snapshot import (
        audit_comtrade_history,
    )

    config = load_config(config_path)
    component_results = {
        "gacc": audit_gacc(config),
        "jodi": audit_jodi_history(config),
        "comtrade": audit_comtrade_history(),
    }
    audits = [
        row
        for component in component_results.values()
        for row in component[0]
    ]
    manifests = [
        row
        for component in component_results.values()
        for row in component[1]
    ]
    summary = {
        "artifact_count": len(audits),
        "manifest_artifact_count": len(manifests),
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
        "details": {
            name: result[2] for name, result in component_results.items()
        },
        "audit_columns": AUDIT_COLUMNS,
        "manifest_columns": MANIFEST_COLUMNS,
    }
    if write:
        with (METADATA_DIR / "trade_energy_snapshot_audit.json").open(
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
    print(f"Trade-energy artifacts audited: {summary['artifact_count']}")
    print(f"Manifest artifacts: {summary['manifest_artifact_count']}")
    print(f"Structural PASS: {summary['structure_pass_count']}")
    print(f"P0 PASS: {summary['p0_pass_count']}")
    print(f"P0 failed by historical/semantic coverage: {summary['p0_fail_count']}")
    return (
        0
        if summary["structure_pass_count"] == summary["artifact_count"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())

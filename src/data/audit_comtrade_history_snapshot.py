"""Audit the corrected 2010--2026 UN Comtrade HS2709 panel."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from src.data.audit_github_snapshot import PROJECT_ROOT
from src.data.audit_trade_energy_snapshot import (
    audit_row,
    manifest_row,
    sha256_file,
)

DEFAULT_CONFIG = (
    PROJECT_ROOT / "configs" / "comtrade_history_snapshot_20260730.json"
)


def finite_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def audit_comtrade_history(
    config_path: Path = DEFAULT_CONFIG,
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    body_root = PROJECT_ROOT / "data/raw/trade_energy/comtrade_hs2709_history"
    header_root = PROJECT_ROOT / "data/raw/trade_energy/comtrade_hs2709_headers"
    expected_bodies = {Path(entry["path"]).name for entry in config["files"]}
    expected_headers = {
        Path(entry["header_path"]).name for entry in config["files"]
    }
    file_set_ok = (
        {path.name for path in body_root.glob("*.json")} == expected_bodies
        and {path.name for path in header_root.glob("*.txt")}
        == expected_headers
    )

    file_results: list[dict[str, Any]] = []
    full_hhi: dict[str, dict[str, float]] = {}
    conditional_hhi: dict[str, dict[str, float]] = {}
    quality_by_reporter_year: dict[str, dict[str, str]] = {}
    classification_by_year: dict[str, set[str]] = {}
    no_record_ids: list[str] = []
    conditional_ids: list[str] = []
    partner_missing_records: list[dict[str, Any]] = []
    estimated_record_count = 0
    estimated_partner_weight_count = 0
    residual_partner_rows: list[dict[str, Any]] = []
    partner_sum_ratio_outside_2pct: list[dict[str, Any]] = []
    total_record_count = 0
    total_invalid_count = 0
    total_duplicate_count = 0

    for entry in config["files"]:
        request_id = f"{entry['reporter']}_{entry['year']}"
        body_path = PROJECT_ROOT / entry["path"]
        header_path = PROJECT_ROOT / entry["header_path"]
        body_digest = sha256_file(body_path)
        header_digest = sha256_file(header_path)
        document = json.loads(body_path.read_text(encoding="utf-8-sig"))
        records = document.get("data")
        local_invalid = 0
        local_duplicates = 0
        if not isinstance(records, list):
            records = []
            local_invalid += 1
        total_record_count += len(records)
        estimated_record_count += sum(
            bool(row.get("isNetWgtEstimated")) for row in records
        )
        if document.get("count") != len(records):
            local_invalid += 1
        if document.get("error") not in (None, "", []):
            local_invalid += 1

        keys: set[tuple[Any, ...]] = set()
        world_rows: list[dict[str, Any]] = []
        partner_rows: list[dict[str, Any]] = []
        classifications: set[str] = set()
        for record in records:
            key = (
                record.get("reporterCode"),
                str(record.get("period")),
                record.get("partnerCode"),
                record.get("cmdCode"),
                record.get("flowCode"),
                record.get("customsCode"),
                record.get("motCode"),
            )
            if key in keys:
                local_duplicates += 1
            keys.add(key)
            if any(
                [
                    record.get("reporterCode")
                    != entry["reporter_area_code"],
                    str(record.get("period")) != str(entry["year"]),
                    record.get("cmdCode") != "2709",
                    record.get("flowCode") != "M",
                    record.get("partner2Code") != 0,
                    record.get("customsCode") != "C00",
                    record.get("motCode") != 0,
                ]
            ):
                local_invalid += 1
            classification = record.get("classificationCode")
            if classification:
                classifications.add(str(classification))
            if record.get("partnerCode") == 0:
                world_rows.append(record)
            else:
                partner_rows.append(record)
        classification_by_year.setdefault(str(entry["year"]), set()).update(
            classifications
        )
        expected_classifications = {
            value for value in entry["classification_codes"].split("|") if value
        }
        if classifications != expected_classifications:
            local_invalid += 1
        if len(world_rows) != entry["world_row_count"]:
            local_invalid += 1
        if len(partner_rows) != entry["partner_row_count"]:
            local_invalid += 1
        if bool(records) == entry["no_record"]:
            local_invalid += 1

        partner_codes = [str(row.get("partnerCode")) for row in partner_rows]
        partner_counts = Counter(partner_codes)
        duplicate_partner_count = sum(
            count - 1 for count in partner_counts.values() if count > 1
        )
        if duplicate_partner_count:
            local_duplicates += duplicate_partner_count
        partner_weights = [
            finite_number(row.get("netWgt")) for row in partner_rows
        ]
        missing_partner_count = sum(
            value is None for value in partner_weights
        )
        negative_partner_count = sum(
            value < 0 for value in partner_weights if value is not None
        )
        estimated_partner_weight_count += sum(
            bool(row.get("isNetWgtEstimated")) for row in partner_rows
        )
        for row, weight in zip(partner_rows, partner_weights, strict=True):
            if weight is None:
                partner_missing_records.append(
                    {
                        "reporter": entry["reporter"],
                        "year": entry["year"],
                        "partner_code": row.get("partnerCode"),
                        "primary_value": row.get("primaryValue"),
                    }
                )
        positive_weights = [
            value for value in partner_weights
            if value is not None and value > 0
        ]
        known_sum = sum(positive_weights)
        known_hhi = (
            sum((value / known_sum) ** 2 for value in positive_weights)
            if known_sum > 0
            else None
        )
        world_weight = (
            finite_number(world_rows[0].get("netWgt"))
            if len(world_rows) == 1
            else None
        )
        ratio_to_world = (
            known_sum / world_weight
            if world_weight is not None and world_weight > 0 and known_sum > 0
            else None
        )
        if ratio_to_world is not None and not 0.98 <= ratio_to_world <= 1.02:
            partner_sum_ratio_outside_2pct.append(
                {
                    "request_id": request_id,
                    "ratio": ratio_to_world,
                }
            )
        if not records:
            status = "NA_NO_RECORD"
            no_record_ids.append(request_id)
        elif duplicate_partner_count or negative_partner_count:
            status = "FAIL_PARTNER_STRUCTURE"
            local_invalid += 1
        elif world_weight is None or world_weight <= 0:
            status = "CONDITIONAL_WORLD_WEIGHT_MISSING"
            conditional_ids.append(request_id)
        elif missing_partner_count:
            status = "CONDITIONAL_PARTNER_WEIGHT_MISSING"
            conditional_ids.append(request_id)
        else:
            status = "FULL"
        if known_sum > 0:
            for row, weight in zip(partner_rows, partner_weights, strict=True):
                partner_code = str(row.get("partnerCode"))
                if partner_code in {"490", "899"} and weight is not None:
                    residual_partner_rows.append(
                        {
                            "reporter": entry["reporter"],
                            "year": entry["year"],
                            "partner_code": partner_code,
                            "net_weight": weight,
                            "known_partner_share": weight / known_sum,
                            "hhi_status": status,
                        }
                    )
        if known_hhi is not None:
            destination = full_hhi if status == "FULL" else conditional_hhi
            destination.setdefault(entry["reporter"], {})[
                str(entry["year"])
            ] = known_hhi
        quality_by_reporter_year.setdefault(entry["reporter"], {})[
            str(entry["year"])
        ] = status

        body_verified = all(
            [
                entry["http_status"] == 200,
                body_digest == entry["sha256"],
                body_path.stat().st_size == entry["size_bytes"],
                header_digest == entry["header_sha256"],
                header_path.stat().st_size == entry["header_size_bytes"],
                document.get("count") == entry["top_level_count"],
                len(records) == entry["record_count"],
                entry["api_error"] == "",
                entry["invariant_status"] == "PASS",
                local_invalid == 0,
                local_duplicates == 0,
            ]
        )
        total_invalid_count += local_invalid
        total_duplicate_count += local_duplicates
        file_results.append(
            {
                "entry": entry,
                "request_id": request_id,
                "body_path": body_path,
                "header_path": header_path,
                "body_digest": body_digest,
                "header_digest": header_digest,
                "body_verified": body_verified,
                "hhi": known_hhi,
                "hhi_status": status,
            }
        )

    expected_quality = config["expected_hhi_weight_quality"]
    full_count = sum(
        result["hhi_status"] == "FULL" for result in file_results
    )
    no_record_count = sum(
        result["hhi_status"] == "NA_NO_RECORD" for result in file_results
    )
    expected_non_sau = sorted(set(config["reporters"]) - {"SAU"})
    historical_non_sau = sorted(
        reporter
        for reporter in expected_non_sau
        if all(
            quality_by_reporter_year[reporter][str(year)] != "NA_NO_RECORD"
            for year in range(2010, 2025)
        )
    )
    release_lag_2026 = sorted(
        reporter
        for reporter in config["reporters"]
        if quality_by_reporter_year[reporter]["2026"] == "NA_NO_RECORD"
    )
    available_2025 = sorted(
        reporter
        for reporter in config["reporters"]
        if quality_by_reporter_year[reporter]["2025"] != "NA_NO_RECORD"
    )
    expected_release = config["expected_release_state"]
    residual_counts = Counter(
        row["partner_code"] for row in residual_partner_rows
    )
    semantic_assertions_ok = all(
        [
            full_count == expected_quality["fully_computable_reporter_years"],
            no_record_count == expected_quality["no_record_reporter_years"],
            sorted(conditional_ids)
            == sorted(expected_quality["conditional_reporter_years"]),
            historical_non_sau == expected_non_sau,
            available_2025
            == sorted(expected_release["year_2025_available"]),
            release_lag_2026
            == sorted(expected_release["year_2026_not_yet_available"]),
            partner_sum_ratio_outside_2pct == [],
            estimated_record_count
            == expected_quality["estimated_record_count"],
            dict(sorted(residual_counts.items()))
            == expected_quality["residual_partner_code_counts"],
        ]
    )
    collection_lines = [
        f"{result['body_digest']}  raw/{result['request_id']}.json\n"
        for result in sorted(
            file_results,
            key=lambda row: (
                row["entry"]["year"],
                row["entry"]["reporter"],
            ),
        )
    ]
    collection_digest = hashlib.sha256(
        "".join(collection_lines).encode("utf-8")
    ).hexdigest()
    structure_ok = all(
        [
            file_set_ok,
            all(result["body_verified"] for result in file_results),
            total_invalid_count == 0,
            total_duplicate_count == 0,
            semantic_assertions_ok,
            collection_digest == config["expected_collection_sha256"],
        ]
    )
    full_value_rows = [
        (value, reporter, year)
        for reporter, years in full_hhi.items()
        for year, value in years.items()
    ]
    minimum_value, minimum_reporter, minimum_year = min(full_value_rows)
    maximum_value, maximum_reporter, maximum_year = max(full_value_rows)
    notes = (
        "All 153 UN Comtrade HS2709 annual responses for nine reporters in "
        "2010--2026 are hash-pinned with response headers and structural "
        "invariants. Comtrade reporter-area codes are used: USA=842, "
        "India=699 and Norway=579, not their M49 reference codes. Correcting "
        "Norway recovers 2022--2024 records. The eight non-Saudi reporters "
        "have data throughout 2010--2024; Saudi Arabia remains NA, never "
        "HHI=0. China 2025 and all reporters in 2026 are release-lag empty. "
        "Only 121 reporter-years have FULL weight HHI; six GBR years are "
        "conditional and are excluded from the primary statistic. The "
        "original nine-country 2010--2026 variable remains P0 FAIL."
    )
    audits = [
        audit_row(
            variable_id="supplier_hhi",
            artifact_id="UNCOMTRADE_HS2709_2010_2026_20260730",
            series_id="UNCOMTRADE_HS2709_IMPORT_WEIGHT_HHI",
            digest=collection_digest,
            row_count=len(file_results),
            valid_count=full_count,
            missing_count=len(file_results) - full_count,
            invalid_count=total_invalid_count,
            duplicate_count=total_duplicate_count,
            start_date="2010-01-01",
            last_date="2025-01-01",
            required_end_date="2026-01-01",
            frequency="annual",
            unit="HHI from normalized positive partner net-weight shares",
            row_coverage=1.0,
            value_coverage=full_count / len(file_results),
            endpoint_coverage=0,
            minimum=minimum_value,
            maximum=maximum_value,
            structure_ok=structure_ok,
            p0_status="FAIL",
            notes=notes,
            minimum_date=minimum_year + "-01-01",
            maximum_date=maximum_year + "-01-01",
        )
    ]
    manifests: list[dict[str, str]] = []
    for result in file_results:
        entry = result["entry"]
        base_id = (
            f"UNCOMTRADE_HS2709_{entry['reporter']}_"
            f"{entry['year']}_20260730"
        )
        manifests.append(
            manifest_row(
                artifact_id=base_id + "_BODY",
                variable_id="supplier_hhi_raw",
                source_id="SRC_UN_COMTRADE",
                official_url=config["official_url"],
                download_url=entry["download_url"],
                local_path=entry["path"],
                retrieved_at_utc=entry["retrieved_at_utc"],
                digest=result["body_digest"],
                size_bytes=entry["size_bytes"],
                format_name="json",
                provider="United Nations",
                distributor="UN Comtrade API",
                terms=config["license_or_terms"],
                verified=result["body_verified"],
                notes=(
                    "Untouched public API response; reporter-area code is "
                    "distinct from M49 where documented."
                ),
            )
        )
        manifests.append(
            manifest_row(
                artifact_id=base_id + "_HEADERS",
                variable_id="supplier_hhi_http_headers",
                source_id="SRC_UN_COMTRADE",
                official_url=config["api_docs_url"],
                download_url=entry["download_url"],
                local_path=entry["header_path"],
                retrieved_at_utc=entry["retrieved_at_utc"],
                digest=result["header_digest"],
                size_bytes=entry["header_size_bytes"],
                format_name="http response headers",
                provider="United Nations",
                distributor="UN Comtrade API",
                terms=config["license_or_terms"],
                verified=result["body_verified"],
                notes="Frozen final HTTP 200 response headers for the body.",
            )
        )
    manifests.append(
        manifest_row(
            artifact_id="UNCOMTRADE_HS2709_2010_2026_20260730",
            variable_id="supplier_hhi",
            source_id="SRC_UN_COMTRADE",
            official_url=config["official_url"],
            download_url=config["endpoint"],
            local_path="data/raw/trade_energy/comtrade_hs2709_history",
            retrieved_at_utc=max(
                entry["retrieved_at_utc"] for entry in config["files"]
            ),
            digest=collection_digest,
            size_bytes=sum(entry["size_bytes"] for entry in config["files"]),
            format_name="json collection",
            provider="United Nations",
            distributor="UN Comtrade API",
            terms=config["license_or_terms"],
            verified=structure_ok,
            notes=(
                "Logical digest over 153 sorted body hashes; per-response "
                "headers, classification vintages and weight quality remain "
                "separately auditable."
            ),
        )
    )
    details = {
        "structure_status": "PASS" if structure_ok else "FAIL",
        "file_count": len(file_results),
        "manifest_count": len(manifests),
        "record_count": total_record_count,
        "collection_sha256": collection_digest,
        "full_hhi_by_reporter_year": full_hhi,
        "conditional_hhi_by_reporter_year": conditional_hhi,
        "hhi_quality_by_reporter_year": quality_by_reporter_year,
        "full_hhi_count": full_count,
        "no_record_reporter_years": sorted(no_record_ids),
        "conditional_reporter_years": sorted(conditional_ids),
        "historical_non_sau_reporters": historical_non_sau,
        "available_2025_reporters": available_2025,
        "release_lag_2026_reporters": release_lag_2026,
        "partner_net_weight_missing_records": partner_missing_records,
        "estimated_record_count": estimated_record_count,
        "estimated_partner_weight_count": estimated_partner_weight_count,
        "residual_partner_rows": residual_partner_rows,
        "residual_partner_code_counts": dict(sorted(residual_counts.items())),
        "minimum_hhi_reporter": minimum_reporter,
        "maximum_hhi_reporter": maximum_reporter,
        "classification_codes_by_year": {
            year: sorted(values)
            for year, values in sorted(classification_by_year.items())
        },
        "reporter_area_codes": {
            reporter: values["reporter_area_code"]
            for reporter, values in config["reporters"].items()
        },
        "m49_reference_codes": {
            reporter: values["m49_reference_code"]
            for reporter, values in config["reporters"].items()
        },
    }
    return audits, manifests, details

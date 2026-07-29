"""Parse and audit the IEA selected-emergency-measures JavaScript arrays."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from src.data.audit_github_snapshot import (
    AUDIT_COLUMNS,
    MANIFEST_COLUMNS,
    METADATA_DIR,
    PROJECT_ROOT,
    ratio,
)


DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "iea_policy_snapshot.json"


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def decode_js_string(payload: str) -> str:
    """Decode the limited escape syntax used by the bundled JS strings."""
    result: list[str] = []
    index = 0
    escapes = {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "b": "\b",
        "f": "\f",
        "v": "\v",
        "0": "\0",
    }
    while index < len(payload):
        char = payload[index]
        if char != "\\":
            result.append(char)
            index += 1
            continue
        if index + 1 >= len(payload):
            raise ValueError("Trailing backslash in JavaScript string")
        escaped = payload[index + 1]
        if escaped == "u":
            codepoint = payload[index + 2 : index + 6]
            if len(codepoint) != 4:
                raise ValueError("Incomplete JavaScript unicode escape")
            result.append(chr(int(codepoint, 16)))
            index += 6
        elif escaped == "x":
            codepoint = payload[index + 2 : index + 4]
            if len(codepoint) != 2:
                raise ValueError("Incomplete JavaScript hex escape")
            result.append(chr(int(codepoint, 16)))
            index += 4
        elif escaped in escapes:
            result.append(escapes[escaped])
            index += 2
        else:
            result.append(escaped)
            index += 2
    return "".join(result)


def extract_json_parse_array(text: str, variable: str) -> list[dict[str, Any]]:
    marker = f"{variable} ="
    variable_start = text.index(marker)
    call_start = text.index("JSON.parse(", variable_start) + len("JSON.parse(")
    quote = text[call_start]
    if quote not in {"'", '"', "`"}:
        raise ValueError(f"Unexpected JSON.parse delimiter for {variable}")
    index = call_start + 1
    raw: list[str] = []
    while index < len(text):
        char = text[index]
        if char == quote:
            backslashes = 0
            lookback = index - 1
            while lookback >= call_start and text[lookback] == "\\":
                backslashes += 1
                lookback -= 1
            if backslashes % 2 == 0:
                break
        raw.append(char)
        index += 1
    else:
        raise ValueError(f"Unterminated JSON.parse string for {variable}")
    decoded = decode_js_string("".join(raw))
    parsed = json.loads(decoded)
    if not isinstance(parsed, list):
        raise ValueError(f"{variable} did not parse to an array")
    return parsed


def extract_literal_array(text: str, variable: str) -> list[dict[str, Any]]:
    start = text.index(f"{variable} =") + len(f"{variable} =")
    start = text.index("[", start)
    end = text.index("], U =", start) + 1
    payload = text[start:end]
    payload = re.sub(
        r"([,{]\s*)(Electrification|Other)(\s*:)",
        r'\1"\2"\3',
        payload,
    )
    parsed = json.loads(payload)
    if not isinstance(parsed, list):
        raise ValueError(f"{variable} did not parse to an array")
    return parsed


def parse_tables(text: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "energy_conservation": extract_json_parse_array(text, "fn"),
        "consumer_support": extract_json_parse_array(text, "gn"),
        "structural_policies": extract_literal_array(text, "mn"),
    }


def run_audit(
    config_path: Path = DEFAULT_CONFIG,
    write: bool = True,
) -> dict[str, Any]:
    config = load_config(config_path)
    path = PROJECT_ROOT / config["path"]
    if not path.exists():
        raise FileNotFoundError(
            f"Missing ignored IEA raw file {config['path']}; rerun the "
            "official static-resource download before this component audit."
        )
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    text = payload.decode("utf-8")
    tables = parse_tables(text)

    table_details: dict[str, dict[str, Any]] = {}
    all_countries: set[str] = set()
    structure_ok = digest == config["sha256"] and len(payload) == config[
        "size_bytes"
    ]
    total_rows = 0
    country_table_rows = 0
    legend_rows = 0
    total_policy_cells = 0
    total_nonempty_cells = 0
    for table_id, expected in config["expected_tables"].items():
        rows = tables[table_id]
        if not rows or rows[0].get("Country/region") is not None:
            raise ValueError(f"{table_id} has no leading legend row")
        legend = rows[0]
        country_rows = rows[1:]
        categories = sorted(
            key for key in legend if key != "Country/region"
        )
        countries = [
            row["Country/region"]
            for row in country_rows
            if row.get("Country/region") is not None
        ]
        policy_cell_count = len(country_rows) * len(categories)
        nonempty_policy_cell_count = sum(
            row.get(category) is not None
            for row in country_rows
            for category in categories
        )
        null_policy_cell_count = (
            policy_cell_count - nonempty_policy_cell_count
        )
        table_ok = all(
            [
                len(rows) == expected["row_count"],
                len(country_rows) == expected["country_count"],
                categories == sorted(expected["required_labels"]),
                policy_cell_count == expected["policy_cell_count"],
                nonempty_policy_cell_count
                == expected["nonempty_policy_cell_count"],
                len(countries) == len(country_rows),
                len(set(countries)) == len(countries),
            ]
        )
        structure_ok = structure_ok and table_ok
        total_rows += len(rows)
        country_table_rows += len(country_rows)
        legend_rows += 1
        total_policy_cells += policy_cell_count
        total_nonempty_cells += nonempty_policy_cell_count
        all_countries.update(countries)
        table_details[table_id] = {
            "row_count": len(rows),
            "country_table_row_count": len(country_rows),
            "legend_row_count": 1,
            "categories": categories,
            "country_count_within_table": len(set(countries)),
            "policy_cell_count": policy_cell_count,
            "nonempty_policy_cell_count": nonempty_policy_cell_count,
            "null_policy_cell_count": null_policy_cell_count,
            "structure_status": "PASS" if table_ok else "FAIL",
        }

    expected_distinct = config["expected_distinct_country_count"]
    structure_ok = structure_ok and len(all_countries) == expected_distinct
    semantic_blocker = (
        "The static IEA resource is an overview of selected measures, not an "
        "index-ready or dated policy panel. Null means that this category cell "
        "is unrecorded in this snapshot; a country absent from one category "
        "table means only that it is not covered by that table. The file has "
        "no common implementation date, end date, budget, legal status, "
        "magnitude, or effect fields. Nonempty cells cannot be interpreted as "
        "policy counts, intensity, or outcomes."
    )
    audit = {
        "variable_id": config["variable_id"],
        "artifact_id": config["artifact_id"],
        "series_id": config["series_id"],
        "snapshot_commit": "",
        "sha256": digest,
        "row_count": str(total_rows),
        "valid_count": str(country_table_rows),
        "missing_marker_count": str(
            total_policy_cells - total_nonempty_cells
        ),
        "invalid_row_count": "0",
        "duplicate_date_count": "0",
        "start_date": "",
        "last_calendar_row_date": "",
        "last_valid_date": "",
        "required_end_date": "",
        "frequency": "static qualitative snapshot",
        "unit": "text category coverage",
        "calendar_row_coverage_ratio": "0.000000",
        "core_value_coverage_ratio": ratio(
            total_nonempty_cells,
            total_policy_cells,
        ),
        "event_calendar_coverage_ratio": "0.000000",
        "event_value_coverage_ratio": "0.000000",
        "publication_lag_calendar_days": "",
        "min_value": "",
        "min_value_date": "",
        "max_value": "",
        "max_value_date": "",
        "negative_value_count": "0",
        "structure_status": "PASS" if structure_ok else "FAIL",
        "p0_status": "FAIL",
        "notes": semantic_blocker,
    }
    manifest = {
        "artifact_id": config["artifact_id"],
        "variable_id": config["variable_id"],
        "source_id": config["source_id"],
        "repository": "",
        "repository_branch": "",
        "repository_commit": "",
        "repository_blob_sha": "",
        "official_url": config["official_url"],
        "download_url": config["download_url"],
        "local_path": config["path"],
        "retrieved_at_utc": config["retrieved_at_utc"],
        "sha256": digest,
        "size_bytes": str(len(payload)),
        "format": "javascript",
        "underlying_provider": "International Energy Agency",
        "distributor": "International Energy Agency static resource",
        "license_or_terms": config["license_or_terms"],
        "official_byte_identical_at_snapshot": "true",
        "status": (
            "audited_external_not_committed"
            if structure_ok
            else "failed_audit"
        ),
        "notes": (
            "Direct official static-resource response; all three arrays were "
            "parsed and audited as qualitative category coverage only."
        ),
    }
    summary = {
        "artifact_count": 1,
        "structure_pass_count": int(structure_ok),
        "p0_pass_count": 0,
        "p0_blocked_count": 0,
        "p0_fail_count": 1,
        "series": [audit],
        "manifest": [manifest],
        "table_details": table_details,
        "country_table_row_count": country_table_rows,
        "distinct_country_count": len(all_countries),
        "legend_row_count": legend_rows,
        "policy_cell_count": total_policy_cells,
        "nonempty_policy_cell_count": total_nonempty_cells,
        "null_policy_cell_count": total_policy_cells - total_nonempty_cells,
        "semantic_disposition": "coverage_snapshot_only",
        "audit_columns": AUDIT_COLUMNS,
        "manifest_columns": MANIFEST_COLUMNS,
    }
    if write:
        with (METADATA_DIR / "iea_policy_snapshot_audit.json").open(
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
    print(f"IEA policy artifacts audited: {summary['artifact_count']}")
    print(f"Structural PASS: {summary['structure_pass_count']}")
    print("P0 semantic status: FAIL (coverage snapshot only)")
    return 0 if summary["structure_pass_count"] == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())

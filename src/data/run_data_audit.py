"""Run component audits and write the combined P0 data disposition tables."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from src.data.audit_eia_gulf_pdf import audit_gulf_pdf
from src.data.audit_eia_snapshot import run_audit as run_eia_audit
from src.data.audit_event_e08_evidence import run_audit as run_event_e08_audit
from src.data.audit_iea_policy_snapshot_v2 import run_audit as run_iea_policy_audit
from src.data.audit_ndrc_snapshot import run_audit as run_ndrc_audit
from src.data.audit_oecd_snapshot_v2 import run_audit as run_oecd_audit
from src.data.audit_trade_energy_snapshot import run_audit as run_trade_audit
from src.data.audit_github_snapshot import (
    AUDIT_COLUMNS,
    AVAILABILITY_COLUMNS,
    MANIFEST_COLUMNS,
    METADATA_DIR,
    PROJECT_ROOT,
    audit_one,
    load_config as load_github_config,
    run_audit as run_github_audit,
    write_csv,
)

BLOCKERS_CONFIG = PROJECT_ROOT / "configs" / "data_blockers.json"
ACCESS_BLOCKERS_CONFIG = (
    PROJECT_ROOT / "configs" / "data_access_blockers_20260729.json"
)
P0_FAIL_NEXT_ACTIONS = {
    "china_exports": (
        "Acquire and audit the complete 2010-2026 monthly GACC export "
        "history; keep the June 2026 workbook as endpoint cross-check."
    ),
    "china_crude_import_qty": (
        "Acquire and audit the complete 2010-2026 monthly GACC crude "
        "import quantity history in the same physical unit."
    ),
    "china_crude_import_value": (
        "Acquire and audit the complete 2010-2026 monthly GACC crude "
        "import value history and resolve the comparison-title conflict."
    ),
    "peer_cpi": (
        "Retain USA 2025-10 as missing; obtain an official replacement "
        "observation or use an explicitly unbalanced-panel method."
    ),
    "net_oil_import_dependency": (
        "Treat the audited eight-country 193/197-month panel as the M1 "
        "candidate; exclude India explicitly unless a defensible alternate "
        "series resolves its 111/197 coverage and 195 semantic conflicts."
    ),
    "supplier_hhi": (
        "Evaluate the audited eight-country 2010-2024 full-weight HHI panel "
        "at M1; keep six conditional GBR years out of the primary series, "
        "exclude SAU explicitly, and treat 2025-2026 as ragged/release lag."
    ),
    "policy_response_index": (
        "Use the IEA snapshot only as qualitative category evidence; "
        "acquire dated magnitude and implementation fields before any "
        "transparent index construction."
    ),
}


def read_dictionary() -> list[dict[str, str]]:
    with (METADATA_DIR / "data_dictionary.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        return list(csv.DictReader(handle))


def read_blockers() -> dict[str, dict[str, Any]]:
    blockers: dict[str, dict[str, Any]] = {}
    for path in (BLOCKERS_CONFIG, ACCESS_BLOCKERS_CONFIG):
        with path.open("r", encoding="utf-8") as handle:
            current = json.load(handle)
        overlap = set(blockers) & set(current)
        if overlap:
            raise ValueError(f"Duplicate blocker definitions: {sorted(overlap)}")
        blockers.update(current)
    return blockers


def github_manifest_rows() -> list[dict[str, str]]:
    config = load_github_config()
    snapshot = config["snapshot"]
    return [audit_one(snapshot, entry)[1] for entry in config["series"]]


def combined_availability(
    audit_rows: list[dict[str, str]],
    manifest_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    audit_by_variable = {row["variable_id"]: row for row in audit_rows}
    artifact_by_variable = {
        row["variable_id"]: row["artifact_id"] for row in manifest_rows
    }
    blockers = read_blockers()
    rows: list[dict[str, str]] = []
    for variable in read_dictionary():
        if variable["priority"] != "P0":
            continue
        variable_id = variable["variable_id"]
        audit = audit_by_variable.get(variable_id)
        if audit:
            if audit["p0_status"] == "PASS":
                availability_status = "audited_p0_pass"
                blocker = ""
                next_action = "Freeze this artifact for the P0 snapshot."
            elif audit["p0_status"] == "BLOCKED_RELEASE_LAG":
                availability_status = "audited_blocked_release_lag"
                blocker = (
                    f"Latest observed or historical period "
                    f"{audit['last_valid_date']} is earlier than required "
                    f"{audit['required_end_date']}."
                )
                if variable_id in {"global_oil_supply", "global_oil_demand"}:
                    next_action = (
                        "Retain later STEO estimates/forecasts with an explicit "
                        "vintage flag; replace them when historical observations "
                        "become available."
                    )
                elif variable_id == "gulf_shut_in_mbd":
                    next_action = (
                        "Use March-June observations only; retain 3Q26 and 4Q26 "
                        "forecasts as separate scenario variables and never "
                        "interpolate them into months."
                    )
                else:
                    next_action = (
                        "Refresh after the next official release and rerun audit."
                    )
            else:
                availability_status = "audited_failed"
                blocker = audit["notes"]
                next_action = P0_FAIL_NEXT_ACTIONS.get(
                    variable_id,
                    "Replace the source or formally redefine the variable.",
                )
        elif variable_id in blockers:
            disposition = blockers[variable_id]
            availability_status = disposition["availability_status"]
            blocker = disposition["blocker"]
            next_action = disposition["next_action"]
        elif variable["source_id"] == "SRC_DERIVED":
            availability_status = "blocked_upstream"
            blocker = "Required upstream raw variables are not all frozen."
            next_action = "Compute only after upstream files pass P0 audit."
        else:
            availability_status = "not_acquired"
            blocker = "No frozen raw artifact has been audited."
            next_action = f"Acquire and audit from {variable['source_id']}."
        rows.append(
            {
                "variable_id": variable_id,
                "question": variable["question"],
                "priority": variable["priority"],
                "source_id": variable["source_id"],
                "artifact_id": artifact_by_variable.get(variable_id, ""),
                "availability_status": availability_status,
                "blocker": blocker,
                "next_action": next_action,
            }
        )
    return rows


def run_combined_audit(write: bool = True) -> dict[str, Any]:
    github = run_github_audit(write=write)
    eia = run_eia_audit(write=write)
    event_e08 = run_event_e08_audit(write=write)
    gulf = audit_gulf_pdf(write=write)
    iea_policy = run_iea_policy_audit(write=write)
    ndrc = run_ndrc_audit(write=write)
    oecd = run_oecd_audit(write=write)
    trade = run_trade_audit(write=write)

    audit_rows = (
        github["series"]
        + eia["series"]
        + gulf["series"]
        + iea_policy["series"]
        + ndrc["series"]
        + oecd["series"]
        + trade["series"]
    )
    manifest_rows = (
        github_manifest_rows()
        + event_e08["manifest"]
        + eia["manifest"]
        + gulf["manifest"]
        + iea_policy["manifest"]
        + ndrc["manifest"]
        + oecd["manifest"]
        + trade["manifest"]
    )
    availability_rows = combined_availability(audit_rows, manifest_rows)
    summary = {
        "data_cutoff": "2026-07-29",
        "github_snapshot_commit": github["snapshot"]["commit_sha"],
        "event_e08_evidence_status": event_e08["structure_status"],
        "event_e08_evidence_source_count": event_e08["source_count"],
        "artifact_count": len(audit_rows),
        "structure_pass_count": sum(
            row["structure_status"] == "PASS" for row in audit_rows
        ),
        "p0_pass_count": sum(row["p0_status"] == "PASS" for row in audit_rows),
        "p0_blocked_count": sum(
            row["p0_status"] == "BLOCKED_RELEASE_LAG" for row in audit_rows
        ),
        "p0_fail_count": sum(row["p0_status"] == "FAIL" for row in audit_rows),
        "p0_variable_count": len(availability_rows),
        "audited_variable_count": len(
            {row["variable_id"] for row in audit_rows}
        ),
        "not_acquired_count": sum(
            row["availability_status"] == "not_acquired"
            for row in availability_rows
        ),
        "derived_blocked_count": sum(
            row["availability_status"] == "blocked_upstream"
            for row in availability_rows
        ),
        "external_blocked_count": sum(
            row["availability_status"] == "blocked_public_access"
            for row in availability_rows
        ),
        "manual_action_required_count": sum(
            row["availability_status"]
            == "acquisition_manual_action_required"
            for row in availability_rows
        ),
        "availability_status_counts": {
            status: sum(
                row["availability_status"] == status
                for row in availability_rows
            )
            for status in sorted(
                {row["availability_status"] for row in availability_rows}
            )
        },
        "series": audit_rows,
        "rejected_proxies": gulf["rejected_proxies"],
    }
    if write:
        write_csv(METADATA_DIR / "audit_results.csv", AUDIT_COLUMNS, audit_rows)
        write_csv(
            METADATA_DIR / "download_manifest.csv",
            MANIFEST_COLUMNS,
            manifest_rows,
        )
        write_csv(
            METADATA_DIR / "data_availability.csv",
            AVAILABILITY_COLUMNS,
            availability_rows,
        )
        with (METADATA_DIR / "data_audit_summary.json").open(
            "w", encoding="utf-8"
        ) as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

        unique_artifacts: dict[str, str] = {}
        for row in manifest_rows:
            if "collection" not in row["format"]:
                unique_artifacts[row["local_path"]] = row["sha256"]

        with (METADATA_DIR / "checksums.sha256").open(
            "w", encoding="utf-8", newline="\n"
        ) as handle:
            for local_path, digest in sorted(unique_artifacts.items()):
                handle.write(f"{digest}  {local_path}\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    summary = run_combined_audit(write=not args.check_only)
    print(f"Combined artifacts audited: {summary['artifact_count']}")
    print(f"Structural PASS: {summary['structure_pass_count']}")
    print(f"P0 PASS: {summary['p0_pass_count']}")
    print(f"P0 blocked: {summary['p0_blocked_count']}")
    print(f"P0 failed: {summary['p0_fail_count']}")
    print(f"P0 variables tracked: {summary['p0_variable_count']}")
    print(f"P0 external variables not acquired: {summary['not_acquired_count']}")
    print(
        f"P0 external variables blocked by public access: "
        f"{summary['external_blocked_count']}"
    )
    print(
        f"P0 variables requiring manual acquisition: "
        f"{summary['manual_action_required_count']}"
    )
    print(f"P0 derived variables blocked upstream: {summary['derived_blocked_count']}")
    return (
        0
        if summary["structure_pass_count"] == summary["artifact_count"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())

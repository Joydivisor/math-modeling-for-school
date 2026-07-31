"""Audit frozen source evidence for the E08 renewed-escalation event."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from src.data.audit_github_snapshot import METADATA_DIR, PROJECT_ROOT

DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "event_e08_evidence_20260730.json"
TIMELINE_PATH = METADATA_DIR / "event_timeline.csv"
OUTPUT_PATH = METADATA_DIR / "event_e08_evidence_audit.json"


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_timeline_event(event_id: str) -> dict[str, str]:
    with TIMELINE_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        matches = [
            row for row in csv.DictReader(handle)
            if row["event_id"] == event_id
        ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one timeline row for {event_id}, got {len(matches)}"
        )
    return matches[0]


def manifest_row(
    entry: dict[str, Any],
    *,
    verified: bool,
    observed_sha256: str,
    observed_size_bytes: int,
) -> dict[str, str]:
    return {
        "artifact_id": entry["artifact_id"],
        "variable_id": "event_timeline_e08",
        "source_id": entry["source_id"],
        "repository": "",
        "repository_branch": "",
        "repository_commit": "",
        "repository_blob_sha": "",
        "official_url": entry["official_url"],
        "download_url": entry["download_url"],
        "local_path": entry["local_path"],
        "retrieved_at_utc": entry["retrieved_at_utc"],
        "sha256": observed_sha256,
        "size_bytes": str(observed_size_bytes),
        "format": "html",
        "underlying_provider": entry["provider"],
        "distributor": entry["distributor"],
        "license_or_terms": entry["license_or_terms"],
        "official_byte_identical_at_snapshot": (
            "true" if verified else "false"
        ),
        "status": (
            "audited_external_not_committed"
            if verified
            else "audit_failed_do_not_use"
        ),
        "notes": (
            f"Frozen {entry['role']} evidence for E08. "
            f"{entry['event_time_note']}"
        ),
    }


def run_audit(
    config_path: Path = DEFAULT_CONFIG,
    write: bool = True,
) -> dict[str, Any]:
    config = load_config(config_path)
    timeline = read_timeline_event(config["event_id"])
    details: list[dict[str, Any]] = []
    manifest: list[dict[str, str]] = []

    for entry in config["sources"]:
        path = PROJECT_ROOT / entry["local_path"]
        payload = path.read_bytes()
        text = payload.decode("utf-8", errors="replace")
        marker_results = {
            marker: marker in text for marker in entry["expected_markers"]
        }
        observed_sha256 = sha256_bytes(payload)
        checks = {
            "sha256": observed_sha256 == entry["sha256"],
            "size_bytes": len(payload) == entry["size_bytes"],
            "expected_markers": all(marker_results.values()),
        }
        details.append(
            {
                "artifact_id": entry["artifact_id"],
                "source_id": entry["source_id"],
                "role": entry["role"],
                "local_path": entry["local_path"],
                "observed_sha256": observed_sha256,
                "observed_size_bytes": len(payload),
                "marker_results": marker_results,
                "checks": checks,
                "status": "PASS" if all(checks.values()) else "FAIL",
                "event_time_note": entry["event_time_note"],
            }
        )
        manifest.append(
            manifest_row(
                entry,
                verified=all(checks.values()),
                observed_sha256=observed_sha256,
                observed_size_bytes=len(payload),
            )
        )

    config_source_ids = {entry["source_id"] for entry in config["sources"]}
    timeline_source_ids = set(timeline["source_ids"].split("|"))
    timeline_checks = {
        "date_start": timeline["date_start"] == config["date_start"],
        "date_end": timeline["date_end"] == config["date_end"],
        "verification_status": (
            timeline["verification_status"] == config["verification_status"]
        ),
        "source_ids": config_source_ids <= timeline_source_ids,
        "causal_role": timeline["causal_role"] == "treatment",
    }
    roles = {entry["role"] for entry in config["sources"]}
    evidence_checks = {
        "primary_source_present": "primary" in roles,
        "independent_institutional_source_present": (
            "independent_institutional" in roles
        ),
        "independent_news_source_present": "independent_news" in roles,
        "publication_metadata_present": "publication_metadata" in roles,
        "unique_artifact_ids": len(
            {entry["artifact_id"] for entry in config["sources"]}
        ) == len(config["sources"]),
        "unique_source_ids": len(config_source_ids) == len(config["sources"]),
    }
    structure_ok = (
        all(detail["status"] == "PASS" for detail in details)
        and all(timeline_checks.values())
        and all(evidence_checks.values())
    )
    summary = {
        "event_id": config["event_id"],
        "date_start": config["date_start"],
        "date_end": config["date_end"],
        "source_count": len(details),
        "source_pass_count": sum(
            detail["status"] == "PASS" for detail in details
        ),
        "structure_status": "PASS" if structure_ok else "FAIL",
        "timeline_checks": timeline_checks,
        "evidence_checks": evidence_checks,
        "details": details,
        "manifest": manifest,
    }
    if write:
        with OUTPUT_PATH.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    summary = run_audit(args.config, write=not args.check_only)
    print(f"E08 evidence sources: {summary['source_count']}")
    print(f"E08 source PASS: {summary['source_pass_count']}")
    print(f"E08 structure status: {summary['structure_status']}")
    return 0 if summary["structure_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
"""Human-entered findings tied to governed IL2CPP artifact manifests."""

from __future__ import annotations

import json
from pathlib import Path

from .shared import DEFAULT_OUTPUT_ROOT, make_run_id, utc_timestamp, write_json


def run_il2cpp_manual_findings_report(
    *,
    catalog_path: Path | None = None,
    name_hint_report_path: Path | None = None,
    finding_paths: list[str],
    finding_notes: list[str],
    finding_symbols: list[str] | None = None,
    finding_kinds: list[str] | None = None,
    analyst: str | None = None,
    notes: str | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> Path:
    """Record human observations against cataloged IL2CPP output paths."""

    if (catalog_path is None) == (name_hint_report_path is None):
        raise ValueError("Provide exactly one of catalog_path or name_hint_report_path.")
    if not finding_paths:
        raise ValueError("At least one finding_path is required.")
    if len(finding_paths) != len(finding_notes):
        raise ValueError("finding_paths and finding_notes must have the same number of entries.")
    if finding_symbols and len(finding_symbols) != len(finding_paths):
        raise ValueError("finding_symbols must be omitted or have the same number of entries as finding_paths.")
    if finding_kinds and len(finding_kinds) != len(finding_paths):
        raise ValueError("finding_kinds must be omitted or have the same number of entries as finding_paths.")

    source_catalog_path: str
    source_name_hint_report_path: str | None = None
    source_snapshot_path: str | None
    if catalog_path is not None:
        resolved_catalog_dir = catalog_path.resolve()
        if not resolved_catalog_dir.is_dir():
            raise FileNotFoundError(f"IL2CPP output catalog directory does not exist: {resolved_catalog_dir}")
        catalog_manifest = _load_manifest(resolved_catalog_dir / "manifest.json", "IL2CPP output catalog")
        source_catalog_path = str(resolved_catalog_dir)
        source_snapshot_path = _string_or_none(catalog_manifest.get("source_snapshot_path"))
    else:
        assert name_hint_report_path is not None
        resolved_name_hint_dir = name_hint_report_path.resolve()
        if not resolved_name_hint_dir.is_dir():
            raise FileNotFoundError(
                f"IL2CPP name-hint-report directory does not exist: {resolved_name_hint_dir}"
            )
        name_hint_manifest = _load_manifest(
            resolved_name_hint_dir / "manifest.json",
            "IL2CPP name-hint-report",
        )
        source_name_hint_report_path = str(resolved_name_hint_dir)
        source_snapshot_path = _string_or_none(name_hint_manifest.get("source_snapshot_path"))
        source_catalog_path = _required_string(
            name_hint_manifest.get("source_catalog_path"),
            "IL2CPP name-hint-report source_catalog_path",
        )
        catalog_manifest = _load_manifest(Path(source_catalog_path) / "manifest.json", "IL2CPP output catalog")

    inventory = _extract_file_inventory(catalog_manifest)
    findings = _build_findings(
        inventory=inventory,
        finding_paths=finding_paths,
        finding_notes=finding_notes,
        finding_symbols=finding_symbols or [],
        finding_kinds=finding_kinds or [],
    )

    report_seed = Path(source_name_hint_report_path or source_catalog_path).name
    report_id = make_run_id(f"il2cpp_manual_findings_report_{report_seed}")
    report_dir = output_root / "il2cpp_manual_findings_reports" / report_id
    report_dir.mkdir(parents=True, exist_ok=False)

    manifest = {
        "schema_version": "il2cpp-manual-findings-report-v1",
        "command_name": "il2cpp-manual-findings-report",
        "created_at_utc": utc_timestamp(),
        "source_catalog_path": source_catalog_path,
        "source_name_hint_report_path": source_name_hint_report_path,
        "source_snapshot_path": source_snapshot_path,
        "analyst": analyst,
        "notes": notes,
        "findings": findings,
        "note": (
            "Human-entered observations only. "
            "This command does not open external files and does not validate semantic correctness."
        ),
    }
    write_json(report_dir / "manifest.json", manifest)

    summary_lines = [
        f"report_path: {report_dir.resolve()}",
        f"source_catalog_path: {source_catalog_path}",
        f"source_name_hint_report_path: {source_name_hint_report_path or 'none'}",
        f"source_snapshot_path: {source_snapshot_path or 'unknown'}",
        f"analyst: {analyst or 'unknown'}",
        f"finding_count: {len(findings)}",
    ]
    if notes:
        summary_lines.extend(["", "notes:", notes])
    summary_lines.extend(["", "findings:"])
    summary_lines.extend(
        _render_finding_line(item)
        for item in findings
    )
    summary_lines.extend(
        [
            "",
            "scope_note:",
            "This report records human semantic interpretation as analyst-supplied notes tied to governed artifacts only.",
        ]
    )
    (report_dir / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return report_dir


def _load_manifest(path: Path, label: str) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing required manifest: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} manifest is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} manifest must be a JSON object: {path}")
    return payload


def _extract_file_inventory(catalog_manifest: dict[str, object]) -> dict[str, dict[str, object]]:
    file_inventory = catalog_manifest.get("file_inventory")
    if not isinstance(file_inventory, list):
        raise ValueError("IL2CPP output catalog manifest is missing a valid file_inventory list.")
    inventory_by_path: dict[str, dict[str, object]] = {}
    for item in file_inventory:
        if not isinstance(item, dict):
            raise ValueError("IL2CPP output catalog manifest contains a non-object file_inventory entry.")
        relative_path = _required_string(item.get("relative_path"), "catalog relative_path")
        size_bytes = item.get("size_bytes")
        sha256 = _required_string(item.get("sha256"), "catalog sha256")
        if not isinstance(size_bytes, int):
            raise ValueError("IL2CPP output catalog manifest contains an invalid size_bytes entry.")
        inventory_by_path[relative_path] = {
            "relative_path": relative_path,
            "size_bytes": size_bytes,
            "sha256": sha256,
        }
    return inventory_by_path


def _build_findings(
    *,
    inventory: dict[str, dict[str, object]],
    finding_paths: list[str],
    finding_notes: list[str],
    finding_symbols: list[str],
    finding_kinds: list[str],
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for index, relative_path in enumerate(finding_paths):
        normalized_path = relative_path.strip()
        if normalized_path not in inventory:
            raise FileNotFoundError(
                f"Finding path is not present in the referenced catalog inventory: {normalized_path}"
            )
        inventory_entry = inventory[normalized_path]
        findings.append(
            {
                "relative_path": normalized_path,
                "size_bytes": int(inventory_entry["size_bytes"]),
                "sha256": str(inventory_entry["sha256"]),
                "finding_note": finding_notes[index],
                "finding_symbol": finding_symbols[index] if index < len(finding_symbols) else None,
                "finding_kind": finding_kinds[index] if index < len(finding_kinds) else None,
            }
        )
    return findings


def _required_string(value: object, label: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    raise ValueError(f"{label} is required and must be a non-empty string.")


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _render_finding_line(finding: dict[str, object]) -> str:
    suffix_parts = [
        f"size_bytes={finding['size_bytes']}",
        f"sha256={finding['sha256']}",
        f"note={finding['finding_note']}",
    ]
    if finding.get("finding_symbol"):
        suffix_parts.append(f"symbol={finding['finding_symbol']}")
    if finding.get("finding_kind"):
        suffix_parts.append(f"kind={finding['finding_kind']}")
    return f"- {finding['relative_path']} " + " ".join(suffix_parts)

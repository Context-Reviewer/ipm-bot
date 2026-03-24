"""Read-only cataloging for externally generated IL2CPP reconstruction output directories."""

from __future__ import annotations

import json
from pathlib import Path

from .shared import DEFAULT_OUTPUT_ROOT, make_run_id, sha256_bytes, utc_timestamp, write_json


def run_il2cpp_output_catalog(
    output_dir: Path,
    *,
    input_report_path: Path | None = None,
    workspace_path: Path | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    tool_name: str | None = None,
    tool_version: str | None = None,
    notes: str | None = None,
) -> Path:
    """Inventory one external IL2CPP tool output directory without interpreting its contents."""

    resolved_output_dir = output_dir.resolve()
    if not resolved_output_dir.is_dir():
        raise FileNotFoundError(f"IL2CPP external output directory does not exist: {resolved_output_dir}")
    if (input_report_path is None) == (workspace_path is None):
        raise ValueError("Provide exactly one of input_report_path or workspace_path.")

    source_snapshot_path: str | None = None
    linked_input_report: str | None = None
    linked_workspace: str | None = None
    if input_report_path is not None:
        resolved_input_report = input_report_path.resolve()
        if not resolved_input_report.is_dir():
            raise FileNotFoundError(f"IL2CPP input-report directory does not exist: {resolved_input_report}")
        input_report_manifest_path = resolved_input_report / "manifest.json"
        if not input_report_manifest_path.is_file():
            raise FileNotFoundError(
                f"IL2CPP input-report is missing required manifest: {input_report_manifest_path}"
            )
        input_report_manifest = _load_manifest(input_report_manifest_path, "IL2CPP input-report")
        source_snapshot_path = _string_or_none(input_report_manifest.get("source_snapshot_path"))
        linked_input_report = str(resolved_input_report)
        linked_workspace = _string_or_none(input_report_manifest.get("workspace_path"))
    else:
        assert workspace_path is not None
        resolved_workspace = workspace_path.resolve()
        if not resolved_workspace.is_dir():
            raise FileNotFoundError(f"IL2CPP workspace directory does not exist: {resolved_workspace}")
        workspace_manifest_path = resolved_workspace / "manifest.json"
        if not workspace_manifest_path.is_file():
            raise FileNotFoundError(
                f"IL2CPP workspace is missing required manifest: {workspace_manifest_path}"
            )
        workspace_manifest = _load_manifest(workspace_manifest_path, "IL2CPP workspace")
        source_snapshot_path = _string_or_none(workspace_manifest.get("snapshot_source_path"))
        linked_workspace = str(resolved_workspace)

    file_inventory = _inventory_output_dir(resolved_output_dir)
    catalog_id = make_run_id(f"il2cpp_output_catalog_{resolved_output_dir.name}")
    catalog_dir = output_root / "il2cpp_output_catalogs" / catalog_id
    catalog_dir.mkdir(parents=True, exist_ok=False)

    manifest = {
        "schema_version": "il2cpp-output-catalog-v1",
        "command_name": "il2cpp-output-catalog",
        "created_at_utc": utc_timestamp(),
        "output_dir_path": str(resolved_output_dir),
        "linked_input_report_path": linked_input_report,
        "linked_workspace_path": linked_workspace,
        "source_snapshot_path": source_snapshot_path,
        "tool_name": tool_name,
        "tool_version": tool_version,
        "notes": notes,
        "file_inventory": file_inventory,
        "note": (
            "Read-only catalog of externally generated IL2CPP reconstruction output. "
            "This command inventories files only and does not perform semantic validation."
        ),
    }
    write_json(catalog_dir / "manifest.json", manifest)

    summary_lines = [
        f"catalog_path: {catalog_dir.resolve()}",
        f"output_dir_path: {resolved_output_dir}",
        f"linked_input_report_path: {linked_input_report or 'none'}",
        f"linked_workspace_path: {linked_workspace or 'none'}",
        f"source_snapshot_path: {source_snapshot_path or 'unknown'}",
        f"tool_name: {tool_name or 'unknown'}",
        f"tool_version: {tool_version or 'unknown'}",
        f"file_count: {len(file_inventory)}",
    ]
    if notes:
        summary_lines.extend(["", "notes:", notes])
    summary_lines.extend(["", "cataloged_files:"])
    summary_lines.extend(
        f"- {item['relative_path']} size_bytes={item['size_bytes']} sha256={item['sha256']}"
        for item in file_inventory
    )
    summary_lines.extend(
        [
            "",
            "scope_note:",
            "Catalog only. This report does not validate the semantic correctness of external IL2CPP reconstruction output.",
        ]
    )
    (catalog_dir / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return catalog_dir


def _inventory_output_dir(output_dir: Path) -> list[dict[str, object]]:
    files: list[dict[str, object]] = []
    for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
        relative_path = path.relative_to(output_dir).as_posix()
        payload = path.read_bytes()
        files.append(
            {
                "relative_path": relative_path,
                "size_bytes": len(payload),
                "sha256": sha256_bytes(payload),
            }
        )
    files.sort(key=lambda item: str(item["relative_path"]))
    return files


def _load_manifest(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} manifest is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} manifest must be a JSON object: {path}")
    return payload


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None

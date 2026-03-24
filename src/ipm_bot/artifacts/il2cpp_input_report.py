"""Read-only validation and reporting for an existing IL2CPP workspace."""

from __future__ import annotations

import json
from pathlib import Path

from .shared import DEFAULT_OUTPUT_ROOT, make_run_id, sha256_bytes, utc_timestamp, write_json


def run_il2cpp_input_report(
    workspace_dir: Path,
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    notes: str | None = None,
) -> Path:
    """Validate one staged IL2CPP workspace and write a normalized handoff report."""

    resolved_workspace_dir = workspace_dir.resolve()
    if not resolved_workspace_dir.is_dir():
        raise FileNotFoundError(f"IL2CPP workspace directory does not exist: {resolved_workspace_dir}")

    required_paths = {
        "global_metadata": resolved_workspace_dir / "workspace" / "global-metadata.dat",
        "libil2cpp": resolved_workspace_dir / "workspace" / "libil2cpp.so",
        "manifest": resolved_workspace_dir / "manifest.json",
        "summary": resolved_workspace_dir / "summary.txt",
    }
    for label, path in required_paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"IL2CPP workspace is missing required file ({label}): {path}")

    workspace_manifest = _load_workspace_manifest(required_paths["manifest"])
    report_id = make_run_id(f"il2cpp_input_report_{resolved_workspace_dir.name}")
    report_dir = output_root / "il2cpp_input_reports" / report_id
    report_dir.mkdir(parents=True, exist_ok=False)

    metadata_payload = required_paths["global_metadata"].read_bytes()
    binary_payload = required_paths["libil2cpp"].read_bytes()
    architecture = workspace_manifest.get("architecture")
    source_snapshot_path = workspace_manifest.get("snapshot_source_path")

    staged_files = {
        "global_metadata": {
            "workspace_relative_path": "workspace/global-metadata.dat",
            "workspace_file_path": str(required_paths["global_metadata"].resolve()),
            "sha256": sha256_bytes(metadata_payload),
            "size_bytes": len(metadata_payload),
        },
        "libil2cpp": {
            "workspace_relative_path": "workspace/libil2cpp.so",
            "workspace_file_path": str(required_paths["libil2cpp"].resolve()),
            "sha256": sha256_bytes(binary_payload),
            "size_bytes": len(binary_payload),
        },
    }

    manifest = {
        "schema_version": "il2cpp-input-report-v1",
        "command_name": "il2cpp-input-report",
        "created_at_utc": utc_timestamp(),
        "workspace_path": str(resolved_workspace_dir),
        "workspace_manifest_path": str(required_paths["manifest"].resolve()),
        "workspace_summary_path": str(required_paths["summary"].resolve()),
        "architecture": architecture,
        "source_snapshot_path": source_snapshot_path,
        "staged_files": staged_files,
        "external_tool_notes": notes,
        "note": (
            "Read-only validation report for an IL2CPP staging workspace. "
            "This command does not run external reverse-engineering tooling and does not validate "
            "the semantic correctness of Cpp2IL or Il2CppDumper output."
        ),
    }
    write_json(report_dir / "manifest.json", manifest)

    summary_lines = [
        f"report_path: {report_dir.resolve()}",
        f"workspace_path: {resolved_workspace_dir}",
        f"source_snapshot_path: {source_snapshot_path or 'unknown'}",
        f"architecture: {architecture or 'unknown'}",
        "",
        "validated_files:",
        f"- workspace/global-metadata.dat sha256={staged_files['global_metadata']['sha256']} size_bytes={staged_files['global_metadata']['size_bytes']}",
        f"- workspace/libil2cpp.so sha256={staged_files['libil2cpp']['sha256']} size_bytes={staged_files['libil2cpp']['size_bytes']}",
    ]
    if notes:
        summary_lines.extend(["", "external_tool_notes:", notes])
    summary_lines.extend(
        [
            "",
            "scope_note:",
            "This report validates staged inputs only. It does not execute or validate external IL2CPP reconstruction output.",
        ]
    )
    (report_dir / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return report_dir


def _load_workspace_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"IL2CPP workspace manifest is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"IL2CPP workspace manifest must be a JSON object: {path}")
    return payload

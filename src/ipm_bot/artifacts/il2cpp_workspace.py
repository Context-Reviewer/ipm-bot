"""Read-only IL2CPP workspace staging from an existing artifact snapshot."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZipFile

from .shared import DEFAULT_OUTPUT_ROOT, make_run_id, sanitize_name, sha256_bytes, utc_timestamp, write_json


GLOBAL_METADATA_MEMBER_PATH = "assets/bin/Data/Managed/Metadata/global-metadata.dat"
LIBIL2CPP_MEMBER_PATH = "lib/arm64-v8a/libil2cpp.so"
ARCHITECTURE = "arm64-v8a"


def run_il2cpp_workspace(snapshot_dir: Path, *, output_root: Path = DEFAULT_OUTPUT_ROOT) -> Path:
    """Stage IL2CPP reconstruction inputs from one existing snapshot."""

    resolved_snapshot_dir = snapshot_dir.resolve()
    if not resolved_snapshot_dir.is_dir():
        raise FileNotFoundError(f"Snapshot directory does not exist: {resolved_snapshot_dir}")

    base_apk_path = resolved_snapshot_dir / "context" / "installed_package" / "base.apk"
    split_apk_path = (
        resolved_snapshot_dir / "context" / "installed_package" / "split_config.arm64_v8a.apk"
    )
    if not base_apk_path.is_file():
        raise FileNotFoundError(
            f"Snapshot is missing required APK: {base_apk_path}"
        )
    if not split_apk_path.is_file():
        raise FileNotFoundError(
            f"Snapshot is missing required APK: {split_apk_path}"
        )

    package_name = _load_package_name(resolved_snapshot_dir)
    workspace_id = make_run_id(
        f"il2cpp_workspace_{sanitize_name(resolved_snapshot_dir.name)}"
    )
    workspace_root = output_root / "il2cpp_workspaces" / workspace_id
    workspace_dir = workspace_root / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=False)

    metadata_payload, metadata_receipt = _resolve_member_payload(
        snapshot_dir=resolved_snapshot_dir,
        apk_path=base_apk_path,
        member_path=GLOBAL_METADATA_MEMBER_PATH,
    )
    binary_payload, binary_receipt = _resolve_member_payload(
        snapshot_dir=resolved_snapshot_dir,
        apk_path=split_apk_path,
        member_path=LIBIL2CPP_MEMBER_PATH,
    )

    metadata_workspace_path = workspace_dir / "global-metadata.dat"
    binary_workspace_path = workspace_dir / "libil2cpp.so"
    metadata_workspace_path.write_bytes(metadata_payload)
    binary_workspace_path.write_bytes(binary_payload)

    metadata_info = {
        "workspace_relative_path": "workspace/global-metadata.dat",
        "source_apk_path": str(base_apk_path.resolve()),
        "source_member_path": GLOBAL_METADATA_MEMBER_PATH,
        "source_receipt": metadata_receipt,
        "sha256": sha256_bytes(metadata_payload),
        "size_bytes": len(metadata_payload),
    }
    binary_info = {
        "workspace_relative_path": "workspace/libil2cpp.so",
        "source_apk_path": str(split_apk_path.resolve()),
        "source_member_path": LIBIL2CPP_MEMBER_PATH,
        "source_receipt": binary_receipt,
        "sha256": sha256_bytes(binary_payload),
        "size_bytes": len(binary_payload),
    }

    manifest = {
        "schema_version": "il2cpp-workspace-v1",
        "command_name": "il2cpp-workspace",
        "created_at_utc": utc_timestamp(),
        "package_name": package_name,
        "snapshot_source_path": str(resolved_snapshot_dir),
        "source_apk_paths": {
            "base_apk_path": str(base_apk_path.resolve()),
            "split_config_arm64_v8a_apk_path": str(split_apk_path.resolve()),
        },
        "architecture": ARCHITECTURE,
        "note": (
            "Read-only staging workspace for external IL2CPP tooling. "
            "This command does not run Cpp2IL, Il2CppDumper, or decompilation."
        ),
        "staged_files": {
            "global_metadata": metadata_info,
            "libil2cpp": binary_info,
        },
    }
    write_json(workspace_root / "manifest.json", manifest)

    summary_lines = [
        f"workspace_path: {workspace_root.resolve()}",
        f"snapshot_source_path: {resolved_snapshot_dir}",
        f"package_name: {package_name or 'unknown'}",
        f"architecture: {ARCHITECTURE}",
        "",
        "metadata_source:",
        f"- apk_path: {metadata_info['source_apk_path']}",
        f"- member_path: {metadata_info['source_member_path']}",
        f"- receipt: {_render_receipt(metadata_receipt)}",
        f"- sha256: {metadata_info['sha256']}",
        f"- size_bytes: {metadata_info['size_bytes']}",
        "",
        "binary_source:",
        f"- apk_path: {binary_info['source_apk_path']}",
        f"- member_path: {binary_info['source_member_path']}",
        f"- receipt: {_render_receipt(binary_receipt)}",
        f"- sha256: {binary_info['sha256']}",
        f"- size_bytes: {binary_info['size_bytes']}",
    ]
    (workspace_root / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return workspace_root


def _load_package_name(snapshot_dir: Path) -> str | None:
    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    package_name = payload.get("package_name")
    return str(package_name) if isinstance(package_name, str) and package_name.strip() else None


def _resolve_member_payload(snapshot_dir: Path, apk_path: Path, member_path: str) -> tuple[bytes, dict[str, Any]]:
    reused_member_path = _find_reused_member(snapshot_dir, apk_path, member_path)
    if reused_member_path is not None:
        payload = reused_member_path.read_bytes()
        return payload, {
            "mode": "reused_apk_report_extract",
            "source_path": str(reused_member_path.resolve()),
        }

    with ZipFile(apk_path) as archive:
        try:
            payload = archive.read(member_path)
        except KeyError as exc:
            raise FileNotFoundError(
                f"Required APK member not found: {member_path} in {apk_path.resolve()}"
            ) from exc
    return payload, {
        "mode": "apk_zip_read",
        "source_path": str(apk_path.resolve()),
    }


def _find_reused_member(snapshot_dir: Path, apk_path: Path, member_path: str) -> Path | None:
    candidate_roots: list[Path] = []
    if snapshot_dir.parent.name == "snapshots":
        candidate_roots.append(snapshot_dir.parent.parent / "apk_reports")
    candidate_roots.append(DEFAULT_OUTPUT_ROOT / "apk_reports")

    for report_root in candidate_roots:
        if not report_root.is_dir():
            continue
        for manifest_path in sorted(report_root.glob("*/manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            resolved_apk_path = manifest.get("resolved_apk_path")
            if resolved_apk_path != str(apk_path.resolve()):
                continue
            candidate = manifest_path.parent / "extracted_members" / Path(
                *PurePosixPath(member_path).parts
            )
            if candidate.is_file():
                return candidate
    return None


def _render_receipt(receipt: dict[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in receipt.items())

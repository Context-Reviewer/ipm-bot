"""Metadata-only filename/path hinting on an IL2CPP output catalog."""

from __future__ import annotations

import json
from pathlib import Path

from .shared import DEFAULT_OUTPUT_ROOT, make_run_id, utc_timestamp, write_json


def run_il2cpp_name_hint_report(
    catalog_dir: Path,
    *,
    terms: list[str],
    case_sensitive: bool = False,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    notes: str | None = None,
) -> Path:
    """Filter one IL2CPP output catalog by filename/path search terms."""

    resolved_catalog_dir = catalog_dir.resolve()
    if not resolved_catalog_dir.is_dir():
        raise FileNotFoundError(f"IL2CPP output catalog directory does not exist: {resolved_catalog_dir}")
    if not terms:
        raise ValueError("At least one search term is required.")
    normalized_terms = [term for term in terms if term.strip()]
    if not normalized_terms:
        raise ValueError("At least one non-empty search term is required.")

    catalog_manifest_path = resolved_catalog_dir / "manifest.json"
    if not catalog_manifest_path.is_file():
        raise FileNotFoundError(
            f"IL2CPP output catalog is missing required manifest: {catalog_manifest_path}"
        )
    catalog_manifest = _load_catalog_manifest(catalog_manifest_path)
    file_inventory = _extract_file_inventory(catalog_manifest, catalog_manifest_path)

    matches = _match_inventory(
        file_inventory=file_inventory,
        terms=normalized_terms,
        case_sensitive=case_sensitive,
    )

    report_id = make_run_id(f"il2cpp_name_hint_report_{resolved_catalog_dir.name}")
    report_dir = output_root / "il2cpp_name_hint_reports" / report_id
    report_dir.mkdir(parents=True, exist_ok=False)

    manifest = {
        "schema_version": "il2cpp-name-hint-report-v1",
        "command_name": "il2cpp-name-hint-report",
        "created_at_utc": utc_timestamp(),
        "source_catalog_path": str(resolved_catalog_dir),
        "source_snapshot_path": _string_or_none(catalog_manifest.get("source_snapshot_path")),
        "terms": normalized_terms,
        "case_sensitive": case_sensitive,
        "matching_entries": matches,
        "notes": notes,
        "note": (
            "Filename/path metadata filtering only. "
            "This command does not open cataloged files and does not perform semantic interpretation."
        ),
    }
    write_json(report_dir / "manifest.json", manifest)

    summary_lines = [
        f"report_path: {report_dir.resolve()}",
        f"source_catalog_path: {resolved_catalog_dir}",
        f"source_snapshot_path: {manifest['source_snapshot_path'] or 'unknown'}",
        f"case_sensitive: {str(case_sensitive).lower()}",
        f"term_count: {len(normalized_terms)}",
        f"match_count: {len(matches)}",
        "",
        "terms:",
    ]
    summary_lines.extend(f"- {term}" for term in normalized_terms)
    if notes:
        summary_lines.extend(["", "notes:", notes])
    summary_lines.extend(["", "matching_entries:"])
    if matches:
        summary_lines.extend(
            f"- {item['relative_path']} matched_terms={','.join(item['matched_terms'])} "
            f"size_bytes={item['size_bytes']} sha256={item['sha256']}"
            for item in matches
        )
    else:
        summary_lines.append("(no path matches)")
    summary_lines.extend(
        [
            "",
            "scope_note:",
            "This report narrows large external output trees using filename/path metadata only.",
        ]
    )
    (report_dir / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return report_dir


def _load_catalog_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"IL2CPP output catalog manifest is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"IL2CPP output catalog manifest must be a JSON object: {path}")
    return payload


def _extract_file_inventory(
    manifest: dict[str, object],
    manifest_path: Path,
) -> list[dict[str, object]]:
    file_inventory = manifest.get("file_inventory")
    if not isinstance(file_inventory, list):
        raise ValueError(
            f"IL2CPP output catalog manifest is missing a valid file_inventory list: {manifest_path}"
        )
    validated: list[dict[str, object]] = []
    for item in file_inventory:
        if not isinstance(item, dict):
            raise ValueError(
                f"IL2CPP output catalog manifest contains a non-object file_inventory entry: {manifest_path}"
            )
        relative_path = item.get("relative_path")
        size_bytes = item.get("size_bytes")
        sha256 = item.get("sha256")
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError(
                f"IL2CPP output catalog manifest contains an invalid relative_path entry: {manifest_path}"
            )
        if not isinstance(size_bytes, int):
            raise ValueError(
                f"IL2CPP output catalog manifest contains an invalid size_bytes entry: {manifest_path}"
            )
        if not isinstance(sha256, str) or not sha256.strip():
            raise ValueError(
                f"IL2CPP output catalog manifest contains an invalid sha256 entry: {manifest_path}"
            )
        validated.append(
            {
                "relative_path": relative_path,
                "size_bytes": size_bytes,
                "sha256": sha256,
            }
        )
    return validated


def _match_inventory(
    *,
    file_inventory: list[dict[str, object]],
    terms: list[str],
    case_sensitive: bool,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    normalized_terms = terms if case_sensitive else [term.lower() for term in terms]

    for item in file_inventory:
        relative_path = str(item["relative_path"])
        haystack = relative_path if case_sensitive else relative_path.lower()
        matched_terms = [
            terms[index]
            for index, needle in enumerate(normalized_terms)
            if needle in haystack
        ]
        if not matched_terms:
            continue
        results.append(
            {
                "relative_path": relative_path,
                "matched_terms": matched_terms,
                "size_bytes": int(item["size_bytes"]),
                "sha256": str(item["sha256"]),
            }
        )
    results.sort(key=lambda item: str(item["relative_path"]))
    return results


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None

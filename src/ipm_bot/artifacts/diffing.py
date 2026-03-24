"""Snapshot diffing and triage for artifact discovery runs."""

from __future__ import annotations

from dataclasses import asdict
import difflib
import json
from pathlib import Path
import platform

from .shared import (
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_TEXT_DIFF_MAX_BYTES,
    DiffRecord,
    decode_lossy,
    looks_binary,
    make_run_id,
    write_csv,
    write_json,
)


def run_diff(
    before_snapshot_dir: Path,
    after_snapshot_dir: Path,
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    text_diff_max_bytes: int = DEFAULT_TEXT_DIFF_MAX_BYTES,
) -> Path:
    """Compare two snapshot directories and write a ranked diff report."""

    before_inventory = _load_inventory(before_snapshot_dir)
    after_inventory = _load_inventory(after_snapshot_dir)
    before_by_key = {item["artifact_key"]: item for item in before_inventory}
    after_by_key = {item["artifact_key"]: item for item in after_inventory}
    all_keys = sorted(set(before_by_key) | set(after_by_key))

    diff_id = make_run_id("artifact_diff")
    diff_dir = output_root / "diffs" / diff_id
    diff_dir.mkdir(parents=True, exist_ok=False)
    text_diff_dir = diff_dir / "text_diffs"
    text_diff_dir.mkdir(parents=True, exist_ok=True)

    diff_records: list[DiffRecord] = []
    for artifact_key in all_keys:
        before = before_by_key.get(artifact_key)
        after = after_by_key.get(artifact_key)
        if before is None:
            diff_records.append(_new_record(after))
            continue
        if after is None:
            diff_records.append(_deleted_record(before))
            continue
        changed, reasons = _compare(before, after)
        if not changed:
            continue
        text_diff_relative_path = _maybe_write_text_diff(
            before_snapshot_dir=before_snapshot_dir,
            after_snapshot_dir=after_snapshot_dir,
            before=before,
            after=after,
            text_diff_dir=text_diff_dir,
            text_diff_max_bytes=text_diff_max_bytes,
        )
        diff_records.append(
            DiffRecord(
                artifact_key=artifact_key,
                change_type="modified",
                source_kind=str(after["source_kind"]),
                source_path=str(after["source_path"]),
                relative_path=str(after["relative_path"]),
                before_size_bytes=_int_or_none(before.get("size_bytes")),
                after_size_bytes=_int_or_none(after.get("size_bytes")),
                before_mtime_utc=_str_or_none(before.get("mtime_utc")),
                after_mtime_utc=_str_or_none(after.get("mtime_utc")),
                before_sha256=_str_or_none(before.get("sha256")),
                after_sha256=_str_or_none(after.get("sha256")),
                before_file_class=_str_or_none(before.get("file_class")),
                after_file_class=_str_or_none(after.get("file_class")),
                before_copied_relative_path=_str_or_none(before.get("copied_relative_path")),
                after_copied_relative_path=_str_or_none(after.get("copied_relative_path")),
                priority=str(after.get("priority", "low")),
                triage_score=_score_change(before, after, "modified", reasons),
                reasons=reasons,
                text_diff_relative_path=text_diff_relative_path,
            )
        )

    diff_records.sort(key=lambda item: (-item.triage_score, item.source_kind, item.source_path))
    csv_rows = []
    for record in diff_records:
        row = asdict(record)
        row["reasons"] = ";".join(record.reasons)
        csv_rows.append(row)
    write_json(diff_dir / "changes.json", [asdict(item) for item in diff_records])
    write_csv(
        diff_dir / "changes.csv",
        csv_rows,
        [
            "artifact_key",
            "change_type",
            "source_kind",
            "source_path",
            "relative_path",
            "before_size_bytes",
            "after_size_bytes",
            "before_mtime_utc",
            "after_mtime_utc",
            "before_sha256",
            "after_sha256",
            "before_file_class",
            "after_file_class",
            "before_copied_relative_path",
            "after_copied_relative_path",
            "priority",
            "triage_score",
            "reasons",
            "text_diff_relative_path",
        ],
    )
    summary = {
        "schema_version": "artifact-diff-v1",
        "before_snapshot_dir": str(before_snapshot_dir),
        "after_snapshot_dir": str(after_snapshot_dir),
        "output_dir": str(diff_dir),
        "host_platform": platform.platform(),
        "new_file_count": sum(1 for item in diff_records if item.change_type == "new"),
        "deleted_file_count": sum(1 for item in diff_records if item.change_type == "deleted"),
        "modified_file_count": sum(1 for item in diff_records if item.change_type == "modified"),
        "high_priority_change_count": sum(1 for item in diff_records if item.priority == "high"),
        "top_changes": [asdict(item) for item in diff_records[:20]],
    }
    write_json(diff_dir / "summary.json", summary)
    _write_summary_text(diff_dir, summary, diff_records)
    return diff_dir


def _load_inventory(snapshot_dir: Path) -> list[dict[str, object]]:
    inventory_path = snapshot_dir / "inventory.json"
    if not inventory_path.is_file():
        raise FileNotFoundError(f"Snapshot inventory is missing: {inventory_path}")
    return json.loads(inventory_path.read_text(encoding="utf-8"))


def _new_record(after: dict[str, object] | None) -> DiffRecord:
    assert after is not None
    reasons = ["new_file"]
    return DiffRecord(
        artifact_key=str(after["artifact_key"]),
        change_type="new",
        source_kind=str(after["source_kind"]),
        source_path=str(after["source_path"]),
        relative_path=str(after["relative_path"]),
        before_size_bytes=None,
        after_size_bytes=_int_or_none(after.get("size_bytes")),
        before_mtime_utc=None,
        after_mtime_utc=_str_or_none(after.get("mtime_utc")),
        before_sha256=None,
        after_sha256=_str_or_none(after.get("sha256")),
        before_file_class=None,
        after_file_class=_str_or_none(after.get("file_class")),
        before_copied_relative_path=None,
        after_copied_relative_path=_str_or_none(after.get("copied_relative_path")),
        priority=str(after.get("priority", "low")),
        triage_score=_score_change(None, after, "new", reasons),
        reasons=reasons,
    )


def _deleted_record(before: dict[str, object] | None) -> DiffRecord:
    assert before is not None
    reasons = ["deleted_file"]
    return DiffRecord(
        artifact_key=str(before["artifact_key"]),
        change_type="deleted",
        source_kind=str(before["source_kind"]),
        source_path=str(before["source_path"]),
        relative_path=str(before["relative_path"]),
        before_size_bytes=_int_or_none(before.get("size_bytes")),
        after_size_bytes=None,
        before_mtime_utc=_str_or_none(before.get("mtime_utc")),
        after_mtime_utc=None,
        before_sha256=_str_or_none(before.get("sha256")),
        after_sha256=None,
        before_file_class=_str_or_none(before.get("file_class")),
        after_file_class=None,
        before_copied_relative_path=_str_or_none(before.get("copied_relative_path")),
        after_copied_relative_path=None,
        priority=str(before.get("priority", "low")),
        triage_score=_score_change(before, None, "deleted", reasons),
        reasons=reasons,
    )


def _compare(before: dict[str, object], after: dict[str, object]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if before.get("size_bytes") != after.get("size_bytes"):
        reasons.append("size_changed")
    if before.get("mtime_utc") != after.get("mtime_utc"):
        reasons.append("mtime_changed")
    if before.get("sha256") and after.get("sha256") and before.get("sha256") != after.get("sha256"):
        reasons.append("hash_changed")
    if before.get("file_class") != after.get("file_class"):
        reasons.append("classification_changed")
    if before.get("text_like") != after.get("text_like"):
        reasons.append("text_binary_class_changed")
    return bool(reasons), reasons


def _maybe_write_text_diff(
    *,
    before_snapshot_dir: Path,
    after_snapshot_dir: Path,
    before: dict[str, object],
    after: dict[str, object],
    text_diff_dir: Path,
    text_diff_max_bytes: int,
) -> str | None:
    before_relative = _str_or_none(before.get("copied_relative_path"))
    after_relative = _str_or_none(after.get("copied_relative_path"))
    if before_relative is None or after_relative is None:
        return None
    before_path = before_snapshot_dir / before_relative
    after_path = after_snapshot_dir / after_relative
    if not before_path.is_file() or not after_path.is_file():
        return None
    if before_path.stat().st_size > text_diff_max_bytes or after_path.stat().st_size > text_diff_max_bytes:
        return None
    before_bytes = before_path.read_bytes()
    after_bytes = after_path.read_bytes()
    if looks_binary(before_bytes) or looks_binary(after_bytes):
        return None
    before_lines = decode_lossy(before_bytes).splitlines()
    after_lines = decode_lossy(after_bytes).splitlines()
    unified = list(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=str(before["source_path"]),
            tofile=str(after["source_path"]),
            lineterm="",
        )
    )
    if not unified:
        return None
    diff_name = f"{_safe_filename(str(after['source_kind']))}_{_safe_filename(str(after['relative_path']))}.diff"
    diff_path = text_diff_dir / diff_name
    diff_path.write_text("\n".join(unified) + "\n", encoding="utf-8")
    return str(diff_path.relative_to(text_diff_dir.parent))


def _score_change(
    before: dict[str, object] | None,
    after: dict[str, object] | None,
    change_type: str,
    reasons: list[str],
) -> int:
    anchor = after if after is not None else before
    assert anchor is not None
    score = int(anchor.get("priority_score") or 0)
    if change_type == "new":
        score += 25
    elif change_type == "deleted":
        score += 18
    else:
        score += 10
    for reason in reasons:
        if reason == "hash_changed":
            score += 30
        elif reason == "size_changed":
            score += 16
        elif reason == "mtime_changed":
            score += 6
        elif reason == "classification_changed":
            score += 12
        elif reason == "new_file":
            score += 10
        elif reason == "deleted_file":
            score += 8
    return score


def _write_summary_text(diff_dir: Path, summary: dict[str, object], diff_records: list[DiffRecord]) -> None:
    lines = [
        f"before_snapshot_dir: {summary['before_snapshot_dir']}",
        f"after_snapshot_dir: {summary['after_snapshot_dir']}",
        f"new_file_count: {summary['new_file_count']}",
        f"deleted_file_count: {summary['deleted_file_count']}",
        f"modified_file_count: {summary['modified_file_count']}",
        f"high_priority_change_count: {summary['high_priority_change_count']}",
        "",
        "most_interesting_changes:",
    ]
    for record in diff_records[:20]:
        lines.append(
            f"- score={record.triage_score} priority={record.priority} change={record.change_type} path={record.source_path} reasons={','.join(record.reasons)}"
        )
    (diff_dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _int_or_none(value: object) -> int | None:
    return int(value) if isinstance(value, int) else None


def _str_or_none(value: object) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value) or "artifact"

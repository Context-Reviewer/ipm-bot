"""Shared models and helpers for artifact discovery workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Any


DEFAULT_PACKAGE_NAME = "com.TironiumTech.IdlePlanetMiner"
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[3] / "data" / "artifacts"
DEFAULT_HASH_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_COPY_MAX_BYTES = 32 * 1024 * 1024
DEFAULT_TEXT_PREVIEW_MAX_BYTES = 64 * 1024
DEFAULT_TEXT_DIFF_MAX_BYTES = 128 * 1024


@dataclass(slots=True)
class CommandReceipt:
    receipt_id: str
    purpose: str
    command: list[str]
    started_at_utc: str
    finished_at_utc: str
    returncode: int | None
    spawn_error: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.spawn_error is None


@dataclass(slots=True)
class MethodStatus:
    method_id: str
    description: str
    status: str
    detail: str | None = None


@dataclass(slots=True)
class ContextFile:
    label: str
    relative_path: str
    source: str
    note: str | None = None


@dataclass(slots=True)
class ArtifactRecord:
    artifact_key: str
    collector_id: str
    source_kind: str
    source_root: str
    source_path: str
    relative_path: str
    entry_type: str
    accessible: bool
    extraction_method: str
    size_bytes: int | None = None
    mtime_epoch: int | None = None
    mtime_utc: str | None = None
    sha256: str | None = None
    extension: str | None = None
    file_class: str = "unknown"
    text_like: bool | None = None
    copy_status: str = "not_attempted"
    copied_relative_path: str | None = None
    quick_text_preview: str | None = None
    priority: str = "low"
    priority_score: int = 0
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SnapshotManifest:
    schema_version: str
    mode: str
    snapshot_id: str
    package_name: str
    created_at_utc: str
    output_dir: str
    host_platform: str
    working_directory: str
    adb_path: str
    adb_serial: str | None
    hash_max_bytes: int
    copy_max_bytes: int
    text_preview_max_bytes: int
    pull_apk: bool
    candidate_roots: list[dict[str, Any]]
    method_status: list[MethodStatus]
    limitations: list[str]
    command_receipt_count: int
    artifact_count: int
    file_count: int
    directory_count: int
    copied_file_count: int
    context_files: list[ContextFile]


@dataclass(slots=True)
class DiffRecord:
    artifact_key: str
    change_type: str
    source_kind: str
    source_path: str
    relative_path: str
    before_size_bytes: int | None
    after_size_bytes: int | None
    before_mtime_utc: str | None
    after_mtime_utc: str | None
    before_sha256: str | None
    after_sha256: str | None
    before_file_class: str | None
    after_file_class: str | None
    before_copied_relative_path: str | None
    after_copied_relative_path: str | None
    priority: str
    triage_score: int
    reasons: list[str]
    text_diff_relative_path: str | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_timestamp() -> str:
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def make_run_id(prefix: str, created_at: datetime | None = None) -> str:
    created = utc_now() if created_at is None else created_at
    return f"{created.strftime('%Y-%m-%dT%H-%M-%S-%fZ')}_{prefix}"


def sanitize_name(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return sanitized.strip("._") or "artifact"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def to_iso_utc(epoch_seconds: int | None) -> str | None:
    if epoch_seconds is None:
        return None
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def decode_lossy(payload: bytes) -> str:
    return payload.decode("utf-8", errors="replace")


def looks_binary(payload: bytes) -> bool:
    if not payload:
        return False
    sample = payload[:4096]
    if b"\x00" in sample:
        return True
    text_bytes = sum(1 for byte in sample if byte in b"\t\n\r\f\b" or 32 <= byte <= 126)
    return text_bytes / max(len(sample), 1) < 0.85


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=False))
            handle.write("\n")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def dataclass_list_payload(items: list[Any]) -> list[dict[str, Any]]:
    return [asdict(item) for item in items]

"""Safe, package-focused artifact census and snapshot discovery."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import platform
import subprocess
import zipfile

from .shared import (
    ArtifactRecord,
    CommandReceipt,
    ContextFile,
    DEFAULT_COPY_MAX_BYTES,
    DEFAULT_HASH_MAX_BYTES,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_PACKAGE_NAME,
    DEFAULT_TEXT_PREVIEW_MAX_BYTES,
    MethodStatus,
    SnapshotManifest,
    decode_lossy,
    looks_binary,
    make_run_id,
    sanitize_name,
    sha256_bytes,
    to_iso_utc,
    utc_now,
    utc_timestamp,
    write_csv,
    write_json,
    write_jsonl,
)


PRIVATE_DATA_ROOT = "/data/data/{package_name}"
PRIVATE_USER_ZERO_ROOT = "/data/user/0/{package_name}"
EXTERNAL_DATA_ROOT = "/sdcard/Android/data/{package_name}"
STORAGE_EMULATED_ROOT = "/storage/emulated/0/Android/data/{package_name}"


@dataclass(frozen=True, slots=True)
class DiscoveryOptions:
    mode: str
    package_name: str = DEFAULT_PACKAGE_NAME
    output_root: Path = DEFAULT_OUTPUT_ROOT
    adb_path: str = "adb"
    adb_serial: str | None = None
    hash_max_bytes: int = DEFAULT_HASH_MAX_BYTES
    copy_max_bytes: int = DEFAULT_COPY_MAX_BYTES
    text_preview_max_bytes: int = DEFAULT_TEXT_PREVIEW_MAX_BYTES
    pull_apk: bool = False

    def __post_init__(self) -> None:
        if self.mode not in {"census", "snapshot"}:
            raise ValueError(f"Unsupported discovery mode: {self.mode}")
        if not self.package_name.strip():
            raise ValueError("package_name must not be empty.")
        if not self.adb_path.strip():
            raise ValueError("adb_path must not be empty.")
        if self.hash_max_bytes <= 0:
            raise ValueError("hash_max_bytes must be greater than zero.")
        if self.copy_max_bytes <= 0:
            raise ValueError("copy_max_bytes must be greater than zero.")
        if self.text_preview_max_bytes <= 0:
            raise ValueError("text_preview_max_bytes must be greater than zero.")


@dataclass(frozen=True, slots=True)
class CandidateRoot:
    collector_id: str
    source_kind: str
    source_root: str
    relative_mode: str
    enumeration_method: str
    description: str


@dataclass(slots=True)
class CommandResult:
    receipt: CommandReceipt
    stdout: bytes
    stderr: bytes

    @property
    def ok(self) -> bool:
        return self.receipt.ok


class RecordedCommandRunner:
    """Subprocess runner that persists stdout/stderr receipts for later audit."""

    def __init__(self, receipts_dir: Path) -> None:
        self._receipts_dir = receipts_dir
        self._receipts_dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0

    def run(self, command: list[str], *, purpose: str) -> CommandResult:
        self._counter += 1
        receipt_id = f"{self._counter:04d}"
        started_at = utc_timestamp()
        stdout = b""
        stderr = b""
        returncode: int | None = None
        spawn_error: str | None = None
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            returncode = completed.returncode
        except OSError as exc:
            spawn_error = str(exc)
            stderr = str(exc).encode("utf-8", errors="replace")
        finished_at = utc_timestamp()
        stdout_path = self._write_stream(receipt_id, "stdout", stdout)
        stderr_path = self._write_stream(receipt_id, "stderr", stderr)
        receipt = CommandReceipt(
            receipt_id=receipt_id,
            purpose=purpose,
            command=list(command),
            started_at_utc=started_at,
            finished_at_utc=finished_at,
            returncode=returncode,
            spawn_error=spawn_error,
            stdout_path=str(stdout_path.relative_to(self._receipts_dir.parent))
            if stdout_path is not None
            else None,
            stderr_path=str(stderr_path.relative_to(self._receipts_dir.parent))
            if stderr_path is not None
            else None,
        )
        write_json(self._receipts_dir / f"{receipt_id}.json", asdict(receipt))
        return CommandResult(receipt=receipt, stdout=stdout, stderr=stderr)

    def _write_stream(self, receipt_id: str, label: str, payload: bytes) -> Path | None:
        if not payload:
            return None
        suffix = ".txt"
        if looks_binary(payload):
            suffix = ".bin"
        path = self._receipts_dir / f"{receipt_id}.{label}{suffix}"
        path.write_bytes(payload)
        return path


class DiscoverySession:
    def __init__(self, options: DiscoveryOptions) -> None:
        self._options = options
        self._snapshot_id = make_run_id(f"{options.mode}_{sanitize_name(options.package_name)}")
        output_subdir = "census" if options.mode == "census" else "snapshots"
        self._snapshot_dir = options.output_root / output_subdir / self._snapshot_id
        self._receipts_dir = self._snapshot_dir / "receipts" / "commands"
        self._context_dir = self._snapshot_dir / "context"
        self._extracted_dir = self._snapshot_dir / "extracted"
        self._reports_dir = self._snapshot_dir / "reports"
        self._runner: RecordedCommandRunner | None = None
        self._events: list[dict[str, object]] = []
        self._method_status: list[MethodStatus] = []
        self._limitations: list[str] = []
        self._artifacts: list[ArtifactRecord] = []
        self._context_files: list[ContextFile] = []
        self._created_at = utc_now()
        self._run_as_probe_result: CommandResult | None = None

    def run(self) -> Path:
        self._snapshot_dir.mkdir(parents=True, exist_ok=False)
        self._context_dir.mkdir(parents=True, exist_ok=True)
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        self._runner = RecordedCommandRunner(self._receipts_dir)
        candidate_roots = self._candidate_roots()
        self._log_event("session_started", package_name=self._options.package_name)
        self._collect_host_metadata()
        adb_ready = self._collect_adb_environment()
        if adb_ready:
            self._collect_android_artifacts(candidate_roots)
            if self._options.pull_apk:
                self._pull_and_inventory_apk()
        else:
            self._limitations.append(
                "ADB preflight failed; Android package collectors were skipped. Host-side BlueStacks metadata was still inventoried."
            )
        self._write_outputs(candidate_roots)
        self._log_event("session_completed", artifact_count=len(self._artifacts))
        return self._snapshot_dir

    def _candidate_roots(self) -> list[CandidateRoot]:
        package_name = self._options.package_name
        return [
            CandidateRoot(
                collector_id="private_run_as_data",
                source_kind="adb_private",
                source_root=PRIVATE_DATA_ROOT.format(package_name=package_name),
                relative_mode="run_as_relative",
                enumeration_method="adb shell run-as",
                description="Package-private app sandbox via run-as, if the app is debuggable.",
            ),
            CandidateRoot(
                collector_id="private_run_as_user0",
                source_kind="adb_private",
                source_root=PRIVATE_USER_ZERO_ROOT.format(package_name=package_name),
                relative_mode="run_as_relative",
                enumeration_method="adb shell run-as",
                description="Package-private user 0 alias via run-as, if supported.",
            ),
            CandidateRoot(
                collector_id="external_sdcard",
                source_kind="adb_external",
                source_root=EXTERNAL_DATA_ROOT.format(package_name=package_name),
                relative_mode="absolute",
                enumeration_method="adb shell find",
                description="External Android/data tree exposed through emulator storage.",
            ),
            CandidateRoot(
                collector_id="external_storage_emulated",
                source_kind="adb_external",
                source_root=STORAGE_EMULATED_ROOT.format(package_name=package_name),
                relative_mode="absolute",
                enumeration_method="adb shell find",
                description="External storage alias for the same package tree.",
            ),
        ]

    def _collect_host_metadata(self) -> None:
        host_files = [
            (
                "bluestacks_appcache",
                Path(r"C:\ProgramData\BlueStacks_nxt\Engine\Pie64\AppCache\AppCache.json"),
                "BlueStacks package metadata cache.",
            ),
            (
                "bluestacks_player_log",
                Path(r"C:\ProgramData\BlueStacks_nxt\Logs\Player.log"),
                "BlueStacks Player.log emulator telemetry.",
            ),
            (
                "bluestacks_conf",
                Path(r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf"),
                "BlueStacks instance configuration.",
            ),
        ]
        for collector_id, path, note in host_files:
            if not path.exists():
                self._method_status.append(
                    MethodStatus(
                        method_id=collector_id,
                        description=note,
                        status="not_found",
                        detail=str(path),
                    )
                )
                continue
            self._method_status.append(
                MethodStatus(
                    method_id=collector_id,
                    description=note,
                    status="ok",
                    detail=str(path),
                )
            )
            self._ingest_local_file(
                collector_id=collector_id,
                source_kind="windows_host",
                source_root=str(path.parent),
                source_path=str(path),
                relative_path=path.name,
                extraction_method="host_read",
            )

    def _collect_adb_environment(self) -> bool:
        version_result = self._run_adb(["version"], purpose="adb_version")
        self._record_method_result("adb_version", version_result, "ADB version preflight.")
        devices_result = self._run_adb(["devices", "-l"], purpose="adb_devices")
        self._record_method_result("adb_devices", devices_result, "ADB device enumeration.")
        if not version_result.ok or not devices_result.ok:
            return False

        get_state_result = self._run_adb(["get-state"], purpose="adb_get_state")
        self._record_method_result("adb_get_state", get_state_result, "ADB transport state.")
        if not get_state_result.ok:
            return False

        package_path_result = self._run_adb_shell(
            ["pm", "path", self._options.package_name],
            purpose="pm_path_package",
        )
        self._record_method_result(
            "pm_path_package",
            package_path_result,
            "Installed package path discovery.",
        )
        dumpsys_result = self._run_adb_shell(
            ["dumpsys", "package", self._options.package_name],
            purpose="dumpsys_package",
        )
        self._record_method_result(
            "dumpsys_package",
            dumpsys_result,
            "Installed package dumpsys metadata.",
        )
        if dumpsys_result.ok:
            self._persist_context_payload(
                label="dumpsys_package",
                relative_path="context/dumpsys_package.txt",
                payload=dumpsys_result.stdout,
                note="Package metadata snapshot from dumpsys package.",
                source="adb shell dumpsys package",
            )
        return package_path_result.ok

    def _collect_android_artifacts(self, candidate_roots: list[CandidateRoot]) -> None:
        for candidate in candidate_roots:
            self._artifacts.extend(self._enumerate_candidate(candidate))

    def _enumerate_candidate(self, candidate: CandidateRoot) -> list[ArtifactRecord]:
        if candidate.relative_mode == "run_as_relative":
            return self._enumerate_run_as_root(candidate)
        return self._enumerate_absolute_root(candidate)

    def _enumerate_run_as_root(self, candidate: CandidateRoot) -> list[ArtifactRecord]:
        probe = self._probe_run_as_access()
        if not probe.ok:
            self._method_status.append(
                MethodStatus(
                    method_id=candidate.collector_id,
                    description=candidate.description,
                    status="blocked",
                    detail=self._summarize_failure(probe),
                )
            )
            self._limitations.append(
                f"{candidate.collector_id} blocked or unsupported: {self._summarize_failure(probe)}"
            )
            return []
        shell_script = (
            "find . -xdev -print 2>/dev/null | while IFS= read -r p; do "
            'clean="${p#./}"; '
            'if [ "$clean" = "" ]; then clean="."; fi; '
            'if [ -d "$p" ]; then kind="dir"; size="0"; '
            "else kind=\"file\"; size=$(wc -c < \"$p\" 2>/dev/null | tr -d ' '); fi; "
            "mtime=$(stat -c %Y \"$p\" 2>/dev/null || echo ''); "
            "printf '%s\\t%s\\t%s\\t%s\\n' \"$kind\" \"$size\" \"$mtime\" \"$clean\"; "
            "done"
        )
        assert self._runner is not None
        result = self._runner.run(
            self._adb_command(
                "shell",
                "run-as",
                self._options.package_name,
                "sh",
                "-c",
                shell_script,
            ),
            purpose=f"enumerate_{candidate.collector_id}",
        )
        self._record_method_result(candidate.collector_id, result, candidate.description)
        if not result.ok:
            self._limitations.append(
                f"{candidate.collector_id} blocked or unsupported: {self._summarize_failure(result)}"
            )
            return []
        if not decode_lossy(result.stdout).strip():
            self._method_status[-1].status = "blocked"
            self._method_status[-1].detail = "run-as enumeration returned no inventory output"
            self._limitations.append(
                f"{candidate.collector_id} returned no inventory output even though run-as preflight succeeded."
            )
            return []
        return self._parse_inventory_output(candidate=candidate, payload=decode_lossy(result.stdout))

    def _enumerate_absolute_root(self, candidate: CandidateRoot) -> list[ArtifactRecord]:
        assert self._runner is not None
        probe = self._runner.run(
            self._adb_command("shell", "ls", candidate.source_root),
            purpose=f"probe_{candidate.collector_id}",
        )
        if probe.receipt.returncode != 0:
            detail = self._summarize_failure(probe)
            status = "not_found" if "No such file or directory" in detail else "blocked"
            self._method_status.append(
                MethodStatus(
                    method_id=candidate.collector_id,
                    description=candidate.description,
                    status=status,
                    detail=detail,
                )
            )
            if status == "blocked":
                self._limitations.append(
                    f"{candidate.collector_id} could not be enumerated: {detail}"
                )
            return []
        result = self._runner.run(
            self._adb_command("shell", "find", candidate.source_root, "-print"),
            purpose=f"enumerate_{candidate.collector_id}",
        )
        self._record_method_result(candidate.collector_id, result, candidate.description)
        if not result.ok:
            self._limitations.append(
                f"{candidate.collector_id} could not be enumerated: {self._summarize_failure(result)}"
            )
            return []
        records: list[ArtifactRecord] = []
        for raw_line in decode_lossy(result.stdout).splitlines():
            path = raw_line.strip()
            if not path:
                continue
            stat_result = self._runner.run(
                self._adb_command("shell", "stat", "-c", "%F,%s,%Y", path),
                purpose=f"stat_{candidate.collector_id}",
            )
            if not stat_result.ok:
                continue
            stat_parts = decode_lossy(stat_result.stdout).strip().split(",", 2)
            if len(stat_parts) != 3:
                continue
            file_type_text, size_text, mtime_text = stat_parts
            entry_type = "dir" if file_type_text == "directory" else "file"
            relative_path = "." if path == candidate.source_root else path.removeprefix(candidate.source_root).lstrip("/")
            size_bytes = int(size_text) if size_text.isdigit() else None
            if entry_type == "dir":
                size_bytes = 0
            mtime_epoch = int(mtime_text) if mtime_text.isdigit() else None
            record = ArtifactRecord(
                artifact_key=f"{candidate.source_kind}|{path}",
                collector_id=candidate.collector_id,
                source_kind=candidate.source_kind,
                source_root=candidate.source_root,
                source_path=path,
                relative_path=relative_path,
                entry_type=entry_type,
                accessible=True,
                extraction_method=candidate.enumeration_method,
                size_bytes=size_bytes,
                mtime_epoch=mtime_epoch,
                mtime_utc=to_iso_utc(mtime_epoch),
            )
            self._enrich_artifact_metadata(record)
            if record.entry_type == "file":
                self._maybe_capture_file(record)
            records.append(record)
        return records

    def _probe_run_as_access(self) -> CommandResult:
        if self._run_as_probe_result is not None:
            return self._run_as_probe_result
        assert self._runner is not None
        self._run_as_probe_result = self._runner.run(
            self._adb_command("shell", "run-as", self._options.package_name, "pwd"),
            purpose="probe_run_as",
        )
        return self._run_as_probe_result

    def _parse_inventory_output(
        self,
        *,
        candidate: CandidateRoot,
        payload: str,
    ) -> list[ArtifactRecord]:
        records: list[ArtifactRecord] = []
        for raw_line in payload.splitlines():
            if not raw_line.strip():
                continue
            parts = raw_line.split("\t", 3)
            if len(parts) != 4:
                continue
            entry_type, size_text, mtime_text, raw_path = parts
            source_path = raw_path
            relative_path = raw_path
            if candidate.relative_mode == "run_as_relative":
                if raw_path == ".":
                    source_path = candidate.source_root
                else:
                    source_path = f"{candidate.source_root}/{raw_path}".replace("\\", "/")
                relative_path = raw_path
            else:
                if raw_path == candidate.source_root:
                    relative_path = "."
                else:
                    relative_path = raw_path.removeprefix(candidate.source_root).lstrip("/")
            size_bytes = int(size_text) if size_text.isdigit() else None
            mtime_epoch = int(mtime_text) if mtime_text.isdigit() else None
            record = ArtifactRecord(
                artifact_key=f"{candidate.source_kind}|{source_path}",
                collector_id=candidate.collector_id,
                source_kind=candidate.source_kind,
                source_root=candidate.source_root,
                source_path=source_path,
                relative_path=relative_path,
                entry_type=entry_type,
                accessible=True,
                extraction_method=candidate.enumeration_method,
                size_bytes=size_bytes,
                mtime_epoch=mtime_epoch,
                mtime_utc=to_iso_utc(mtime_epoch),
            )
            self._enrich_artifact_metadata(record)
            if record.entry_type == "file":
                self._maybe_capture_file(record)
            records.append(record)
        return records

    def _maybe_capture_file(self, record: ArtifactRecord) -> None:
        if record.size_bytes is None:
            record.notes.append("size_unknown")
            return
        if record.size_bytes > self._options.copy_max_bytes and record.size_bytes > self._options.hash_max_bytes:
            record.copy_status = "skipped_too_large"
            record.notes.append(
                f"file exceeds both copy and hash thresholds ({record.size_bytes} bytes)"
            )
            return
        payload = self._read_remote_bytes(record)
        if payload is None:
            record.copy_status = "read_failed"
            return
        if record.size_bytes <= self._options.hash_max_bytes:
            record.sha256 = sha256_bytes(payload)
        else:
            record.notes.append("hash_skipped_above_threshold")
        record.text_like = not looks_binary(payload)
        if record.text_like:
            record.quick_text_preview = decode_lossy(payload[: self._options.text_preview_max_bytes])
        if self._options.mode == "snapshot" and record.size_bytes <= self._options.copy_max_bytes:
            record.copied_relative_path = self._copy_record_payload(record, payload)
            record.copy_status = "copied"
        elif self._options.mode == "snapshot":
            record.copy_status = "skipped_too_large"
            record.notes.append("copy_skipped_above_threshold")
        else:
            record.copy_status = "hashed_only"

    def _read_remote_bytes(self, record: ArtifactRecord) -> bytes | None:
        if record.source_kind == "adb_private":
            command = self._adb_command(
                "exec-out",
                "run-as",
                self._options.package_name,
                "cat",
                record.relative_path,
            )
        elif record.source_kind == "adb_external":
            command = self._adb_command("exec-out", "cat", record.source_path)
        else:
            return None
        assert self._runner is not None
        result = self._runner.run(command, purpose=f"read_{record.collector_id}")
        if not result.ok:
            record.errors.append(self._summarize_failure(result))
            return None
        return result.stdout

    def _copy_record_payload(self, record: ArtifactRecord, payload: bytes) -> str:
        collector_root = self._extracted_dir / sanitize_name(record.collector_id)
        target_path = collector_root / self._safe_relative_copy_path(record.relative_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(payload)
        return str(target_path.relative_to(self._snapshot_dir))

    def _safe_relative_copy_path(self, relative_path: str) -> Path:
        if relative_path in {".", ""}:
            return Path("_root")
        parts = [sanitize_name(part) for part in relative_path.split("/") if part not in {"", "."}]
        if not parts:
            return Path("_root")
        return Path(*parts)

    def _ingest_local_file(
        self,
        *,
        collector_id: str,
        source_kind: str,
        source_root: str,
        source_path: str,
        relative_path: str,
        extraction_method: str,
    ) -> None:
        path = Path(source_path)
        stats = path.stat()
        payload = path.read_bytes()
        record = ArtifactRecord(
            artifact_key=f"{source_kind}|{source_path}",
            collector_id=collector_id,
            source_kind=source_kind,
            source_root=source_root,
            source_path=source_path,
            relative_path=relative_path,
            entry_type="file",
            accessible=True,
            extraction_method=extraction_method,
            size_bytes=stats.st_size,
            mtime_epoch=int(stats.st_mtime),
            mtime_utc=to_iso_utc(int(stats.st_mtime)),
            sha256=sha256_bytes(payload) if len(payload) <= self._options.hash_max_bytes else None,
            text_like=not looks_binary(payload),
        )
        if record.text_like:
            record.quick_text_preview = decode_lossy(payload[: self._options.text_preview_max_bytes])
        if self._options.mode == "snapshot" and len(payload) <= self._options.copy_max_bytes:
            record.copied_relative_path = self._copy_record_payload(record, payload)
            record.copy_status = "copied"
        elif self._options.mode == "snapshot":
            record.copy_status = "skipped_too_large"
        else:
            record.copy_status = "hashed_only"
        self._enrich_artifact_metadata(record)
        self._artifacts.append(record)

    def _enrich_artifact_metadata(self, record: ArtifactRecord) -> None:
        extension = Path(record.source_path).suffix.lower()
        record.extension = extension or None
        if record.entry_type == "dir":
            record.file_class = "directory"
            record.priority = "low"
            record.priority_score = 0
            return
        score = 5
        file_class = "unknown"
        notes: list[str] = []
        normalized_path = record.source_path.lower()
        if extension in {".dat", ".bin"}:
            file_class = "binary_state_blob"
            score += 35
            notes.append("binary_blob_extension")
        if extension == ".json":
            file_class = "json_state_or_config"
            score += 28
            notes.append("json_extension")
        if extension == ".xml":
            file_class = "xml_state_or_config"
            score += 26
            notes.append("xml_extension")
        if extension in {".sqlite", ".db", ".db3"}:
            file_class = "sqlite_database"
            score += 40
            notes.append("database_extension")
        if extension in {".log", ".txt"} and file_class == "unknown":
            file_class = "log_or_text"
            score += 10
            notes.append("text_log_extension")
        if extension == ".apk":
            file_class = "installed_package"
            score += 18
            notes.append("apk_package")
        for token, bonus, label in [
            ("shared_prefs", 35, "shared_prefs_path"),
            ("databases", 35, "databases_path"),
            ("files", 22, "files_path"),
            ("no_backup", 18, "no_backup_path"),
            ("cache", -5, "cache_path"),
            ("code_cache", -10, "code_cache_path"),
            ("playerinfo", 40, "playerinfo_name"),
            ("reward", 18, "reward_name"),
            ("timer", 18, "timer_name"),
            ("cooldown", 18, "cooldown_name"),
            ("purchase", 16, "purchase_name"),
            ("receipt", 14, "receipt_name"),
            ("unity", 18, "unity_name"),
            ("firebase", 10, "firebase_name"),
            ("preferences_pb", 20, "preferences_pb_name"),
            ("analytics", -8, "analytics_name"),
        ]:
            if token in normalized_path:
                score += bonus
                notes.append(label)
        if record.source_kind == "adb_private":
            score += 20
            notes.append("private_package_storage")
        elif record.source_kind == "adb_external":
            score += 8
            notes.append("external_package_storage")
        elif record.source_kind == "windows_host":
            score += 4
            notes.append("bluestacks_host_metadata")
            if file_class == "unknown":
                file_class = "host_metadata"
        if score >= 60:
            record.priority = "high"
        elif score >= 25:
            record.priority = "medium"
        else:
            record.priority = "low"
        record.file_class = file_class
        record.priority_score = score
        record.notes.extend(notes)

    def _pull_and_inventory_apk(self) -> None:
        pm_path_result = self._run_adb_shell(
            ["pm", "path", self._options.package_name],
            purpose="pm_path_package_for_apk_pull",
        )
        if not pm_path_result.ok:
            self._limitations.append(
                f"APK pull skipped because pm path failed: {self._summarize_failure(pm_path_result)}"
            )
            return
        package_paths = []
        for raw_line in decode_lossy(pm_path_result.stdout).splitlines():
            line = raw_line.strip()
            if line.startswith("package:"):
                package_paths.append(line.removeprefix("package:"))
        if not package_paths:
            self._limitations.append("APK pull skipped because pm path returned no package paths.")
            return
        installed_package_dir = self._context_dir / "installed_package"
        installed_package_dir.mkdir(parents=True, exist_ok=True)
        pulled_any = False
        for index, remote_apk_path in enumerate(package_paths):
            apk_name = Path(remote_apk_path).name
            local_apk_path = installed_package_dir / apk_name
            assert self._runner is not None
            pull_result = self._runner.run(
                self._adb_command("pull", remote_apk_path, str(local_apk_path)),
                purpose=f"pull_installed_apk_{index + 1:02d}_{sanitize_name(apk_name)}",
            )
            self._record_method_result(
                f"pull_installed_apk_{sanitize_name(apk_name)}",
                pull_result,
                f"Read-only pull of installed package APK member {apk_name}.",
            )
            if not pull_result.ok:
                self._limitations.append(
                    f"Installed APK pull failed for {remote_apk_path}: {self._summarize_failure(pull_result)}"
                )
                continue
            pulled_any = True
            label = "installed_base_apk" if apk_name == "base.apk" else f"installed_{sanitize_name(apk_name)}"
            self._context_files.append(
                ContextFile(
                    label=label,
                    relative_path=str(local_apk_path.relative_to(self._snapshot_dir)),
                    source=remote_apk_path,
                    note="Read-only APK copy for member inventory only.",
                )
            )
            self._inventory_apk(local_apk_path, remote_apk_path)
        if not pulled_any:
            self._limitations.append("Installed APK pull failed for all package APK paths.")

    def _inventory_apk(self, apk_path: Path, source_path: str) -> None:
        records: list[dict[str, object]] = []
        interesting: list[dict[str, object]] = []
        with zipfile.ZipFile(apk_path) as archive:
            for member in archive.infolist():
                member_path = member.filename
                ext = Path(member_path).suffix.lower()
                notes: list[str] = []
                score = 0
                if "assets/bin/data" in member_path.lower():
                    score += 30
                    notes.append("unity_data_member")
                if "managed/metadata" in member_path.lower():
                    score += 30
                    notes.append("global_metadata_candidate")
                if "resources.assets" in member_path.lower():
                    score += 20
                    notes.append("unity_resources_assets")
                if ext in {".json", ".xml", ".txt"}:
                    score += 12
                    notes.append("inspectable_text_member")
                if ext == ".so":
                    score += 8
                    notes.append("native_library")
                row = {
                    "member_path": member_path,
                    "file_size": member.file_size,
                    "compress_size": member.compress_size,
                    "extension": ext or None,
                    "score": score,
                    "notes": notes,
                }
                records.append(row)
                if score > 0:
                    interesting.append(row)
        records.sort(key=lambda row: str(row["member_path"]))
        interesting.sort(key=lambda row: (-int(row["score"]), str(row["member_path"])))
        write_json(self._reports_dir / "apk_inventory.json", records)
        write_json(self._reports_dir / "apk_interesting_members.json", interesting[:200])
        payload = apk_path.read_bytes()
        self._artifacts.append(
            ArtifactRecord(
                artifact_key=f"adb_apk|{source_path}",
                collector_id="installed_base_apk",
                source_kind="adb_apk",
                source_root=str(Path(source_path).parent).replace("\\", "/"),
                source_path=source_path,
                relative_path=Path(source_path).name,
                entry_type="file",
                accessible=True,
                extraction_method="adb pull",
                size_bytes=apk_path.stat().st_size,
                mtime_epoch=int(apk_path.stat().st_mtime),
                mtime_utc=to_iso_utc(int(apk_path.stat().st_mtime)),
                sha256=sha256_bytes(payload),
                extension=".apk",
                file_class="installed_package",
                text_like=False,
                copy_status="copied",
                copied_relative_path=str(apk_path.relative_to(self._snapshot_dir)),
                priority="medium",
                priority_score=25,
                notes=["apk_inventory_available"],
            )
        )

    def _persist_context_payload(
        self,
        *,
        label: str,
        relative_path: str,
        payload: bytes,
        note: str,
        source: str,
    ) -> None:
        path = self._snapshot_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        self._context_files.append(
            ContextFile(
                label=label,
                relative_path=relative_path,
                source=source,
                note=note,
            )
        )

    def _record_method_result(
        self,
        method_id: str,
        result: CommandResult,
        description: str,
    ) -> None:
        self._method_status.append(
            MethodStatus(
                method_id=method_id,
                description=description,
                status="ok" if result.ok else "blocked",
                detail=None if result.ok else self._summarize_failure(result),
            )
        )

    def _summarize_failure(self, result: CommandResult) -> str:
        stderr_text = decode_lossy(result.stderr).strip()
        stdout_text = decode_lossy(result.stdout).strip()
        detail = stderr_text or stdout_text or result.receipt.spawn_error or "no output"
        if len(detail) > 240:
            detail = f"{detail[:237]}..."
        return f"returncode={result.receipt.returncode}; {detail}"

    def _write_outputs(self, candidate_roots: list[CandidateRoot]) -> None:
        artifacts = sorted(self._artifacts, key=lambda item: (item.source_kind, item.source_path))
        inventory_payload = [asdict(item) for item in artifacts]
        csv_rows = []
        for item in inventory_payload:
            row = dict(item)
            row["notes"] = ";".join(item["notes"])
            row["errors"] = ";".join(item["errors"])
            csv_rows.append(row)
        write_json(self._snapshot_dir / "inventory.json", inventory_payload)
        write_csv(
            self._snapshot_dir / "inventory.csv",
            csv_rows,
            [
                "artifact_key",
                "collector_id",
                "source_kind",
                "source_root",
                "source_path",
                "relative_path",
                "entry_type",
                "accessible",
                "extraction_method",
                "size_bytes",
                "mtime_epoch",
                "mtime_utc",
                "sha256",
                "extension",
                "file_class",
                "text_like",
                "copy_status",
                "copied_relative_path",
                "quick_text_preview",
                "priority",
                "priority_score",
                "notes",
                "errors",
            ],
        )
        tree_lines = []
        for item in artifacts:
            prefix = "D" if item.entry_type == "dir" else "F"
            size_text = "-" if item.size_bytes is None else str(item.size_bytes)
            tree_lines.append(
                f"{prefix}\t{item.priority}\t{size_text}\t{item.source_kind}\t{item.source_path}"
            )
        (self._snapshot_dir / "tree.txt").write_text("\n".join(tree_lines) + "\n", encoding="utf-8")
        write_jsonl(self._snapshot_dir / "events.jsonl", self._events)
        manifest = SnapshotManifest(
            schema_version="artifact-snapshot-v1",
            mode=self._options.mode,
            snapshot_id=self._snapshot_id,
            package_name=self._options.package_name,
            created_at_utc=self._created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            output_dir=str(self._snapshot_dir),
            host_platform=platform.platform(),
            working_directory=os.getcwd(),
            adb_path=self._options.adb_path,
            adb_serial=self._options.adb_serial,
            hash_max_bytes=self._options.hash_max_bytes,
            copy_max_bytes=self._options.copy_max_bytes,
            text_preview_max_bytes=self._options.text_preview_max_bytes,
            pull_apk=self._options.pull_apk,
            candidate_roots=[asdict(item) for item in candidate_roots],
            method_status=self._method_status,
            limitations=self._limitations,
            command_receipt_count=len(list(self._receipts_dir.glob("*.json"))),
            artifact_count=len(artifacts),
            file_count=sum(1 for item in artifacts if item.entry_type == "file"),
            directory_count=sum(1 for item in artifacts if item.entry_type == "dir"),
            copied_file_count=sum(1 for item in artifacts if item.copy_status == "copied"),
            context_files=self._context_files,
        )
        write_json(self._snapshot_dir / "manifest.json", asdict(manifest))
        summary_lines = [
            f"snapshot_id: {manifest.snapshot_id}",
            f"mode: {manifest.mode}",
            f"package_name: {manifest.package_name}",
            f"artifact_count: {manifest.artifact_count}",
            f"file_count: {manifest.file_count}",
            f"directory_count: {manifest.directory_count}",
            f"copied_file_count: {manifest.copied_file_count}",
            "",
            "method_status:",
        ]
        for status in self._method_status:
            detail = f" ({status.detail})" if status.detail else ""
            summary_lines.append(f"- {status.method_id}: {status.status}{detail}")
        if self._limitations:
            summary_lines.extend(["", "limitations:"])
            for limitation in self._limitations:
                summary_lines.append(f"- {limitation}")
        (self._reports_dir / "summary.txt").write_text(
            "\n".join(summary_lines) + "\n",
            encoding="utf-8",
        )

    def _log_event(self, event_type: str, **fields: object) -> None:
        event = {"event_type": event_type, "timestamp_utc": utc_timestamp()}
        event.update(fields)
        self._events.append(event)

    def _adb_command(self, *parts: str) -> list[str]:
        command = [self._options.adb_path]
        if self._options.adb_serial:
            command.extend(["-s", self._options.adb_serial])
        command.extend(parts)
        return command

    def _run_adb(self, parts: list[str], *, purpose: str) -> CommandResult:
        assert self._runner is not None
        return self._runner.run(self._adb_command(*parts), purpose=purpose)

    def _run_adb_shell(self, parts: list[str], *, purpose: str) -> CommandResult:
        assert self._runner is not None
        return self._runner.run(self._adb_command("shell", *parts), purpose=purpose)


def run_discovery(options: DiscoveryOptions) -> Path:
    """Execute one census or snapshot run and return the output directory."""

    return DiscoverySession(options).run()

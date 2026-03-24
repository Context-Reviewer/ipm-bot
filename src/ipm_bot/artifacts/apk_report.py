"""Read-only APK inventory and extraction helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import platform
from zipfile import ZipFile, ZipInfo

from .shared import make_run_id, sanitize_name, sha256_bytes, utc_timestamp, write_json, write_csv


DEFAULT_APK_REPORT_ROOT = Path(__file__).resolve().parents[3] / "data" / "artifacts" / "apk_reports"


@dataclass(frozen=True, slots=True)
class ApkMemberRecord:
    member_path: str
    file_size: int
    compress_size: int
    crc32_hex: str
    sha256: str | None
    extension: str | None
    classification: str
    interesting: bool
    notes: list[str]
    extracted_relative_path: str | None = None


def run_apk_report(apk_input: Path, output_root: Path = DEFAULT_APK_REPORT_ROOT) -> Path:
    apk_path = _resolve_apk_path(apk_input)
    output_dir = output_root / make_run_id(f"apk_report_{sanitize_name(apk_path.stem)}")
    output_dir.mkdir(parents=True, exist_ok=False)

    records: list[ApkMemberRecord] = []
    extracted_count = 0
    il2cpp_indicators: list[str] = []

    with ZipFile(apk_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            record, extracted = _record_member(archive, info, output_dir)
            records.append(record)
            if extracted:
                extracted_count += 1
            if "il2cpp" in record.classification and record.member_path not in il2cpp_indicators:
                il2cpp_indicators.append(record.member_path)

    payload_rows = [_record_payload(record) for record in records]
    write_json(output_dir / "apk_inventory.json", payload_rows)
    write_csv(
        output_dir / "apk_inventory.csv",
        payload_rows,
        fieldnames=[
            "member_path",
            "file_size",
            "compress_size",
            "crc32_hex",
            "sha256",
            "extension",
            "classification",
            "interesting",
            "notes",
            "extracted_relative_path",
        ],
    )

    interesting_rows = [row for row in payload_rows if row["interesting"]]
    write_json(output_dir / "interesting_members.json", interesting_rows)

    manifest = {
        "schema_version": "apk-report-v1",
        "created_at_utc": utc_timestamp(),
        "apk_input": str(apk_input),
        "resolved_apk_path": str(apk_path.resolve()),
        "output_dir": str(output_dir.resolve()),
        "host_platform": platform.platform(),
        "member_count": len(records),
        "interesting_member_count": len(interesting_rows),
        "extracted_member_count": extracted_count,
        "il2cpp_detected": bool(il2cpp_indicators),
        "il2cpp_indicators": il2cpp_indicators,
    }
    write_json(output_dir / "manifest.json", manifest)
    summary_lines = [
        f"resolved_apk_path: {apk_path.resolve()}",
        f"member_count: {len(records)}",
        f"interesting_member_count: {len(interesting_rows)}",
        f"extracted_member_count: {extracted_count}",
        f"il2cpp_detected: {str(bool(il2cpp_indicators)).lower()}",
    ]
    if il2cpp_indicators:
        summary_lines.append("il2cpp_indicators:")
        summary_lines.extend(f"- {member}" for member in il2cpp_indicators)
    (output_dir / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return output_dir


def _resolve_apk_path(apk_input: Path) -> Path:
    if apk_input.is_file():
        return apk_input
    candidate = apk_input / "context" / "installed_package" / "base.apk"
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(
        f"Could not resolve APK path from {apk_input}. Provide base.apk directly or a snapshot dir containing context/installed_package/base.apk."
    )


def _record_member(archive: ZipFile, info: ZipInfo, output_dir: Path) -> tuple[ApkMemberRecord, bool]:
    member_path = info.filename
    member_name = PurePosixPath(member_path).name
    extension = PurePosixPath(member_name).suffix.lower() or None
    notes: list[str] = []
    classification = "generic_apk_member"
    should_extract = False

    if member_path.endswith("/libil2cpp.so"):
        classification = "il2cpp_native_runtime"
        notes.append("il2cpp_runtime")
        should_extract = True
    elif member_path.endswith("/global-metadata.dat"):
        classification = "il2cpp_metadata"
        notes.append("il2cpp_metadata")
        should_extract = True
    elif member_path.endswith("/Assembly-CSharp.dll"):
        classification = "managed_game_assembly"
        notes.append("managed_assembly")
        should_extract = True
    elif "/assets/bin/Data/Managed/" in member_path:
        classification = "managed_support_assembly"
        notes.append("managed_support")
        should_extract = True
    elif member_path.endswith("AndroidManifest.xml"):
        classification = "apk_manifest"
        notes.append("package_metadata")
        should_extract = True
    elif member_path.endswith(".so"):
        classification = "native_library"
    elif member_path.endswith(".dex"):
        classification = "dex_bytecode"
    elif member_path.endswith(".arsc"):
        classification = "android_resources"

    payload = archive.read(info)
    sha256 = sha256_bytes(payload)
    extracted_relative_path: str | None = None
    extracted = False
    if should_extract:
        extracted_relative_path = str(Path("extracted_members") / PurePosixPath(member_path))
        destination = output_dir / extracted_relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        extracted = True

    return (
        ApkMemberRecord(
            member_path=member_path,
            file_size=info.file_size,
            compress_size=info.compress_size,
            crc32_hex=f"{info.CRC:08x}",
            sha256=sha256,
            extension=extension,
            classification=classification,
            interesting=should_extract or classification.startswith("il2cpp"),
            notes=notes,
            extracted_relative_path=extracted_relative_path,
        ),
        extracted,
    )


def _record_payload(record: ApkMemberRecord) -> dict[str, object]:
    return {
        "member_path": record.member_path,
        "file_size": record.file_size,
        "compress_size": record.compress_size,
        "crc32_hex": record.crc32_hex,
        "sha256": record.sha256,
        "extension": record.extension,
        "classification": record.classification,
        "interesting": record.interesting,
        "notes": record.notes,
        "extracted_relative_path": record.extracted_relative_path,
    }

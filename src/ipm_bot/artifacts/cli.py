"""CLI for package-focused artifact discovery and diffing."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from .apk_report import DEFAULT_APK_REPORT_ROOT, run_apk_report
from .diffing import run_diff
from .discovery import DiscoveryOptions, run_discovery
from .il2cpp_input_report import run_il2cpp_input_report
from .il2cpp_assembly_priority_report import run_il2cpp_assembly_priority_report
from .il2cpp_manual_findings_report import run_il2cpp_manual_findings_report
from .il2cpp_name_hint_report import run_il2cpp_name_hint_report
from .il2cpp_output_catalog import run_il2cpp_output_catalog
from .il2cpp_workspace import run_il2cpp_workspace
from .shared import (
    DEFAULT_COPY_MAX_BYTES,
    DEFAULT_HASH_MAX_BYTES,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_PACKAGE_NAME,
    DEFAULT_TEXT_DIFF_MAX_BYTES,
    DEFAULT_TEXT_PREVIEW_MAX_BYTES,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command in {"census", "snapshot"}:
            output_dir = run_discovery(
                DiscoveryOptions(
                    mode=args.command,
                    package_name=args.package_name,
                    output_root=args.output_root,
                    adb_path=args.adb_path,
                    adb_serial=args.adb_serial,
                    hash_max_bytes=args.hash_max_bytes,
                    copy_max_bytes=args.copy_max_bytes,
                    text_preview_max_bytes=args.text_preview_max_bytes,
                    pull_apk=args.pull_apk,
                )
            )
            print(str(output_dir))
            return 0
        if args.command == "diff":
            output_dir = run_diff(
                args.before_snapshot_dir,
                args.after_snapshot_dir,
                output_root=args.output_root,
                text_diff_max_bytes=args.text_diff_max_bytes,
            )
            print(str(output_dir))
            return 0
        if args.command == "apk-report":
            output_dir = run_apk_report(
                args.apk_input,
                output_root=args.output_root,
            )
            print(str(output_dir))
            return 0
        if args.command == "il2cpp-workspace":
            output_dir = run_il2cpp_workspace(
                args.snapshot,
                output_root=args.output_root,
            )
            print(str(output_dir))
            return 0
        if args.command == "il2cpp-input-report":
            output_dir = run_il2cpp_input_report(
                args.workspace,
                output_root=args.output_root,
                notes=args.notes,
            )
            print(str(output_dir))
            return 0
        if args.command == "il2cpp-output-catalog":
            output_dir = run_il2cpp_output_catalog(
                args.output_dir,
                input_report_path=args.input_report,
                workspace_path=args.workspace,
                output_root=args.output_root,
                tool_name=args.tool_name,
                tool_version=args.tool_version,
                notes=args.notes,
            )
            print(str(output_dir))
            return 0
        if args.command == "il2cpp-name-hint-report":
            output_dir = run_il2cpp_name_hint_report(
                args.catalog,
                terms=args.term,
                case_sensitive=args.case_sensitive,
                output_root=args.output_root,
                notes=args.notes,
            )
            print(str(output_dir))
            return 0
        if args.command == "il2cpp-assembly-priority-report":
            output_dir = run_il2cpp_assembly_priority_report(
                args.catalog,
                output_root=args.output_root,
                notes=args.notes,
            )
            print(str(output_dir))
            return 0
        if args.command == "il2cpp-manual-findings-report":
            output_dir = run_il2cpp_manual_findings_report(
                catalog_path=args.catalog,
                name_hint_report_path=args.name_hint_report,
                finding_paths=args.finding_path,
                finding_notes=args.finding_note,
                finding_symbols=args.finding_symbol,
                finding_kinds=args.finding_kind,
                analyst=args.analyst,
                notes=args.notes,
                output_root=args.output_root,
            )
            print(str(output_dir))
            return 0
        parser.error(f"Unsupported command: {args.command}")
        return 2
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safe, package-focused artifact census/snapshot/diff tooling for Idle Planet Miner on BlueStacks."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command_name in ("census", "snapshot"):
        subparser = subparsers.add_parser(
            command_name,
            help=f"Run a {command_name} of accessible package-scoped artifacts.",
        )
        _add_common_discovery_arguments(subparser)
        subparser.add_argument(
            "--pull-apk",
            action="store_true",
            help="Attempt a read-only pull of the installed APK and inventory its members.",
        )

    diff_parser = subparsers.add_parser(
        "diff",
        help="Compare two prior artifact snapshots and rank the changed artifacts.",
    )
    diff_parser.add_argument("before_snapshot_dir", type=Path)
    diff_parser.add_argument("after_snapshot_dir", type=Path)
    diff_parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Base output directory used for diff reports.",
    )
    diff_parser.add_argument(
        "--text-diff-max-bytes",
        type=int,
        default=DEFAULT_TEXT_DIFF_MAX_BYTES,
        help="Maximum file size eligible for quick text diff previews.",
    )

    apk_parser = subparsers.add_parser(
        "apk-report",
        help="Inventory a pulled base.apk and extract IL2CPP/managed-analysis members.",
    )
    apk_parser.add_argument(
        "apk_input",
        type=Path,
        help="Path to base.apk or a snapshot directory containing context/installed_package/base.apk.",
    )
    apk_parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_APK_REPORT_ROOT,
        help="Base output directory used for APK reports.",
    )

    il2cpp_parser = subparsers.add_parser(
        "il2cpp-workspace",
        help="Stage global-metadata.dat and libil2cpp.so from an existing snapshot for external IL2CPP tooling.",
    )
    il2cpp_parser.add_argument(
        "--snapshot",
        type=Path,
        required=True,
        help="Artifact snapshot root containing context/installed_package/base.apk and split_config.arm64_v8a.apk.",
    )
    il2cpp_parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Base artifact root used for IL2CPP workspace staging output.",
    )

    il2cpp_input_report_parser = subparsers.add_parser(
        "il2cpp-input-report",
        help="Validate an existing il2cpp-workspace handoff and write a normalized input report.",
    )
    il2cpp_input_report_parser.add_argument(
        "--workspace",
        type=Path,
        required=True,
        help="Path to an existing il2cpp-workspace artifact directory.",
    )
    il2cpp_input_report_parser.add_argument(
        "--notes",
        default=None,
        help="Optional operator notes about the external IL2CPP tool/run that used this workspace.",
    )
    il2cpp_input_report_parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Base artifact root used for IL2CPP input report output.",
    )

    il2cpp_output_catalog_parser = subparsers.add_parser(
        "il2cpp-output-catalog",
        help="Catalog an external IL2CPP reconstruction output directory without validating semantics.",
    )
    il2cpp_output_catalog_parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory containing external IL2CPP reconstruction output to inventory.",
    )
    il2cpp_output_catalog_source_group = il2cpp_output_catalog_parser.add_mutually_exclusive_group(
        required=True
    )
    il2cpp_output_catalog_source_group.add_argument(
        "--input-report",
        type=Path,
        default=None,
        help="Existing il2cpp-input-report artifact linked to this external tool run.",
    )
    il2cpp_output_catalog_source_group.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Existing il2cpp-workspace artifact linked to this external tool run.",
    )
    il2cpp_output_catalog_parser.add_argument(
        "--tool-name",
        default=None,
        help="Optional external tool name, for example Cpp2IL.",
    )
    il2cpp_output_catalog_parser.add_argument(
        "--tool-version",
        default=None,
        help="Optional external tool version string.",
    )
    il2cpp_output_catalog_parser.add_argument(
        "--notes",
        default=None,
        help="Optional operator notes about the external tool run.",
    )
    il2cpp_output_catalog_parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Base artifact root used for IL2CPP output catalog artifacts.",
    )

    il2cpp_name_hint_report_parser = subparsers.add_parser(
        "il2cpp-name-hint-report",
        help="Filter an il2cpp-output-catalog by filename/path terms without opening file contents.",
    )
    il2cpp_name_hint_report_parser.add_argument(
        "--catalog",
        type=Path,
        required=True,
        help="Path to an existing il2cpp-output-catalog artifact directory.",
    )
    il2cpp_name_hint_report_parser.add_argument(
        "--term",
        action="append",
        required=True,
        help="Search term matched against cataloged relative paths. Repeat for multiple terms.",
    )
    il2cpp_name_hint_report_parser.add_argument(
        "--case-sensitive",
        action="store_true",
        help="Use case-sensitive term matching.",
    )
    il2cpp_name_hint_report_parser.add_argument(
        "--notes",
        default=None,
        help="Optional operator notes for this metadata-only narrowing pass.",
    )
    il2cpp_name_hint_report_parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Base artifact root used for IL2CPP name hint reports.",
    )

    il2cpp_manual_findings_report_parser = subparsers.add_parser(
        "il2cpp-manual-findings-report",
        help="Record human-entered findings tied to a catalog or name-hint-report without validating semantics.",
    )
    il2cpp_assembly_priority_report_parser = subparsers.add_parser(
        "il2cpp-assembly-priority-report",
        help="Rank dumped assemblies in an il2cpp-output-catalog by likely usefulness to the bot.",
    )
    il2cpp_assembly_priority_report_parser.add_argument(
        "--catalog",
        type=Path,
        required=True,
        help="Path to an existing il2cpp-output-catalog artifact directory.",
    )
    il2cpp_assembly_priority_report_parser.add_argument(
        "--notes",
        default=None,
        help="Optional operator notes for this metadata-only assembly triage pass.",
    )
    il2cpp_assembly_priority_report_parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Base artifact root used for IL2CPP assembly priority reports.",
    )

    il2cpp_manual_findings_source_group = il2cpp_manual_findings_report_parser.add_mutually_exclusive_group(
        required=True
    )
    il2cpp_manual_findings_source_group.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Path to an existing il2cpp-output-catalog artifact directory.",
    )
    il2cpp_manual_findings_source_group.add_argument(
        "--name-hint-report",
        type=Path,
        default=None,
        help="Path to an existing il2cpp-name-hint-report artifact directory.",
    )
    il2cpp_manual_findings_report_parser.add_argument(
        "--finding-path",
        action="append",
        required=True,
        help="Catalog relative path for one human finding. Repeat for multiple findings.",
    )
    il2cpp_manual_findings_report_parser.add_argument(
        "--finding-note",
        action="append",
        required=True,
        help="Human note for the corresponding finding-path entry. Repeat in the same order.",
    )
    il2cpp_manual_findings_report_parser.add_argument(
        "--finding-symbol",
        action="append",
        default=None,
        help="Optional symbol label for the corresponding finding-path entry. Repeat in the same order.",
    )
    il2cpp_manual_findings_report_parser.add_argument(
        "--finding-kind",
        action="append",
        default=None,
        help="Optional kind label for the corresponding finding-path entry. Repeat in the same order.",
    )
    il2cpp_manual_findings_report_parser.add_argument(
        "--analyst",
        default=None,
        help="Optional analyst identifier for these human-entered findings.",
    )
    il2cpp_manual_findings_report_parser.add_argument(
        "--notes",
        default=None,
        help="Optional global notes for this manual findings report.",
    )
    il2cpp_manual_findings_report_parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Base artifact root used for IL2CPP manual findings reports.",
    )
    return parser


def _add_common_discovery_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--package-name",
        default=DEFAULT_PACKAGE_NAME,
        help="Target Android package to inspect.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Base output directory used for census/snapshot artifacts.",
    )
    parser.add_argument(
        "--adb-path",
        default="adb",
        help="ADB executable path.",
    )
    parser.add_argument(
        "--adb-serial",
        default=None,
        help="Optional ADB serial for a specific emulator/device.",
    )
    parser.add_argument(
        "--hash-max-bytes",
        type=int,
        default=DEFAULT_HASH_MAX_BYTES,
        help="Maximum file size to hash directly during collection.",
    )
    parser.add_argument(
        "--copy-max-bytes",
        type=int,
        default=DEFAULT_COPY_MAX_BYTES,
        help="Maximum file size to preserve as a raw evidence copy in snapshot mode.",
    )
    parser.add_argument(
        "--text-preview-max-bytes",
        type=int,
        default=DEFAULT_TEXT_PREVIEW_MAX_BYTES,
        help="Maximum text preview size embedded in the inventory for text-like files.",
    )

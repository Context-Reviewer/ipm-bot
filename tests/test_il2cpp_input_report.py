from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.artifacts.il2cpp_input_report import run_il2cpp_input_report
from ipm_bot.artifacts.shared import sha256_bytes


class Il2CppInputReportTests(unittest.TestCase):
    def test_run_il2cpp_input_report_writes_manifest_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            workspace_dir = _build_workspace_fixture(root)

            report_dir = run_il2cpp_input_report(workspace_dir, output_root=root / "artifacts")

            self.assertTrue((report_dir / "manifest.json").is_file())
            self.assertTrue((report_dir / "summary.txt").is_file())

    def test_run_il2cpp_input_report_fails_when_required_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            workspace_dir = _build_workspace_fixture(root)
            (workspace_dir / "workspace" / "libil2cpp.so").unlink()

            with self.assertRaises(FileNotFoundError) as context:
                run_il2cpp_input_report(workspace_dir, output_root=root / "artifacts")

            self.assertIn("libil2cpp.so", str(context.exception))

    def test_run_il2cpp_input_report_propagates_source_snapshot_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            workspace_dir = _build_workspace_fixture(root)

            report_dir = run_il2cpp_input_report(workspace_dir, output_root=root / "artifacts")
            manifest = json.loads((report_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(
                manifest["source_snapshot_path"],
                "C:\\dev\\ipm-bot\\data\\artifacts\\snapshots\\fixture_snapshot",
            )

    def test_run_il2cpp_input_report_persists_notes_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata_payload = b"metadata-bytes"
            binary_payload = b"libil2cpp-bytes"
            workspace_dir = _build_workspace_fixture(
                root,
                metadata_payload=metadata_payload,
                binary_payload=binary_payload,
            )

            report_dir = run_il2cpp_input_report(
                workspace_dir,
                output_root=root / "artifacts",
                notes="Cpp2IL 2026-03-24 manual run outside repo",
            )
            manifest = json.loads((report_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(
                manifest["external_tool_notes"],
                "Cpp2IL 2026-03-24 manual run outside repo",
            )
            self.assertEqual(
                manifest["staged_files"]["global_metadata"]["sha256"],
                sha256_bytes(metadata_payload),
            )
            self.assertEqual(
                manifest["staged_files"]["libil2cpp"]["sha256"],
                sha256_bytes(binary_payload),
            )


def _build_workspace_fixture(
    root: Path,
    *,
    metadata_payload: bytes = b"metadata-bytes",
    binary_payload: bytes = b"libil2cpp-bytes",
) -> Path:
    workspace_dir = root / "il2cpp_workspaces" / "fixture_workspace"
    staged_dir = workspace_dir / "workspace"
    staged_dir.mkdir(parents=True, exist_ok=True)
    (staged_dir / "global-metadata.dat").write_bytes(metadata_payload)
    (staged_dir / "libil2cpp.so").write_bytes(binary_payload)
    (workspace_dir / "summary.txt").write_text("fixture summary\n", encoding="utf-8")
    (workspace_dir / "manifest.json").write_text(
        json.dumps(
            {
                "command_name": "il2cpp-workspace",
                "architecture": "arm64-v8a",
                "snapshot_source_path": "C:\\dev\\ipm-bot\\data\\artifacts\\snapshots\\fixture_snapshot",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return workspace_dir

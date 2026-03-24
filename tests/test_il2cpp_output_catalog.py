from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.artifacts.il2cpp_output_catalog import run_il2cpp_output_catalog
from ipm_bot.artifacts.shared import sha256_bytes


class Il2CppOutputCatalogTests(unittest.TestCase):
    def test_run_il2cpp_output_catalog_writes_manifest_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = _build_external_output_fixture(root)
            input_report_dir = _build_input_report_fixture(root)

            catalog_dir = run_il2cpp_output_catalog(
                output_dir,
                input_report_path=input_report_dir,
                output_root=root / "artifacts",
            )

            self.assertTrue((catalog_dir / "manifest.json").is_file())
            self.assertTrue((catalog_dir / "summary.txt").is_file())

    def test_run_il2cpp_output_catalog_fails_when_output_dir_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_report_dir = _build_input_report_fixture(root)

            with self.assertRaises(FileNotFoundError) as context:
                run_il2cpp_output_catalog(
                    root / "missing-output",
                    input_report_path=input_report_dir,
                    output_root=root / "artifacts",
                )

            self.assertIn("IL2CPP external output directory does not exist", str(context.exception))

    def test_run_il2cpp_output_catalog_propagates_source_snapshot_from_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = _build_external_output_fixture(root)
            workspace_dir = _build_workspace_fixture(root)

            catalog_dir = run_il2cpp_output_catalog(
                output_dir,
                workspace_path=workspace_dir,
                output_root=root / "artifacts",
            )
            manifest = json.loads((catalog_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(
                manifest["source_snapshot_path"],
                "C:\\dev\\ipm-bot\\data\\artifacts\\snapshots\\fixture_snapshot",
            )
            self.assertEqual(manifest["linked_workspace_path"], str(workspace_dir.resolve()))

    def test_run_il2cpp_output_catalog_persists_tool_metadata_and_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = _build_external_output_fixture(root)
            input_report_dir = _build_input_report_fixture(root)

            catalog_dir = run_il2cpp_output_catalog(
                output_dir,
                input_report_path=input_report_dir,
                output_root=root / "artifacts",
                tool_name="Cpp2IL",
                tool_version="2026.3.24",
                notes="manual analyst run",
            )
            manifest = json.loads((catalog_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["tool_name"], "Cpp2IL")
            self.assertEqual(manifest["tool_version"], "2026.3.24")
            self.assertEqual(manifest["notes"], "manual analyst run")

    def test_run_il2cpp_output_catalog_uses_stable_relative_path_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = _build_external_output_fixture(root)
            input_report_dir = _build_input_report_fixture(root)

            catalog_dir = run_il2cpp_output_catalog(
                output_dir,
                input_report_path=input_report_dir,
                output_root=root / "artifacts",
            )
            manifest = json.loads((catalog_dir / "manifest.json").read_text(encoding="utf-8"))

            inventory = manifest["file_inventory"]
            self.assertEqual(
                [item["relative_path"] for item in inventory],
                ["DummyAssembly/Assembly-CSharp.dll", "script.json"],
            )
            self.assertEqual(
                inventory[0]["sha256"],
                sha256_bytes(b"assembly"),
            )
            self.assertEqual(
                inventory[1]["sha256"],
                sha256_bytes(b'{"tool":"cpp2il"}\n'),
            )


def _build_external_output_fixture(root: Path) -> Path:
    output_dir = root / "external_output"
    (output_dir / "DummyAssembly").mkdir(parents=True, exist_ok=True)
    (output_dir / "DummyAssembly" / "Assembly-CSharp.dll").write_bytes(b"assembly")
    (output_dir / "script.json").write_bytes(b'{"tool":"cpp2il"}\n')
    return output_dir


def _build_input_report_fixture(root: Path) -> Path:
    report_dir = root / "il2cpp_input_reports" / "fixture_input_report"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "summary.txt").write_text("fixture summary\n", encoding="utf-8")
    (report_dir / "manifest.json").write_text(
        json.dumps(
            {
                "command_name": "il2cpp-input-report",
                "workspace_path": str((root / "il2cpp_workspaces" / "fixture_workspace").resolve()),
                "source_snapshot_path": "C:\\dev\\ipm-bot\\data\\artifacts\\snapshots\\fixture_snapshot",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return report_dir


def _build_workspace_fixture(root: Path) -> Path:
    workspace_dir = root / "il2cpp_workspaces" / "fixture_workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "summary.txt").write_text("fixture summary\n", encoding="utf-8")
    (workspace_dir / "manifest.json").write_text(
        json.dumps(
            {
                "command_name": "il2cpp-workspace",
                "snapshot_source_path": "C:\\dev\\ipm-bot\\data\\artifacts\\snapshots\\fixture_snapshot",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return workspace_dir

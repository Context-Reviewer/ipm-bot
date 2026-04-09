from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.artifacts.il2cpp_assembly_priority_report import run_il2cpp_assembly_priority_report


class Il2CppAssemblyPriorityReportTests(unittest.TestCase):
    def test_run_il2cpp_assembly_priority_report_writes_manifest_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            catalog_dir = _build_catalog_fixture(root)

            report_dir = run_il2cpp_assembly_priority_report(
                catalog_dir,
                output_root=root / "artifacts",
            )

            self.assertTrue((report_dir / "manifest.json").is_file())
            self.assertTrue((report_dir / "summary.txt").is_file())

    def test_run_il2cpp_assembly_priority_report_ranks_core_bot_assemblies_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            catalog_dir = _build_catalog_fixture(root)

            report_dir = run_il2cpp_assembly_priority_report(
                catalog_dir,
                output_root=root / "artifacts",
            )
            manifest = json.loads((report_dir / "manifest.json").read_text(encoding="utf-8"))

            entries = manifest["assembly_entries"]
            ordered_names = [entry["assembly_name"] for entry in entries]
            self.assertEqual(
                ordered_names[:5],
                [
                    "Assembly-CSharp.dll",
                    "Unity.LevelPlay.dll",
                    "PlayFab.dll",
                    "Firebase.Firestore.dll",
                    "Tapjoy.dll",
                ],
            )
            self.assertEqual(
                manifest["recommended_open_order"][:3],
                [
                    "DummyDll/Assembly-CSharp.dll",
                    "DummyDll/Unity.LevelPlay.dll",
                    "DummyDll/PlayFab.dll",
                ],
            )

    def test_run_il2cpp_assembly_priority_report_excludes_non_dll_entries_and_propagates_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            catalog_dir = _build_catalog_fixture(root)

            report_dir = run_il2cpp_assembly_priority_report(
                catalog_dir,
                output_root=root / "artifacts",
                notes="bot assembly triage",
            )
            manifest = json.loads((report_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(
                manifest["source_snapshot_path"],
                "C:\\dev\\ipm-bot\\data\\artifacts\\snapshots\\fixture_snapshot",
            )
            self.assertEqual(manifest["notes"], "bot assembly triage")
            assembly_paths = {entry["relative_path"] for entry in manifest["assembly_entries"]}
            self.assertNotIn("script.json", assembly_paths)
            self.assertNotIn("DummyDll/notes.txt", assembly_paths)


def _build_catalog_fixture(root: Path) -> Path:
    catalog_dir = root / "il2cpp_output_catalogs" / "fixture_catalog"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    (catalog_dir / "summary.txt").write_text("fixture summary\n", encoding="utf-8")
    (catalog_dir / "manifest.json").write_text(
        json.dumps(
            {
                "command_name": "il2cpp-output-catalog",
                "source_snapshot_path": "C:\\dev\\ipm-bot\\data\\artifacts\\snapshots\\fixture_snapshot",
                "file_inventory": [
                    {
                        "relative_path": "DummyDll/Assembly-CSharp.dll",
                        "size_bytes": 2187012,
                        "sha256": "sha-assembly-csharp",
                    },
                    {
                        "relative_path": "DummyDll/Unity.LevelPlay.dll",
                        "size_bytes": 262144,
                        "sha256": "sha-levelplay",
                    },
                    {
                        "relative_path": "DummyDll/PlayFab.dll",
                        "size_bytes": 1048576,
                        "sha256": "sha-playfab",
                    },
                    {
                        "relative_path": "DummyDll/Firebase.Firestore.dll",
                        "size_bytes": 131072,
                        "sha256": "sha-firestore",
                    },
                    {
                        "relative_path": "DummyDll/Tapjoy.dll",
                        "size_bytes": 65536,
                        "sha256": "sha-tapjoy",
                    },
                    {
                        "relative_path": "DummyDll/UnityEngine.CoreModule.dll",
                        "size_bytes": 4194304,
                        "sha256": "sha-unityengine",
                    },
                    {
                        "relative_path": "DummyDll/AppsFlyer.dll",
                        "size_bytes": 32768,
                        "sha256": "sha-appsflyer",
                    },
                    {
                        "relative_path": "DummyDll/notes.txt",
                        "size_bytes": 12,
                        "sha256": "sha-notes",
                    },
                    {
                        "relative_path": "script.json",
                        "size_bytes": 44,
                        "sha256": "sha-script",
                    },
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return catalog_dir

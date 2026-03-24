from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.artifacts.il2cpp_name_hint_report import run_il2cpp_name_hint_report


class Il2CppNameHintReportTests(unittest.TestCase):
    def test_run_il2cpp_name_hint_report_writes_manifest_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            catalog_dir = _build_catalog_fixture(root)

            report_dir = run_il2cpp_name_hint_report(
                catalog_dir,
                terms=["player"],
                output_root=root / "artifacts",
            )

            self.assertTrue((report_dir / "manifest.json").is_file())
            self.assertTrue((report_dir / "summary.txt").is_file())

    def test_run_il2cpp_name_hint_report_supports_multiple_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            catalog_dir = _build_catalog_fixture(root)

            report_dir = run_il2cpp_name_hint_report(
                catalog_dir,
                terms=["player", "reward"],
                output_root=root / "artifacts",
            )
            manifest = json.loads((report_dir / "manifest.json").read_text(encoding="utf-8"))
            matches = {item["relative_path"]: item["matched_terms"] for item in manifest["matching_entries"]}

            self.assertEqual(matches["DummyAssembly/PlayerData.cs"], ["player"])
            self.assertEqual(matches["DummyAssembly/RewardPanel.cs"], ["reward"])

    def test_run_il2cpp_name_hint_report_honors_case_sensitivity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            catalog_dir = _build_catalog_fixture(root)

            insensitive_dir = run_il2cpp_name_hint_report(
                catalog_dir,
                terms=["player"],
                case_sensitive=False,
                output_root=root / "artifacts",
            )
            sensitive_dir = run_il2cpp_name_hint_report(
                catalog_dir,
                terms=["player"],
                case_sensitive=True,
                output_root=root / "artifacts",
            )

            insensitive_manifest = json.loads((insensitive_dir / "manifest.json").read_text(encoding="utf-8"))
            sensitive_manifest = json.loads((sensitive_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(len(insensitive_manifest["matching_entries"]), 1)
            self.assertEqual(len(sensitive_manifest["matching_entries"]), 0)

    def test_run_il2cpp_name_hint_report_fails_for_missing_or_malformed_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            missing_catalog = root / "missing_catalog"
            missing_catalog.mkdir(parents=True, exist_ok=True)

            with self.assertRaises(FileNotFoundError):
                run_il2cpp_name_hint_report(
                    missing_catalog,
                    terms=["player"],
                    output_root=root / "artifacts",
                )

            malformed_catalog = root / "malformed_catalog"
            malformed_catalog.mkdir(parents=True, exist_ok=True)
            (malformed_catalog / "manifest.json").write_text("not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                run_il2cpp_name_hint_report(
                    malformed_catalog,
                    terms=["player"],
                    output_root=root / "artifacts",
                )

    def test_run_il2cpp_name_hint_report_propagates_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            catalog_dir = _build_catalog_fixture(root)

            report_dir = run_il2cpp_name_hint_report(
                catalog_dir,
                terms=["reward"],
                output_root=root / "artifacts",
                notes="manual narrowing pass",
            )
            manifest = json.loads((report_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(
                manifest["source_snapshot_path"],
                "C:\\dev\\ipm-bot\\data\\artifacts\\snapshots\\fixture_snapshot",
            )
            self.assertEqual(manifest["notes"], "manual narrowing pass")


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
                        "relative_path": "DummyAssembly/PlayerData.cs",
                        "size_bytes": 101,
                        "sha256": "sha-player",
                    },
                    {
                        "relative_path": "DummyAssembly/RewardPanel.cs",
                        "size_bytes": 202,
                        "sha256": "sha-reward",
                    },
                    {
                        "relative_path": "metadata/globalgamemanagers",
                        "size_bytes": 303,
                        "sha256": "sha-metadata",
                    },
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return catalog_dir

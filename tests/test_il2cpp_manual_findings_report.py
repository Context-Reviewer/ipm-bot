from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.artifacts.il2cpp_manual_findings_report import run_il2cpp_manual_findings_report


class Il2CppManualFindingsReportTests(unittest.TestCase):
    def test_run_il2cpp_manual_findings_report_writes_manifest_and_summary_from_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            catalog_dir = _build_catalog_fixture(root)

            report_dir = run_il2cpp_manual_findings_report(
                catalog_path=catalog_dir,
                finding_paths=["DummyAssembly/PlayerData.cs"],
                finding_notes=["Likely player state class"],
                output_root=root / "artifacts",
            )

            self.assertTrue((report_dir / "manifest.json").is_file())
            self.assertTrue((report_dir / "summary.txt").is_file())

    def test_run_il2cpp_manual_findings_report_works_via_name_hint_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            catalog_dir = _build_catalog_fixture(root)
            name_hint_report_dir = _build_name_hint_report_fixture(root, catalog_dir)

            report_dir = run_il2cpp_manual_findings_report(
                name_hint_report_path=name_hint_report_dir,
                finding_paths=["DummyAssembly/RewardPanel.cs"],
                finding_notes=["Reward UI hook candidate"],
                output_root=root / "artifacts",
            )
            manifest = json.loads((report_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["source_name_hint_report_path"], str(name_hint_report_dir.resolve()))
            self.assertEqual(manifest["source_catalog_path"], str(catalog_dir.resolve()))

    def test_run_il2cpp_manual_findings_report_fails_when_path_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            catalog_dir = _build_catalog_fixture(root)

            with self.assertRaises(FileNotFoundError) as context:
                run_il2cpp_manual_findings_report(
                    catalog_path=catalog_dir,
                    finding_paths=["Missing/File.cs"],
                    finding_notes=["Nope"],
                    output_root=root / "artifacts",
                )

            self.assertIn("Finding path is not present", str(context.exception))

    def test_run_il2cpp_manual_findings_report_propagates_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            catalog_dir = _build_catalog_fixture(root)

            report_dir = run_il2cpp_manual_findings_report(
                catalog_path=catalog_dir,
                finding_paths=["DummyAssembly/PlayerData.cs"],
                finding_notes=["Likely player state class"],
                output_root=root / "artifacts",
            )
            manifest = json.loads((report_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(
                manifest["source_snapshot_path"],
                "C:\\dev\\ipm-bot\\data\\artifacts\\snapshots\\fixture_snapshot",
            )

    def test_run_il2cpp_manual_findings_report_persists_optional_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            catalog_dir = _build_catalog_fixture(root)

            report_dir = run_il2cpp_manual_findings_report(
                catalog_path=catalog_dir,
                finding_paths=["DummyAssembly/PlayerData.cs"],
                finding_notes=["Likely player state class"],
                finding_symbols=["PlayerData"],
                finding_kinds=["class"],
                analyst="lwpar",
                notes="manual review session 1",
                output_root=root / "artifacts",
            )
            manifest = json.loads((report_dir / "manifest.json").read_text(encoding="utf-8"))
            finding = manifest["findings"][0]

            self.assertEqual(manifest["analyst"], "lwpar")
            self.assertEqual(manifest["notes"], "manual review session 1")
            self.assertEqual(finding["finding_symbol"], "PlayerData")
            self.assertEqual(finding["finding_kind"], "class")


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
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return catalog_dir


def _build_name_hint_report_fixture(root: Path, catalog_dir: Path) -> Path:
    report_dir = root / "il2cpp_name_hint_reports" / "fixture_name_hint_report"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "summary.txt").write_text("fixture summary\n", encoding="utf-8")
    (report_dir / "manifest.json").write_text(
        json.dumps(
            {
                "command_name": "il2cpp-name-hint-report",
                "source_catalog_path": str(catalog_dir.resolve()),
                "source_snapshot_path": "C:\\dev\\ipm-bot\\data\\artifacts\\snapshots\\fixture_snapshot",
                "matching_entries": [
                    {
                        "relative_path": "DummyAssembly/RewardPanel.cs",
                        "matched_terms": ["reward"],
                        "size_bytes": 202,
                        "sha256": "sha-reward",
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return report_dir

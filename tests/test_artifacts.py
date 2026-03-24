from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.artifacts.diffing import run_diff
from ipm_bot.artifacts.apk_report import run_apk_report
from ipm_bot.artifacts.discovery import DiscoveryOptions, DiscoverySession, run_discovery
from ipm_bot.artifacts.shared import sha256_bytes


class ArtifactDiscoveryTests(unittest.TestCase):
    def test_run_diff_detects_hash_change_and_writes_text_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            before_dir = root / "before"
            after_dir = root / "after"
            before_dir.mkdir()
            after_dir.mkdir()

            before_payload = b'{"reward":"before"}\n'
            after_payload = b'{"reward":"after"}\n'
            before_copy = before_dir / "extracted" / "artifact.json"
            after_copy = after_dir / "extracted" / "artifact.json"
            before_copy.parent.mkdir(parents=True, exist_ok=True)
            after_copy.parent.mkdir(parents=True, exist_ok=True)
            before_copy.write_bytes(before_payload)
            after_copy.write_bytes(after_payload)

            inventory_row_before = {
                "artifact_key": "adb_private|/data/data/com.TironiumTech.IdlePlanetMiner/shared_prefs/reward.json",
                "collector_id": "private_run_as_data",
                "source_kind": "adb_private",
                "source_root": "/data/data/com.TironiumTech.IdlePlanetMiner",
                "source_path": "/data/data/com.TironiumTech.IdlePlanetMiner/shared_prefs/reward.json",
                "relative_path": "shared_prefs/reward.json",
                "entry_type": "file",
                "accessible": True,
                "extraction_method": "adb shell run-as",
                "size_bytes": len(before_payload),
                "mtime_epoch": 1,
                "mtime_utc": "2026-03-23T00:00:01Z",
                "sha256": sha256_bytes(before_payload),
                "extension": ".json",
                "file_class": "json_state_or_config",
                "text_like": True,
                "copy_status": "copied",
                "copied_relative_path": "extracted/artifact.json",
                "quick_text_preview": '{"reward":"before"}',
                "priority": "high",
                "priority_score": 82,
                "notes": ["shared_prefs_path"],
                "errors": [],
            }
            inventory_row_after = dict(inventory_row_before)
            inventory_row_after["size_bytes"] = len(after_payload)
            inventory_row_after["mtime_epoch"] = 2
            inventory_row_after["mtime_utc"] = "2026-03-23T00:00:02Z"
            inventory_row_after["sha256"] = sha256_bytes(after_payload)
            inventory_row_after["quick_text_preview"] = '{"reward":"after"}'

            (before_dir / "inventory.json").write_text(
                json.dumps([inventory_row_before], indent=2),
                encoding="utf-8",
            )
            (after_dir / "inventory.json").write_text(
                json.dumps([inventory_row_after], indent=2),
                encoding="utf-8",
            )

            diff_dir = run_diff(before_dir, after_dir, output_root=root / "output")

            summary = json.loads((diff_dir / "summary.json").read_text(encoding="utf-8"))
            changes = json.loads((diff_dir / "changes.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["modified_file_count"], 1)
            self.assertEqual(len(changes), 1)
            self.assertIn("hash_changed", changes[0]["reasons"])
            self.assertIsNotNone(changes[0]["text_diff_relative_path"])
            self.assertTrue((diff_dir / changes[0]["text_diff_relative_path"]).is_file())

    def test_run_discovery_writes_limitation_when_adb_preflight_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "artifacts"
            options = DiscoveryOptions(mode="snapshot", output_root=output_root)
            with patch.object(DiscoverySession, "_collect_host_metadata", autospec=True) as host_mock:
                host_mock.return_value = None
                with patch.object(DiscoverySession, "_collect_adb_environment", autospec=True) as adb_mock:
                    adb_mock.return_value = False
                    snapshot_dir = run_discovery(options)

            manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["artifact_count"], 0)
            self.assertTrue(manifest["limitations"])
            self.assertIn("ADB preflight failed", manifest["limitations"][0])

    def test_run_discovery_can_snapshot_one_host_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_file = root / "Player.log"
            source_file.write_text("line-one\nline-two\n", encoding="utf-8")
            output_root = root / "artifacts"
            options = DiscoveryOptions(mode="snapshot", output_root=output_root)

            def fake_host_collection(session: DiscoverySession) -> None:
                session._ingest_local_file(
                    collector_id="test_host_file",
                    source_kind="windows_host",
                    source_root=str(source_file.parent),
                    source_path=str(source_file),
                    relative_path=source_file.name,
                    extraction_method="host_read",
                )

            with patch.object(DiscoverySession, "_collect_host_metadata", autospec=True, side_effect=fake_host_collection):
                with patch.object(DiscoverySession, "_collect_adb_environment", autospec=True) as adb_mock:
                    adb_mock.return_value = False
                    snapshot_dir = run_discovery(options)

            inventory = json.loads((snapshot_dir / "inventory.json").read_text(encoding="utf-8"))
            self.assertEqual(len(inventory), 1)
            record = inventory[0]
            self.assertEqual(record["collector_id"], "test_host_file")
            self.assertEqual(record["source_kind"], "windows_host")
            self.assertEqual(record["copy_status"], "copied")
            copied_path = snapshot_dir / record["copied_relative_path"]
            self.assertTrue(copied_path.is_file())

    def test_run_apk_report_detects_il2cpp_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            apk_path = root / "base.apk"

            with zipfile.ZipFile(apk_path, "w") as archive:
                archive.writestr("lib/arm64-v8a/libil2cpp.so", b"fake-il2cpp")
                archive.writestr(
                    "assets/bin/Data/Managed/Metadata/global-metadata.dat",
                    b"fake-metadata",
                )
                archive.writestr("AndroidManifest.xml", b"manifest")

            report_dir = run_apk_report(apk_path, output_root=root / "reports")

            manifest = json.loads((report_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["il2cpp_detected"])
            interesting = json.loads((report_dir / "interesting_members.json").read_text(encoding="utf-8"))
            member_paths = {row["member_path"] for row in interesting}
            self.assertIn("lib/arm64-v8a/libil2cpp.so", member_paths)
            self.assertIn("assets/bin/Data/Managed/Metadata/global-metadata.dat", member_paths)
            extracted_member = (
                report_dir / "extracted_members" / "lib" / "arm64-v8a" / "libil2cpp.so"
            )
            self.assertTrue(extracted_member.is_file())

    def test_pull_and_inventory_apk_pulls_all_package_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            options = DiscoveryOptions(mode="snapshot", output_root=root / "artifacts", pull_apk=True)
            session = DiscoverySession(options)
            session._snapshot_dir.mkdir(parents=True, exist_ok=False)
            session._context_dir.mkdir(parents=True, exist_ok=True)
            session._reports_dir.mkdir(parents=True, exist_ok=True)

            class FakeRunner:
                def __init__(self) -> None:
                    self.commands: list[list[str]] = []

                def run(self, command: list[str], *, purpose: str):
                    self.commands.append(command)
                    destination = Path(command[-1])
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with zipfile.ZipFile(destination, "w") as archive:
                        archive.writestr("AndroidManifest.xml", b"manifest")
                    from ipm_bot.artifacts.discovery import CommandResult, CommandReceipt

                    receipt = CommandReceipt(
                        receipt_id="0001",
                        purpose=purpose,
                        command=command,
                        started_at_utc="2026-03-24T00:00:00Z",
                        finished_at_utc="2026-03-24T00:00:01Z",
                        returncode=0,
                    )
                    return CommandResult(receipt=receipt, stdout=b"", stderr=b"")

            fake_runner = FakeRunner()
            session._runner = fake_runner

            from ipm_bot.artifacts.discovery import CommandResult, CommandReceipt

            pm_path_result = CommandResult(
                receipt=CommandReceipt(
                    receipt_id="0000",
                    purpose="pm_path_package_for_apk_pull",
                    command=[],
                    started_at_utc="2026-03-24T00:00:00Z",
                    finished_at_utc="2026-03-24T00:00:00Z",
                    returncode=0,
                ),
                stdout=(
                    b"package:/data/app/example/base.apk\n"
                    b"package:/data/app/example/split_config.arm64_v8a.apk\n"
                ),
                stderr=b"",
            )

            with patch.object(session, "_run_adb_shell", return_value=pm_path_result):
                session._pull_and_inventory_apk()

            pulled_targets = [Path(command[-1]).name for command in fake_runner.commands]
            self.assertEqual(pulled_targets, ["base.apk", "split_config.arm64_v8a.apk"])
            context_labels = {item.label for item in session._context_files}
            self.assertIn("installed_base_apk", context_labels)
            self.assertIn("installed_split_config.arm64_v8a.apk", context_labels)


if __name__ == "__main__":
    unittest.main()

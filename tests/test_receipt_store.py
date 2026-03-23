from __future__ import annotations

from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.actuator.runner import (
    ActionAttemptReceipt,
    FailureReason,
    ReceiptRuntimeContext,
)
from ipm_bot.actuator.boundary import (
    ActuatorConfigSnapshot,
    ActuatorExecutionMetadata,
)
from ipm_bot.control.contracts import get_action_contract
from ipm_bot.control.receipt_schema import CURRENT_RECEIPT_SCHEMA_VERSION
from ipm_bot.control.receipt_store import write_receipt
from ipm_bot.control.save_source import SaveSourceConfigSnapshot, SaveSourceMetadata
from ipm_bot.main import main
from ipm_bot.planner.planner import PlannerDecision


class ReceiptStoreTests(unittest.TestCase):
    def test_write_receipt_creates_directory_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "nested" / "receipts"
            receipt = _sample_receipt()

            written_path = write_receipt(
                receipt,
                output_dir=output_dir,
                written_at=datetime(2026, 3, 22, 14, 31, 5, tzinfo=timezone.utc),
            )

            self.assertTrue(output_dir.is_dir())
            self.assertTrue(written_path.is_file())
            self.assertEqual(
                written_path.name,
                "2026-03-22T14-31-05Z_activate_ad_boost.json",
            )

            payload = json.loads(written_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["action"], receipt.action)
            self.assertEqual(payload["baseline_hash"], receipt.baseline_hash)
            self.assertEqual(payload["prepared_save_hash"], receipt.baseline_hash)
            self.assertEqual(payload["final_status"], receipt.final_status)
            self.assertEqual(payload["failure_reason"], receipt.failure_reason)
            self.assertEqual(payload["elapsed_seconds"], receipt.elapsed_seconds)
            self.assertEqual(payload["changed_save_count"], receipt.changed_save_count)
            self.assertEqual(payload["candidate_hashes"], receipt.candidate_hashes)
            self.assertEqual(payload["save_path"], receipt.save_path)
            self.assertEqual(payload["final_candidate_hash"], receipt.final_candidate_hash)
            self.assertEqual(
                payload["receipt_written_at_utc"],
                "2026-03-22T14-31-05Z",
            )
            self.assertEqual(
                payload["contract_identity"]["action"],
                receipt.contract_identity.action,
            )
            self.assertEqual(
                payload["contract_identity"]["required_expected_values"],
                receipt.contract_identity.required_expected_values,
            )
            self.assertEqual(
                payload["runtime_context"]["receipt_schema_version"],
                receipt.runtime_context.receipt_schema_version,
            )
            self.assertEqual(
                payload["runtime_context"]["poll_interval_seconds"],
                receipt.runtime_context.poll_interval_seconds,
            )
            self.assertEqual(
                payload["runtime_context"]["timeout_seconds"],
                receipt.runtime_context.timeout_seconds,
            )
            self.assertEqual(
                payload["runtime_context"]["exit_code"],
                receipt.runtime_context.exit_code,
            )
            self.assertEqual(
                payload["actuator_execution"]["actuator_type"],
                receipt.actuator_execution.actuator_type,
            )
            self.assertEqual(
                payload["actuator_execution"]["actuator_execution_status"],
                receipt.actuator_execution.actuator_execution_status,
            )
            self.assertEqual(
                payload["actuator_execution"]["actuator_command_count"],
                receipt.actuator_execution.actuator_command_count,
            )
            self.assertEqual(
                payload["actuator_execution"]["actuator_command_summary"],
                receipt.actuator_execution.actuator_command_summary,
            )
            self.assertEqual(
                payload["actuator_config"]["actuator_type"],
                receipt.actuator_config_snapshot.actuator_type,
            )
            self.assertEqual(
                payload["planner_decision"]["selected_action"],
                receipt.planner_decision.selected_action,
            )
            self.assertEqual(
                payload["planner_decision"]["decision_reason"],
                receipt.planner_decision.decision_reason,
            )
            self.assertEqual(
                payload["planner_decision"]["actuation_required"],
                receipt.planner_decision.actuation_required,
            )
            self.assertEqual(
                payload["actuation_attempted"],
                receipt.actuation_attempted,
            )
            self.assertEqual(
                payload["save_source"]["save_source_type"],
                receipt.save_source_metadata.save_source_type,
            )
            self.assertEqual(
                payload["save_source"]["original_requested_path"],
                receipt.save_source_metadata.original_requested_path,
            )
            self.assertEqual(
                payload["save_source"]["prepared_local_path"],
                receipt.save_source_metadata.prepared_local_path,
            )
            self.assertEqual(
                payload["save_source"]["preparation_performed"],
                receipt.save_source_metadata.preparation_performed,
            )
            self.assertEqual(
                payload["save_source"]["local_source_path"],
                receipt.save_source_metadata.config_snapshot.local_source_path,
            )
            self.assertEqual(payload["verifier_messages"], receipt.verifier_messages)

    def test_write_receipt_includes_explicit_vhdx_and_actuator_config_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "receipts"
            receipt = _sample_receipt(save_source_kind="vhdx", actuator_kind="adb")

            written_path = write_receipt(
                receipt,
                output_dir=output_dir,
                written_at=datetime(2026, 3, 22, 14, 31, 5, tzinfo=timezone.utc),
            )

            payload = json.loads(written_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["save_source"]["save_source_type"], "vhdx")
            self.assertEqual(
                payload["save_source"]["vhdx_path"],
                receipt.save_source_metadata.config_snapshot.vhdx_path,
            )
            self.assertEqual(
                payload["save_source"]["vhdx_member_name"],
                receipt.save_source_metadata.config_snapshot.vhdx_member_name,
            )
            self.assertEqual(
                payload["save_source"]["seven_zip_path"],
                receipt.save_source_metadata.config_snapshot.seven_zip_path,
            )
            self.assertEqual(payload["actuator_config"]["actuator_type"], "adb")
            self.assertEqual(
                payload["actuator_config"]["adb_path"],
                receipt.actuator_config_snapshot.adb_path,
            )
            self.assertEqual(
                payload["actuator_config"]["adb_serial"],
                receipt.actuator_config_snapshot.adb_serial,
            )
            self.assertEqual(
                payload["actuator_config"]["app_package"],
                receipt.actuator_config_snapshot.app_package,
            )
            self.assertEqual(
                payload["actuator_config"]["app_activity"],
                receipt.actuator_config_snapshot.app_activity,
            )

    def test_write_receipt_includes_explicit_adb_pull_save_source_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "receipts"
            receipt = _sample_receipt(save_source_kind="adb_pull")

            written_path = write_receipt(
                receipt,
                output_dir=output_dir,
                written_at=datetime(2026, 3, 22, 14, 31, 5, tzinfo=timezone.utc),
            )

            payload = json.loads(written_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["save_source"]["save_source_type"], "adb_pull")
            self.assertEqual(
                payload["save_source"]["adb_path"],
                receipt.save_source_metadata.config_snapshot.adb_path,
            )
            self.assertEqual(
                payload["save_source"]["adb_serial"],
                receipt.save_source_metadata.config_snapshot.adb_serial,
            )
            self.assertEqual(
                payload["save_source"]["remote_save_path"],
                receipt.save_source_metadata.config_snapshot.remote_save_path,
            )

    def test_main_writes_receipt_and_prints_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_tmp = Path(tmpdir)
            save_path = repo_tmp / "save.json"
            save_path.write_text(
                json.dumps(
                    {
                        "adBoostActive": False,
                        "adsWatched": 1,
                        "saveTimestamp": "2026-03-22T14:31:05",
                        "arkRewardReadyToClaim": False,
                        "playerLevel": 5,
                    }
                ),
                encoding="utf-8",
            )
            output_dir = repo_tmp / "logs" / "receipts"
            receipt = _sample_receipt()
            stdout = io.StringIO()

            def _write_to_temp(receipt_to_write: ActionAttemptReceipt) -> Path:
                return write_receipt(
                    receipt_to_write,
                    output_dir=output_dir,
                    written_at=datetime(2026, 3, 22, 14, 31, 5, tzinfo=timezone.utc),
                )

            with (
                patch("sys.argv", ["ipm_bot.main", str(save_path)]),
                patch("sys.stdout", stdout),
                patch("ipm_bot.main.run_action_until_verified", return_value=receipt),
                patch("ipm_bot.main.write_receipt", side_effect=_write_to_temp),
            ):
                exit_code = main()

            written_files = list(output_dir.glob("*.json"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(len(written_files), 1)
            self.assertIn("Receipt path:", stdout.getvalue())
            self.assertIn(str(written_files[0]), stdout.getvalue())


def _sample_receipt(
    *,
    save_source_kind: str = "local",
    actuator_kind: str = "stub",
) -> ActionAttemptReceipt:
    contract = get_action_contract("activate_ad_boost")
    actuator_config_snapshot = ActuatorConfigSnapshot(actuator_type="stub")
    actuator_execution = ActuatorExecutionMetadata(
        actuator_type="stub",
        actuator_execution_status="COMPLETED",
        actuator_command_count=1,
        actuator_command_summary=["stub:activate_ad_boost"],
    )
    if actuator_kind == "adb":
        actuator_config_snapshot = ActuatorConfigSnapshot(
            actuator_type="adb",
            adb_path="adb",
            adb_serial="emulator-5554",
            app_package="com.TironiumTech.IdlePlanetMiner",
            app_activity="com.unity3d.player.UnityPlayerActivity",
        )
        actuator_execution = ActuatorExecutionMetadata(
            actuator_type="adb",
            actuator_execution_status="COMPLETED",
            actuator_command_count=2,
            actuator_command_summary=["adb shell am start -n ...", "adb shell input tap 852 311"],
        )

    save_source_metadata = SaveSourceMetadata(
        save_source_type="local",
        original_requested_path="C:\\dev\\ipm-bot\\data\\save.json",
        prepared_local_path=str((Path("C:/dev/ipm-bot/data/save.json")).resolve()),
        preparation_performed=False,
        config_snapshot=SaveSourceConfigSnapshot(
            save_source_type="local",
            preparation_performed=False,
            prepared_local_path=str((Path("C:/dev/ipm-bot/data/save.json")).resolve()),
            original_requested_path="C:\\dev\\ipm-bot\\data\\save.json",
            local_source_path=str((Path("C:/dev/ipm-bot/data/save.json")).resolve()),
        ),
    )
    if save_source_kind == "adb_pull":
        save_source_metadata = SaveSourceMetadata(
            save_source_type="adb_pull",
            original_requested_path="/sdcard/Android/data/com.TironiumTech.IdlePlanetMiner/files/playerInfo.dat",
            prepared_local_path=str((Path("C:/dev/ipm-bot/data/pulled/playerInfo.dat")).resolve()),
            preparation_performed=True,
            config_snapshot=SaveSourceConfigSnapshot(
                save_source_type="adb_pull",
                preparation_performed=True,
                prepared_local_path=str((Path("C:/dev/ipm-bot/data/pulled/playerInfo.dat")).resolve()),
                original_requested_path="/sdcard/Android/data/com.TironiumTech.IdlePlanetMiner/files/playerInfo.dat",
                adb_path="adb",
                adb_serial="emulator-5554",
                remote_save_path="/sdcard/Android/data/com.TironiumTech.IdlePlanetMiner/files/playerInfo.dat",
            ),
        )
    elif save_source_kind == "vhdx":
        save_source_metadata = SaveSourceMetadata(
            save_source_type="vhdx",
            original_requested_path=(
                "C:\\ProgramData\\BlueStacks_nxt\\Engine\\Pie64\\Data.vhdx::"
                "media\\0\\Android\\data\\com.TironiumTech.IdlePlanetMiner\\files\\playerInfo.dat"
            ),
            prepared_local_path=str((Path("C:/dev/ipm-bot/data/runs/current/playerInfo.dat")).resolve()),
            preparation_performed=True,
            config_snapshot=SaveSourceConfigSnapshot(
                save_source_type="vhdx",
                preparation_performed=True,
                prepared_local_path=str((Path("C:/dev/ipm-bot/data/runs/current/playerInfo.dat")).resolve()),
                original_requested_path=(
                    "C:\\ProgramData\\BlueStacks_nxt\\Engine\\Pie64\\Data.vhdx::"
                    "media\\0\\Android\\data\\com.TironiumTech.IdlePlanetMiner\\files\\playerInfo.dat"
                ),
                vhdx_path="C:\\ProgramData\\BlueStacks_nxt\\Engine\\Pie64\\Data.vhdx",
                vhdx_member_name="playerInfo.dat",
                seven_zip_path="C:\\Program Files\\AMD\\CIM\\Bin64\\7z.exe",
            ),
        )

    return ActionAttemptReceipt(
        action="activate_ad_boost",
        save_path=str((Path("C:/dev/ipm-bot/data/save.json")).resolve()),
        baseline_hash="abc123",
        final_status="PASS",
        failure_reason=FailureReason.NONE,
        elapsed_seconds=1.25,
        changed_save_count=1,
        candidate_hashes=["def456"],
        final_candidate_hash="def456",
        contract_identity=contract.identity("activate_ad_boost"),
        runtime_context=ReceiptRuntimeContext(
            receipt_schema_version=CURRENT_RECEIPT_SCHEMA_VERSION,
            poll_interval_seconds=0.5,
            timeout_seconds=30.0,
            exit_code=0,
        ),
        actuator_execution=actuator_execution,
        actuator_config_snapshot=actuator_config_snapshot,
        verifier_messages=["Field 'ad_boost_active' matched the expected value: value=True."],
        planner_decision=PlannerDecision(
            selected_action="activate_ad_boost",
            decision_reason="ad_boost_inactive",
            actuation_required=True,
        ),
        actuation_attempted=True,
        save_source_metadata=save_source_metadata,
    )


if __name__ == "__main__":
    unittest.main()

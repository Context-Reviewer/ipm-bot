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
    ActuatorProbeSample,
    ActuatorStageEvent,
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
                payload["runtime_context"]["timeout_scope"],
                receipt.runtime_context.timeout_scope,
            )
            self.assertEqual(
                payload["runtime_context"]["save_snapshot_available"],
                receipt.runtime_context.save_snapshot_available,
            )
            self.assertEqual(
                payload["runtime_context"]["active_smelters"],
                receipt.runtime_context.active_smelters,
            )
            self.assertEqual(
                payload["runtime_context"]["active_crafters"],
                receipt.runtime_context.active_crafters,
            )
            self.assertEqual(
                payload["runtime_context"]["nearest_completion_seconds"],
                receipt.runtime_context.nearest_completion_seconds,
            )
            self.assertEqual(
                payload["runtime_context"]["exit_code"],
                receipt.runtime_context.exit_code,
            )
            self.assertEqual(
                payload["runtime_context"]["action_override_used"],
                receipt.runtime_context.action_override_used,
            )
            self.assertEqual(
                payload["runtime_context"]["action_override_requested_action"],
                receipt.runtime_context.action_override_requested_action,
            )
            self.assertEqual(
                payload["runtime_context"]["save_repull_interval_seconds"],
                receipt.runtime_context.save_repull_interval_seconds,
            )
            self.assertEqual(
                payload["runtime_context"]["save_repull_count"],
                receipt.runtime_context.save_repull_count,
            )
            self.assertEqual(
                payload["runtime_context"]["save_repull_failure_count"],
                receipt.runtime_context.save_repull_failure_count,
            )
            self.assertEqual(
                payload["runtime_context"]["actuation_elapsed_seconds"],
                receipt.runtime_context.actuation_elapsed_seconds,
            )
            self.assertEqual(
                payload["runtime_context"]["verification_elapsed_seconds"],
                receipt.runtime_context.verification_elapsed_seconds,
            )
            self.assertEqual(
                payload["runtime_context"]["verification_started"],
                receipt.runtime_context.verification_started,
            )
            self.assertEqual(
                payload["runtime_context"]["verification_starved_by_timeout"],
                receipt.runtime_context.verification_starved_by_timeout,
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
                payload["actuator_execution"]["stage_events"],
                [],
            )
            self.assertEqual(
                payload["actuator_execution"]["probe_samples"],
                [],
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
            self.assertEqual(
                payload["actuator_config"]["ark_ad_wait_seconds"],
                receipt.actuator_config_snapshot.ark_ad_wait_seconds,
            )
            self.assertEqual(
                payload["actuator_config"]["ark_skip_close_wait_seconds"],
                receipt.actuator_config_snapshot.ark_skip_close_wait_seconds,
            )
            self.assertEqual(
                payload["actuator_config"]["ark_return_wait_seconds"],
                receipt.actuator_config_snapshot.ark_return_wait_seconds,
            )
            self.assertEqual(
                payload["actuator_config"]["ark_esc_attempts"],
                receipt.actuator_config_snapshot.ark_esc_attempts,
            )
            self.assertEqual(
                payload["actuator_config"]["ark_esc_interval_seconds"],
                receipt.actuator_config_snapshot.ark_esc_interval_seconds,
            )
            self.assertEqual(
                payload["actuator_config"]["ark_post_watch_probe_count"],
                receipt.actuator_config_snapshot.ark_post_watch_probe_count,
            )
            self.assertEqual(
                payload["actuator_config"]["ark_post_watch_probe_interval_seconds"],
                receipt.actuator_config_snapshot.ark_post_watch_probe_interval_seconds,
            )
            self.assertEqual(
                payload["actuator_config"]["ark_post_watch_ui_dump_max_text_length"],
                receipt.actuator_config_snapshot.ark_post_watch_ui_dump_max_text_length,
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

    def test_write_receipt_marks_manual_observation_mode_and_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "receipts"
            receipt = _sample_receipt(
                actuator_kind="adb",
                with_observability=True,
                manual_observation=True,
            )

            written_path = write_receipt(
                receipt,
                output_dir=output_dir,
                written_at=datetime(2026, 3, 22, 14, 31, 5, tzinfo=timezone.utc),
            )

            payload = json.loads(written_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["runtime_context"]["manual_observation_mode"])
            self.assertTrue(payload["actuator_config"]["manual_observation_mode"])
            self.assertEqual(
                payload["actuator_config"]["manual_observation_window_seconds"],
                20.0,
            )
            self.assertEqual(
                payload["actuator_config"]["manual_observation_probe_interval_seconds"],
                1.0,
            )
            self.assertEqual(
                payload["actuator_execution"]["probe_samples"][0]["sample_context"],
                "manual_observation",
            )
            self.assertEqual(
                payload["actuator_execution"]["probe_samples"][0]["sample_reference_stage"],
                "manual_observation_start",
            )
            artifact_paths = payload["actuator_execution"]["probe_samples"][0]["artifact_paths"]
            self.assertTrue(Path(artifact_paths["dumpsys_window_path"]).is_file())
            self.assertTrue(Path(artifact_paths["dumpsys_activity_path"]).is_file())
            self.assertTrue(Path(artifact_paths["ui_dump_xml_path"]).is_file())

    def test_write_receipt_persists_stage_events_probe_samples_and_raw_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "receipts"
            receipt = _sample_receipt(
                actuator_kind="adb",
                with_observability=True,
            )

            written_path = write_receipt(
                receipt,
                output_dir=output_dir,
                written_at=datetime(2026, 3, 22, 14, 31, 5, tzinfo=timezone.utc),
            )

            payload = json.loads(written_path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["actuator_execution"]["stage_events"][0]["stage_name"],
                "ark_watch_tap",
            )
            self.assertEqual(
                payload["actuator_execution"]["probe_samples"][0]["focus_package"],
                "com.google.android.gms",
            )
            self.assertEqual(
                payload["actuator_execution"]["probe_samples"][0]["sample_context"],
                "pre_esc",
            )
            self.assertEqual(
                payload["actuator_execution"]["probe_samples"][0]["sample_reference_stage"],
                "ark_watch_tap",
            )
            self.assertEqual(
                payload["actuator_execution"]["probe_samples"][0]["esc_attempt_index"],
                1,
            )
            self.assertEqual(
                payload["actuator_execution"]["probe_samples"][0]["ui_text_excerpt"],
                "Reward granted | Close ad",
            )
            artifact_paths = payload["actuator_execution"]["probe_samples"][0]["artifact_paths"]
            dumpsys_window_path = Path(artifact_paths["dumpsys_window_path"])
            dumpsys_activity_path = Path(artifact_paths["dumpsys_activity_path"])
            ui_dump_xml_path = Path(artifact_paths["ui_dump_xml_path"])
            self.assertTrue(dumpsys_window_path.is_file())
            self.assertTrue(dumpsys_activity_path.is_file())
            self.assertTrue(ui_dump_xml_path.is_file())
            self.assertIn("pre_esc_attempt_1", dumpsys_window_path.name)
            self.assertEqual(
                dumpsys_window_path.read_text(encoding="utf-8"),
                receipt.actuator_execution.probe_samples[0].dumpsys_window_output,
            )
            self.assertEqual(
                dumpsys_activity_path.read_text(encoding="utf-8"),
                receipt.actuator_execution.probe_samples[0].dumpsys_activity_output,
            )
            self.assertEqual(
                ui_dump_xml_path.read_text(encoding="utf-8"),
                receipt.actuator_execution.probe_samples[0].ui_dump_xml,
            )

    def test_write_receipt_leaves_missing_probe_artifact_paths_null_when_source_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "receipts"
            receipt = _sample_receipt(
                actuator_kind="adb",
                with_observability=True,
                missing_ui_dump=True,
            )

            written_path = write_receipt(
                receipt,
                output_dir=output_dir,
                written_at=datetime(2026, 3, 22, 14, 31, 5, tzinfo=timezone.utc),
            )

            payload = json.loads(written_path.read_text(encoding="utf-8"))
            artifact_paths = payload["actuator_execution"]["probe_samples"][0]["artifact_paths"]
            self.assertIsNotNone(artifact_paths["dumpsys_window_path"])
            self.assertIsNotNone(artifact_paths["dumpsys_activity_path"])
            self.assertIsNone(artifact_paths["ui_dump_xml_path"])
            self.assertIn("ui:", payload["actuator_execution"]["probe_samples"][0]["probe_error"])

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
    with_observability: bool = False,
    missing_ui_dump: bool = False,
    manual_observation: bool = False,
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
            manual_observation_mode=manual_observation,
            manual_observation_window_seconds=20.0,
            manual_observation_probe_interval_seconds=1.0,
            ark_ad_wait_seconds=20.0,
            ark_skip_close_wait_seconds=1.0,
            ark_return_wait_seconds=3.0,
            ark_esc_attempts=2,
            ark_esc_interval_seconds=1.25,
            ark_post_watch_probe_count=2,
            ark_post_watch_probe_interval_seconds=2.0,
            ark_post_watch_ui_dump_max_text_length=240,
        )
        actuator_execution = ActuatorExecutionMetadata(
            actuator_type="adb",
            actuator_execution_status="COMPLETED",
            actuator_command_count=2,
            actuator_command_summary=["adb shell am start -n ...", "adb shell input tap 852 311"],
        )
        if with_observability:
            actuator_execution = ActuatorExecutionMetadata(
                actuator_type="adb",
                actuator_execution_status="COMPLETED",
                actuator_command_count=2,
                actuator_command_summary=["adb shell am start -n ...", "adb shell input tap 852 311"],
                stage_events=[
                    ActuatorStageEvent(
                        stage_name=(
                            "manual_observation_start" if manual_observation else "ark_watch_tap"
                        ),
                        wall_clock_utc="2026-03-22T14:31:05Z",
                        elapsed_seconds=0.0,
                    )
                ],
                probe_samples=[
                    ActuatorProbeSample(
                        sample_offset_seconds=2.0,
                        sample_context=("manual_observation" if manual_observation else "pre_esc"),
                        sample_reference_stage=(
                            "manual_observation_start" if manual_observation else "ark_watch_tap"
                        ),
                        esc_attempt_index=(None if manual_observation else 1),
                        focus_package="com.google.android.gms",
                        focus_activity="com.google.android.gms.ads.AdActivity",
                        ui_text_excerpt="Reward granted | Close ad",
                        ui_text_sha256="abc123def456",
                        probe_error=("ui:uiautomator unavailable" if missing_ui_dump else None),
                        dumpsys_window_output=(
                            "mCurrentFocus=Window{42 u0 "
                            "com.google.android.gms/com.google.android.gms.ads.AdActivity}"
                        ),
                        dumpsys_activity_output="ACTIVITY MANAGER ACTIVITIES",
                        ui_dump_xml=(
                            None
                            if missing_ui_dump
                            else (
                                "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
                                "<hierarchy><node text=\"Reward granted\" content-desc=\"Close ad\" /></hierarchy>"
                            )
                        ),
                    )
                ],
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
            timeout_scope="verification_only_after_actuation",
            manual_observation_mode=manual_observation,
            save_snapshot_available=True,
            active_smelters=4,
            active_crafters=1,
            nearest_completion_seconds=6.324,
            exit_code=0,
            actuation_elapsed_seconds=12.5,
            verification_elapsed_seconds=4.25,
            verification_started=True,
            verification_starved_by_timeout=False,
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

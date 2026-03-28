from __future__ import annotations

from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.actuator.boundary import ActuatorConfigSnapshot, ActuatorExecutionMetadata
from ipm_bot.actuator.runner import ActionAttemptReceipt, FailureReason, ReceiptRuntimeContext
from ipm_bot.control.contracts import get_action_contract
from ipm_bot.control.experiment_store import write_experiment_manifest
from ipm_bot.control.receipt_schema import CURRENT_RECEIPT_SCHEMA_VERSION
from ipm_bot.control.receipt_store import write_receipt
from ipm_bot.control.save_source import LocalSaveSource, SaveSourceConfigSnapshot, SaveSourceMetadata
from ipm_bot.experiment.runner import main
from ipm_bot.main import ExitCode, run_single_control_tick
from ipm_bot.planner.planner import PlannerDecision


class ExperimentHarnessTests(unittest.TestCase):
    def test_experiment_run_writes_one_manifest_and_points_to_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            receipt_path = temp_root / "logs" / "receipts" / "receipt.json"
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text("{}", encoding="utf-8")
            manifest_dir = temp_root / "logs" / "experiments"
            sample_receipt = _sample_receipt(final_status="PASS", failure_reason=FailureReason.NONE)
            stdout = io.StringIO()

            def _write_manifest_to_temp(manifest):
                return write_experiment_manifest(manifest, output_dir=manifest_dir)

            with (
                patch("sys.stdout", stdout),
                patch(
                    "ipm_bot.experiment.runner.run_single_control_tick",
                    return_value=("activate_ad_boost", sample_receipt, receipt_path),
                ),
                patch(
                    "ipm_bot.experiment.runner.write_experiment_manifest",
                    side_effect=_write_manifest_to_temp,
                ),
            ):
                exit_code = main([str(temp_root / "save.json")])

            manifest_files = list(manifest_dir.glob("*.json"))
            self.assertEqual(exit_code, int(ExitCode.PASS))
            self.assertEqual(len(manifest_files), 1)
            payload = json.loads(manifest_files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["receipt_path"], str(receipt_path))
            self.assertEqual(payload["actuator_type"], "stub")
            self.assertEqual(payload["save_source_type"], "local")
            self.assertEqual(payload["selected_action"], "activate_ad_boost")
            self.assertEqual(payload["final_status"], "PASS")
            self.assertEqual(payload["failure_reason"], "NONE")
            self.assertIn("Experiment ID:", stdout.getvalue())
            self.assertIn(str(receipt_path), stdout.getvalue())
            self.assertIn(str(manifest_files[0]), stdout.getvalue())

    def test_experiment_exit_code_matches_control_tick_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            receipt_path = temp_root / "logs" / "receipts" / "receipt.json"
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text("{}", encoding="utf-8")
            manifest_dir = temp_root / "logs" / "experiments"
            sample_receipt = _sample_receipt(
                final_status="AMBIGUOUS",
                failure_reason=FailureReason.AMBIGUOUS_TRANSITION,
                exit_code=int(ExitCode.AMBIGUOUS),
            )
            stdout = io.StringIO()

            def _write_manifest_to_temp(manifest):
                return write_experiment_manifest(manifest, output_dir=manifest_dir)

            with (
                patch("sys.stdout", stdout),
                patch(
                    "ipm_bot.experiment.runner.run_single_control_tick",
                    return_value=("claim_ark_reward", sample_receipt, receipt_path),
                ),
                patch(
                    "ipm_bot.experiment.runner.write_experiment_manifest",
                    side_effect=_write_manifest_to_temp,
                ),
            ):
                exit_code = main([str(temp_root / "save.json")])

            manifest_files = list(manifest_dir.glob("*.json"))
            payload = json.loads(manifest_files[0].read_text(encoding="utf-8"))
            self.assertEqual(exit_code, int(ExitCode.AMBIGUOUS))
            self.assertEqual(payload["exit_code"], int(ExitCode.AMBIGUOUS))

    def test_run_single_control_tick_honors_experiment_action_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            save_path = root / "save.json"
            save_path.write_text(
                json.dumps(
                    {
                        "adBoostActive": False,
                        "adsWatched": 1,
                        "saveTimestamp": "2026-03-22T14:31:05",
                        "arkRewardReadyToClaim": True,
                        "playerLevel": 5,
                    }
                ),
                encoding="utf-8",
            )
            output_dir = root / "logs" / "receipts"
            actuator = RecordingActuator()

            def _delayed_update() -> None:
                time.sleep(0.1)
                save_path.write_text(
                    json.dumps(
                        {
                            "adBoostActive": False,
                            "adsWatched": 1,
                            "saveTimestamp": "2026-03-22T14:31:15",
                            "arkRewardReadyToClaim": False,
                            "playerLevel": 5,
                        }
                    ),
                    encoding="utf-8",
                )

            updater = threading.Thread(target=_delayed_update)
            updater.start()

            def _write_to_temp(receipt_to_write: ActionAttemptReceipt) -> Path:
                return write_receipt(
                    receipt_to_write,
                    output_dir=output_dir,
                    written_at=datetime(2026, 3, 22, 14, 31, 5, tzinfo=timezone.utc),
                )

            with patch("ipm_bot.main.write_receipt", side_effect=_write_to_temp):
                action, receipt, _ = run_single_control_tick(
                    save_path=save_path,
                    timeout_seconds=1.0,
                    poll_interval_seconds=0.05,
                    actuator=actuator,
                    save_source=LocalSaveSource(),
                    action_override="claim_ark_reward",
                )

            updater.join()

            self.assertEqual(action, "claim_ark_reward")
            self.assertEqual(actuator.actions, ["claim_ark_reward"])
            self.assertEqual(receipt.planner_decision.selected_action, "claim_ark_reward")
            self.assertEqual(receipt.planner_decision.decision_reason, "experiment_action_override")
            self.assertTrue(receipt.runtime_context.action_override_used)
            self.assertEqual(receipt.runtime_context.action_override_requested_action, "claim_ark_reward")

    def test_run_single_control_tick_marks_manual_observation_mode_in_runtime_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            save_path = root / "save.json"
            save_path.write_text(
                json.dumps(
                    {
                        "adBoostActive": False,
                        "adsWatched": 1,
                        "saveTimestamp": "2026-03-22T14:31:05",
                        "arkRewardReadyToClaim": True,
                        "playerLevel": 5,
                    }
                ),
                encoding="utf-8",
            )
            output_dir = root / "logs" / "receipts"
            actuator = RecordingActuator()

            def _delayed_update() -> None:
                time.sleep(0.1)
                save_path.write_text(
                    json.dumps(
                        {
                            "adBoostActive": False,
                            "adsWatched": 1,
                            "saveTimestamp": "2026-03-22T14:31:15",
                            "arkRewardReadyToClaim": False,
                            "playerLevel": 5,
                        }
                    ),
                    encoding="utf-8",
                )

            updater = threading.Thread(target=_delayed_update)
            updater.start()

            def _write_to_temp(receipt_to_write: ActionAttemptReceipt) -> Path:
                return write_receipt(
                    receipt_to_write,
                    output_dir=output_dir,
                    written_at=datetime(2026, 3, 22, 14, 31, 5, tzinfo=timezone.utc),
                )

            with patch("ipm_bot.main.write_receipt", side_effect=_write_to_temp):
                action, receipt, _ = run_single_control_tick(
                    save_path=save_path,
                    timeout_seconds=1.0,
                    poll_interval_seconds=0.05,
                    actuator=actuator,
                    save_source=LocalSaveSource(),
                    action_override="claim_ark_reward",
                    manual_observation_mode=True,
                )

            updater.join()

            self.assertEqual(action, "claim_ark_reward")
            self.assertTrue(receipt.runtime_context.manual_observation_mode)
            self.assertTrue(receipt.runtime_context.action_override_used)
            self.assertEqual(receipt.runtime_context.action_override_requested_action, "claim_ark_reward")


def _sample_receipt(
    *,
    final_status: str,
    failure_reason: FailureReason,
    exit_code: int = int(ExitCode.PASS),
) -> ActionAttemptReceipt:
    action = "activate_ad_boost" if final_status == "PASS" else "claim_ark_reward"
    contract = get_action_contract(action)
    decision_reason = "ad_boost_inactive" if action == "activate_ad_boost" else "ark_reward_ready_to_claim"
    return ActionAttemptReceipt(
        action=action,
        save_path=str((Path("C:/dev/ipm-bot/data/save.json")).resolve()),
        baseline_hash="abc123",
        final_status=final_status,
        failure_reason=failure_reason,
        elapsed_seconds=1.25,
        changed_save_count=1,
        candidate_hashes=["def456"],
        final_candidate_hash="def456",
        contract_identity=contract.identity(action),
        runtime_context=ReceiptRuntimeContext(
            receipt_schema_version=CURRENT_RECEIPT_SCHEMA_VERSION,
            poll_interval_seconds=0.5,
            timeout_seconds=30.0,
            exit_code=exit_code,
        ),
        actuator_execution=ActuatorExecutionMetadata(
            actuator_type="stub",
            actuator_execution_status="COMPLETED",
            actuator_command_count=1,
            actuator_command_summary=[f"stub:{action}"],
        ),
        actuator_config_snapshot=ActuatorConfigSnapshot(actuator_type="stub"),
        verifier_messages=["verification message"],
        resulting_save_hashes=["def456"],
        planner_decision=PlannerDecision(
            selected_action=action,
            decision_reason=decision_reason,
            actuation_required=True,
        ),
        actuation_attempted=True,
        save_source_metadata=SaveSourceMetadata(
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
        ),
    )

class RecordingActuator:
    actuator_type = "recording"
    config_snapshot = ActuatorConfigSnapshot(actuator_type="recording")

    def __init__(self) -> None:
        self.actions: list[str] = []

    def execute(self, action: str) -> ActuatorExecutionMetadata:
        self.actions.append(action)
        return ActuatorExecutionMetadata(
            actuator_type=self.actuator_type,
            actuator_execution_status="COMPLETED",
            actuator_command_count=1,
            actuator_command_summary=[f"recording:{action}"],
        )


if __name__ == "__main__":
    unittest.main()

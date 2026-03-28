"""Persistent storage for action attempt receipts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ipm_bot.actuator.runner import ActionAttemptReceipt


DEFAULT_RECEIPT_DIRECTORY = Path(__file__).resolve().parents[3] / "logs" / "receipts"


def write_receipt(
    receipt: ActionAttemptReceipt,
    output_dir: Path | None = None,
    written_at: datetime | None = None,
) -> Path:
    """Persist one action attempt receipt as a JSON file and return its path."""

    directory = DEFAULT_RECEIPT_DIRECTORY if output_dir is None else output_dir
    directory.mkdir(parents=True, exist_ok=True)

    timestamp = _normalize_timestamp(
        datetime.now(timezone.utc) if written_at is None else written_at
    )
    receipt_path = _next_available_path(
        directory=directory,
        timestamp=timestamp,
        action=_sanitize_action_name(receipt.action),
    )
    artifact_directory = _artifact_directory_for_receipt(receipt_path)
    receipt_path.write_text(
        json.dumps(
            _serialize_receipt(
                receipt,
                receipt_written_at_utc=timestamp,
                artifact_directory=artifact_directory,
            ),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return receipt_path


def _serialize_receipt(
    receipt: ActionAttemptReceipt,
    receipt_written_at_utc: str,
    artifact_directory: Path,
) -> dict[str, object]:
    if receipt.planner_decision is None:
        raise ValueError("Receipt planner_decision must be populated before persistence.")
    if receipt.actuation_attempted is None:
        raise ValueError("Receipt actuation_attempted must be populated before persistence.")
    if receipt.save_source_metadata is None:
        raise ValueError("Receipt save_source_metadata must be populated before persistence.")
    if receipt.actuator_config_snapshot is None:
        raise ValueError("Receipt actuator_config_snapshot must be populated before persistence.")

    serialized_probe_samples = _serialize_probe_samples(
        receipt=receipt,
        artifact_directory=artifact_directory,
    )

    return {
        "action": receipt.action,
        "save_path": receipt.save_path,
        "baseline_hash": receipt.baseline_hash,
        "prepared_save_hash": receipt.baseline_hash,
        "final_status": receipt.final_status,
        "failure_reason": receipt.failure_reason,
        "elapsed_seconds": receipt.elapsed_seconds,
        "changed_save_count": receipt.changed_save_count,
        "claim_attempted": receipt.claim_attempted,
        "number_of_claim_taps": receipt.number_of_claim_taps,
        "claim_tap_timestamps": list(
            [] if receipt.claim_tap_timestamps is None else receipt.claim_tap_timestamps
        ),
        "resulting_save_hashes": list(
            [] if receipt.resulting_save_hashes is None else receipt.resulting_save_hashes
        ),
        "candidate_hashes": list(receipt.candidate_hashes),
        "final_candidate_hash": receipt.final_candidate_hash,
        "contract_identity": {
            "action": receipt.contract_identity.action,
            "expectation_keys": list(receipt.contract_identity.expectation_keys),
            "required_expected_values": dict(receipt.contract_identity.required_expected_values),
            "supporting_fields": list(receipt.contract_identity.supporting_fields),
        },
        "runtime_context": {
            "receipt_schema_version": receipt.runtime_context.receipt_schema_version,
            "poll_interval_seconds": receipt.runtime_context.poll_interval_seconds,
            "timeout_seconds": receipt.runtime_context.timeout_seconds,
            "timeout_scope": receipt.runtime_context.timeout_scope,
            "manual_observation_mode": receipt.runtime_context.manual_observation_mode,
            "save_snapshot_available": receipt.runtime_context.save_snapshot_available,
            "active_smelters": receipt.runtime_context.active_smelters,
            "active_crafters": receipt.runtime_context.active_crafters,
            "nearest_completion_seconds": receipt.runtime_context.nearest_completion_seconds,
            "planner_nearest_completion_seconds": (
                receipt.runtime_context.planner_nearest_completion_seconds
            ),
            "planner_save_snapshot_used": receipt.runtime_context.planner_save_snapshot_used,
            "planner_deferred_for_imminent_completion": (
                receipt.runtime_context.planner_deferred_for_imminent_completion
            ),
            "exit_code": receipt.runtime_context.exit_code,
            "action_override_used": receipt.runtime_context.action_override_used,
            "action_override_requested_action": (
                receipt.runtime_context.action_override_requested_action
            ),
            "save_repull_interval_seconds": receipt.runtime_context.save_repull_interval_seconds,
            "save_repull_count": receipt.runtime_context.save_repull_count,
            "save_repull_failure_count": receipt.runtime_context.save_repull_failure_count,
            "actuation_elapsed_seconds": receipt.runtime_context.actuation_elapsed_seconds,
            "verification_elapsed_seconds": receipt.runtime_context.verification_elapsed_seconds,
            "verification_started": receipt.runtime_context.verification_started,
            "verification_starved_by_timeout": (
                receipt.runtime_context.verification_starved_by_timeout
            ),
        },
        "actuator_execution": {
            "actuator_type": receipt.actuator_execution.actuator_type,
            "actuator_execution_status": receipt.actuator_execution.actuator_execution_status,
            "actuator_command_count": receipt.actuator_execution.actuator_command_count,
            "actuator_command_summary": list(receipt.actuator_execution.actuator_command_summary),
            "claim_attempted": receipt.actuator_execution.claim_attempted,
            "number_of_claim_taps": receipt.actuator_execution.number_of_claim_taps,
            "claim_tap_timestamps": list(receipt.actuator_execution.claim_tap_timestamps),
            "stage_events": [
                {
                    "stage_name": sample.stage_name,
                    "wall_clock_utc": sample.wall_clock_utc,
                    "elapsed_seconds": sample.elapsed_seconds,
                    "detail": sample.detail,
                    "error": sample.error,
                }
                for sample in receipt.actuator_execution.stage_events
            ],
            "probe_samples": serialized_probe_samples,
        },
        "actuator_config": _serialize_actuator_config(receipt),
        "planner_decision": {
            "selected_action": receipt.planner_decision.selected_action,
            "decision_reason": receipt.planner_decision.decision_reason,
            "actuation_required": receipt.planner_decision.actuation_required,
        },
        "actuation_attempted": receipt.actuation_attempted,
        "save_source": _serialize_save_source(receipt),
        "receipt_written_at_utc": receipt_written_at_utc,
        "verifier_messages": list(receipt.verifier_messages),
    }


def _serialize_actuator_config(receipt: ActionAttemptReceipt) -> dict[str, object]:
    snapshot = receipt.actuator_config_snapshot
    if snapshot is None:
        raise ValueError("Receipt actuator_config_snapshot must be populated before persistence.")

    payload: dict[str, object] = {
        "actuator_type": snapshot.actuator_type,
    }
    if snapshot.adb_path is not None:
        payload["adb_path"] = snapshot.adb_path
    if snapshot.adb_serial is not None:
        payload["adb_serial"] = snapshot.adb_serial
    if snapshot.app_package is not None:
        payload["app_package"] = snapshot.app_package
    if snapshot.app_activity is not None:
        payload["app_activity"] = snapshot.app_activity
    if snapshot.manual_observation_mode:
        payload["manual_observation_mode"] = snapshot.manual_observation_mode
    if snapshot.manual_observation_window_seconds is not None:
        payload["manual_observation_window_seconds"] = snapshot.manual_observation_window_seconds
    if snapshot.manual_observation_probe_interval_seconds is not None:
        payload["manual_observation_probe_interval_seconds"] = (
            snapshot.manual_observation_probe_interval_seconds
        )
    if snapshot.ark_ad_wait_seconds is not None:
        payload["ark_ad_wait_seconds"] = snapshot.ark_ad_wait_seconds
    if snapshot.ark_skip_close_wait_seconds is not None:
        payload["ark_skip_close_wait_seconds"] = snapshot.ark_skip_close_wait_seconds
    if snapshot.ark_return_wait_seconds is not None:
        payload["ark_return_wait_seconds"] = snapshot.ark_return_wait_seconds
    if snapshot.ark_esc_attempts is not None:
        payload["ark_esc_attempts"] = snapshot.ark_esc_attempts
    if snapshot.ark_esc_interval_seconds is not None:
        payload["ark_esc_interval_seconds"] = snapshot.ark_esc_interval_seconds
    if snapshot.ark_post_watch_probe_count is not None:
        payload["ark_post_watch_probe_count"] = snapshot.ark_post_watch_probe_count
    if snapshot.ark_post_watch_probe_interval_seconds is not None:
        payload["ark_post_watch_probe_interval_seconds"] = (
            snapshot.ark_post_watch_probe_interval_seconds
        )
    if snapshot.ark_post_watch_ui_dump_max_text_length is not None:
        payload["ark_post_watch_ui_dump_max_text_length"] = (
            snapshot.ark_post_watch_ui_dump_max_text_length
        )
    if snapshot.ad_boost_verbose_signal_tracing is not None:
        payload["ad_boost_verbose_signal_tracing"] = snapshot.ad_boost_verbose_signal_tracing
    if snapshot.ad_boost_soft_exit_timeout_seconds is not None:
        payload["ad_boost_soft_exit_timeout_seconds"] = snapshot.ad_boost_soft_exit_timeout_seconds
    if snapshot.ad_boost_hard_exit_timeout_seconds is not None:
        payload["ad_boost_hard_exit_timeout_seconds"] = snapshot.ad_boost_hard_exit_timeout_seconds
    if snapshot.ad_post_reward_claim_tap is not None:
        payload["ad_post_reward_claim_tap"] = snapshot.ad_post_reward_claim_tap
    if snapshot.ad_post_reward_claim_retry_count is not None:
        payload["ad_post_reward_claim_retry_count"] = snapshot.ad_post_reward_claim_retry_count
    if snapshot.ad_post_reward_claim_interval_seconds is not None:
        payload["ad_post_reward_claim_interval_seconds"] = snapshot.ad_post_reward_claim_interval_seconds
    if snapshot.ad_post_reward_claim_settle_seconds is not None:
        payload["ad_post_reward_claim_settle_seconds"] = snapshot.ad_post_reward_claim_settle_seconds
    if snapshot.ad_post_reward_auto_claim_enabled is not None:
        payload["ad_post_reward_auto_claim_enabled"] = snapshot.ad_post_reward_auto_claim_enabled
    return payload


def _serialize_probe_samples(
    receipt: ActionAttemptReceipt,
    artifact_directory: Path,
) -> list[dict[str, object]]:
    serialized_samples: list[dict[str, object]] = []
    for sample_index, sample in enumerate(receipt.actuator_execution.probe_samples, start=1):
        artifact_paths = _persist_probe_artifacts(
            sample=sample,
            artifact_directory=artifact_directory,
            sample_index=sample_index,
        )
        serialized_samples.append(
            {
                "sample_offset_seconds": sample.sample_offset_seconds,
                "sample_context": sample.sample_context,
                "sample_reference_stage": sample.sample_reference_stage,
                "esc_attempt_index": sample.esc_attempt_index,
                "focus_window": sample.focus_window,
                "focus_package": sample.focus_package,
                "focus_activity": sample.focus_activity,
                "ui_text_excerpt": sample.ui_text_excerpt,
                "ui_text_sha256": sample.ui_text_sha256,
                "probe_error": sample.probe_error,
                "artifact_paths": artifact_paths,
            }
        )
    return serialized_samples


def _persist_probe_artifacts(
    *,
    sample,
    artifact_directory: Path,
    sample_index: int,
) -> dict[str, object]:
    artifact_paths = {
        "dumpsys_window_path": sample.dumpsys_window_artifact_path,
        "dumpsys_activity_path": sample.dumpsys_activity_artifact_path,
        "ui_dump_xml_path": sample.ui_dump_xml_artifact_path,
    }
    file_stem = _probe_artifact_stem(sample_index=sample_index, sample=sample)
    if sample.dumpsys_window_output is not None:
        artifact_paths["dumpsys_window_path"] = str(
            _write_probe_artifact(
                artifact_directory=artifact_directory,
                file_stem=file_stem,
                suffix="dumpsys_window.txt",
                content=sample.dumpsys_window_output,
            )
        )
    if sample.dumpsys_activity_output is not None:
        artifact_paths["dumpsys_activity_path"] = str(
            _write_probe_artifact(
                artifact_directory=artifact_directory,
                file_stem=file_stem,
                suffix="dumpsys_activity.txt",
                content=sample.dumpsys_activity_output,
            )
        )
    if sample.ui_dump_xml is not None:
        artifact_paths["ui_dump_xml_path"] = str(
            _write_probe_artifact(
                artifact_directory=artifact_directory,
                file_stem=file_stem,
                suffix="ui_dump.xml",
                content=sample.ui_dump_xml,
            )
        )
    return artifact_paths


def _probe_artifact_stem(*, sample_index: int, sample) -> str:
    stem = f"probe_{sample_index:03d}"
    if sample.sample_context is not None:
        stem += f"_{sample.sample_context}"
    if sample.esc_attempt_index is not None:
        stem += f"_attempt_{sample.esc_attempt_index}"
    return stem


def _write_probe_artifact(
    *,
    artifact_directory: Path,
    file_stem: str,
    suffix: str,
    content: str,
) -> Path:
    artifact_directory.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_directory / f"{file_stem}_{suffix}"
    artifact_path.write_text(content, encoding="utf-8")
    return artifact_path


def _serialize_save_source(receipt: ActionAttemptReceipt) -> dict[str, object]:
    metadata = receipt.save_source_metadata
    if metadata is None:
        raise ValueError("Receipt save_source_metadata must be populated before persistence.")

    snapshot = metadata.config_snapshot
    payload: dict[str, object] = {
        "save_source_type": metadata.save_source_type,
        "preparation_performed": metadata.preparation_performed,
        "prepared_local_path": metadata.prepared_local_path,
        "original_requested_path": metadata.original_requested_path,
    }
    if snapshot is None:
        return payload

    if snapshot.local_source_path is not None:
        payload["local_source_path"] = snapshot.local_source_path
    if snapshot.adb_path is not None:
        payload["adb_path"] = snapshot.adb_path
    if snapshot.adb_serial is not None:
        payload["adb_serial"] = snapshot.adb_serial
    if snapshot.remote_save_path is not None:
        payload["remote_save_path"] = snapshot.remote_save_path
    if snapshot.vhdx_path is not None:
        payload["vhdx_path"] = snapshot.vhdx_path
    if snapshot.vhdx_member_name is not None:
        payload["vhdx_member_name"] = snapshot.vhdx_member_name
    if snapshot.seven_zip_path is not None:
        payload["seven_zip_path"] = snapshot.seven_zip_path
    return payload


def _normalize_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H-%M-%SZ")


def _sanitize_action_name(action: str) -> str:
    sanitized = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in action
    )
    if not sanitized:
        raise ValueError("Receipt action produced an empty filename component.")
    return sanitized


def _next_available_path(directory: Path, timestamp: str, action: str) -> Path:
    base_name = f"{timestamp}_{action}"
    candidate = directory / f"{base_name}.json"
    suffix = 1
    while candidate.exists():
        candidate = directory / f"{base_name}_{suffix:02d}.json"
        suffix += 1
    return candidate


def _artifact_directory_for_receipt(receipt_path: Path) -> Path:
    return receipt_path.with_name(f"{receipt_path.stem}_artifacts")


def check_ad_boost_suppressed(
    receipt_dir: Path | None = None,
    *,
    threshold: int = 3,
) -> bool:
    """Return True if recent receipts show enough consecutive failed ad-boost attempts.

    Reads persisted receipt JSON files in reverse chronological order (filenames
    sort naturally by timestamp).  Counts consecutive ``activate_ad_boost``
    receipts whose ``final_status`` is not ``"PASS"``.  Returns ``True`` when the
    count reaches *threshold*.

    Fails open: returns ``False`` if the directory is missing, empty, or any
    file cannot be read/parsed.
    """

    if threshold <= 0:
        raise ValueError("Suppression threshold must be greater than zero.")

    directory = DEFAULT_RECEIPT_DIRECTORY if receipt_dir is None else receipt_dir
    try:
        if not directory.is_dir():
            return False
        receipt_files = sorted(directory.glob("*.json"), reverse=True)
    except OSError:
        return False

    consecutive_failures = 0
    for receipt_path in receipt_files[:threshold]:
        try:
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False

        action = payload.get("action")
        final_status = payload.get("final_status")
        if action != "activate_ad_boost":
            return False
        if final_status == "PASS":
            return False
        consecutive_failures += 1
        if consecutive_failures >= threshold:
            return True

    return False

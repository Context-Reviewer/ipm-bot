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
    receipt_path.write_text(
        json.dumps(_serialize_receipt(receipt, timestamp), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return receipt_path


def _serialize_receipt(
    receipt: ActionAttemptReceipt,
    receipt_written_at_utc: str,
) -> dict[str, object]:
    if receipt.planner_decision is None:
        raise ValueError("Receipt planner_decision must be populated before persistence.")
    if receipt.actuation_attempted is None:
        raise ValueError("Receipt actuation_attempted must be populated before persistence.")
    if receipt.save_source_metadata is None:
        raise ValueError("Receipt save_source_metadata must be populated before persistence.")
    if receipt.actuator_config_snapshot is None:
        raise ValueError("Receipt actuator_config_snapshot must be populated before persistence.")

    return {
        "action": receipt.action,
        "save_path": receipt.save_path,
        "baseline_hash": receipt.baseline_hash,
        "prepared_save_hash": receipt.baseline_hash,
        "final_status": receipt.final_status,
        "failure_reason": receipt.failure_reason,
        "elapsed_seconds": receipt.elapsed_seconds,
        "changed_save_count": receipt.changed_save_count,
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
            "exit_code": receipt.runtime_context.exit_code,
        },
        "actuator_execution": {
            "actuator_type": receipt.actuator_execution.actuator_type,
            "actuator_execution_status": receipt.actuator_execution.actuator_execution_status,
            "actuator_command_count": receipt.actuator_execution.actuator_command_count,
            "actuator_command_summary": list(receipt.actuator_execution.actuator_command_summary),
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
    return payload


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

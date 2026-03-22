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

    return {
        "action": receipt.action,
        "save_path": receipt.save_path,
        "baseline_hash": receipt.baseline_hash,
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
        "planner_decision": {
            "selected_action": receipt.planner_decision.selected_action,
            "decision_reason": receipt.planner_decision.decision_reason,
            "actuation_required": receipt.planner_decision.actuation_required,
        },
        "actuation_attempted": receipt.actuation_attempted,
        "receipt_written_at_utc": receipt_written_at_utc,
        "verifier_messages": list(receipt.verifier_messages),
    }


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

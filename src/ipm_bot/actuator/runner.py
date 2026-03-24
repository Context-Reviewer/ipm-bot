"""Action execution and closed-loop verification helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import time
from typing import Mapping

from ipm_bot.actuator.boundary import (
    ActionActuator,
    ActuatorConfigSnapshot,
    ActuatorExecutionError,
    ActuatorExecutionMetadata,
)
from ipm_bot.control.contracts import ActionContract, ActionContractIdentity
from ipm_bot.control.receipt_schema import CURRENT_RECEIPT_SCHEMA_VERSION
from ipm_bot.control.save_source import SaveRefreshController, SaveRefreshTelemetry, SaveSourceMetadata
from ipm_bot.planner.planner import PlannerDecision
from ipm_bot.control.save_watcher import get_save_fingerprint, wait_for_save_change
from ipm_bot.save.models import PlayerSnapshot
from ipm_bot.verifier.verifier import VerificationResult, VerificationStatus, verify_transition


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    verification: VerificationResult
    terminal_failure_reason: FailureReason | None = None


class FailureReason(StrEnum):
    NONE = "NONE"
    TIMEOUT_NO_SAVE_CHANGE = "TIMEOUT_NO_SAVE_CHANGE"
    TIMEOUT_AFTER_SAVE_CHANGES = "TIMEOUT_AFTER_SAVE_CHANGES"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    AMBIGUOUS_TRANSITION = "AMBIGUOUS_TRANSITION"
    ACTUATION_ERROR = "ACTUATION_ERROR"
    COMMAND_EXECUTION_ERROR = "COMMAND_EXECUTION_ERROR"
    SAVE_WATCH_ERROR = "SAVE_WATCH_ERROR"


@dataclass(frozen=True, slots=True)
class ReceiptRuntimeContext:
    receipt_schema_version: int
    poll_interval_seconds: float
    timeout_seconds: float
    timeout_scope: str = "total_run"
    manual_observation_mode: bool = False
    save_snapshot_available: bool = False
    active_smelters: int = 0
    active_crafters: int = 0
    nearest_completion_seconds: float | None = None
    exit_code: int | None = None
    action_override_used: bool = False
    action_override_requested_action: str | None = None
    save_repull_interval_seconds: float | None = None
    save_repull_count: int = 0
    save_repull_failure_count: int = 0
    actuation_elapsed_seconds: float = 0.0
    verification_elapsed_seconds: float = 0.0
    verification_started: bool = False
    verification_starved_by_timeout: bool = False

    def __post_init__(self) -> None:
        if self.receipt_schema_version <= 0:
            raise ValueError("Receipt schema version must be greater than zero.")
        if self.poll_interval_seconds <= 0:
            raise ValueError("Poll interval must be greater than zero.")
        if self.timeout_seconds <= 0:
            raise ValueError("Timeout must be greater than zero.")
        if self.timeout_scope not in {"total_run", "verification_only_after_actuation"}:
            raise ValueError("Timeout scope must be one of the supported receipt values.")
        if self.active_smelters < 0:
            raise ValueError("Active smelters must be non-negative.")
        if self.active_crafters < 0:
            raise ValueError("Active crafters must be non-negative.")
        if (
            self.nearest_completion_seconds is not None
            and self.nearest_completion_seconds < 0
        ):
            raise ValueError("Nearest completion seconds must be non-negative when provided.")
        if self.exit_code is not None and self.exit_code < 0:
            raise ValueError("Exit code must be non-negative when provided.")
        if self.action_override_requested_action is not None and not self.action_override_requested_action:
            raise ValueError("Action override requested action must not be empty when provided.")
        if (
            self.save_repull_interval_seconds is not None
            and self.save_repull_interval_seconds <= 0
        ):
            raise ValueError("Save re-pull interval must be greater than zero when provided.")
        if self.save_repull_count < 0:
            raise ValueError("Save re-pull count must be non-negative.")
        if self.save_repull_failure_count < 0:
            raise ValueError("Save re-pull failure count must be non-negative.")
        if self.actuation_elapsed_seconds < 0:
            raise ValueError("Actuation elapsed seconds must be non-negative.")
        if self.verification_elapsed_seconds < 0:
            raise ValueError("Verification elapsed seconds must be non-negative.")


@dataclass(frozen=True, slots=True)
class ActionAttemptReceipt:
    action: str
    save_path: str
    baseline_hash: str
    final_status: VerificationStatus
    failure_reason: FailureReason
    elapsed_seconds: float
    changed_save_count: int
    candidate_hashes: list[str]
    final_candidate_hash: str | None
    contract_identity: ActionContractIdentity
    runtime_context: ReceiptRuntimeContext
    actuator_execution: ActuatorExecutionMetadata
    verifier_messages: list[str]
    actuator_config_snapshot: ActuatorConfigSnapshot | None = None
    planner_decision: PlannerDecision | None = None
    actuation_attempted: bool | None = None
    save_source_metadata: SaveSourceMetadata | None = None

    def __post_init__(self) -> None:
        if not self.action:
            raise ValueError("Receipt action must not be empty.")
        if not self.save_path:
            raise ValueError("Receipt save_path must not be empty.")
        if not self.baseline_hash:
            raise ValueError("Receipt baseline_hash must not be empty.")
        if self.elapsed_seconds < 0:
            raise ValueError("Receipt elapsed_seconds must be non-negative.")
        if self.changed_save_count < 0:
            raise ValueError("Receipt changed_save_count must be non-negative.")
        if self.changed_save_count != len(self.candidate_hashes):
            raise ValueError(
                "Receipt changed_save_count must match the number of candidate hashes."
            )
        if self.changed_save_count == 0 and self.final_candidate_hash is not None:
            raise ValueError(
                "Receipt final_candidate_hash must be None when no candidate saves were observed."
            )
        if self.changed_save_count > 0 and self.final_candidate_hash != self.candidate_hashes[-1]:
            raise ValueError(
                "Receipt final_candidate_hash must match the most recent candidate hash."
            )
        if self.final_status == "PASS" and self.failure_reason is not FailureReason.NONE:
            raise ValueError("Passing receipts must use failure reason NONE.")
        if self.final_status != "PASS" and self.failure_reason is FailureReason.NONE:
            raise ValueError("Non-passing receipts must use a non-NONE failure reason.")
        if self.planner_decision is not None and self.planner_decision.selected_action != self.action:
            raise ValueError("Receipt planner decision action must match receipt action.")
        if (
            self.actuator_config_snapshot is not None
            and self.actuator_config_snapshot.actuator_type != self.actuator_execution.actuator_type
        ):
            raise ValueError(
                "Receipt actuator_config_snapshot actuator_type must match actuator_execution."
            )


def run_action_until_verified(
    action: str,
    save_path: Path,
    snapshot_before: PlayerSnapshot,
    contract: ActionContract,
    actuator: ActionActuator,
    poll_interval_s: float,
    timeout_s: float | None = None,
    save_refresh_controller: SaveRefreshController | None = None,
    verification_timeout_starts_after_actuation: bool = False,
    manual_observation_mode: bool = False,
) -> ActionAttemptReceipt:
    """Execute an action and verify it against successive updated saves."""

    if poll_interval_s <= 0:
        raise ValueError("poll_interval_s must be greater than zero.")
    effective_timeout_s = contract.default_timeout_seconds if timeout_s is None else timeout_s
    if effective_timeout_s <= 0:
        raise ValueError("timeout_s must be greater than zero.")
    resolved_save_path = str(save_path.resolve())

    baseline_hash = get_save_fingerprint(save_path).sha256
    initial_baseline_hash = baseline_hash
    started_at = time.monotonic()
    actuation_completed_at = started_at
    verification_started = False
    candidate_hashes: list[str] = []
    last_verifier_messages: list[str] = []
    actuator_execution = ActuatorExecutionMetadata(
        actuator_type=actuator.actuator_type,
        actuator_execution_status="NOT_REQUIRED",
        actuator_command_count=0,
        actuator_command_summary=[],
    )

    if action == "idle":
        return _build_receipt(
            action=action,
            save_path=resolved_save_path,
            baseline_hash=initial_baseline_hash,
            final_status="PASS",
            failure_reason=FailureReason.NONE,
            contract=contract,
            effective_timeout_s=effective_timeout_s,
            poll_interval_s=poll_interval_s,
            actuator_execution=actuator_execution,
            started_at=started_at,
            candidate_hashes=candidate_hashes,
            verifier_messages=_with_refresh_messages(
                ["Idle action selected; no actuation or verification loop required."],
                save_refresh_controller,
            ),
            save_refresh_telemetry=_refresh_telemetry(save_refresh_controller),
            actuation_elapsed_seconds=0.0,
            verification_elapsed_seconds=0.0,
            verification_started=False,
            verification_starved_by_timeout=False,
            timeout_scope=(
                "verification_only_after_actuation"
                if verification_timeout_starts_after_actuation
                else "total_run"
            ),
            manual_observation_mode=manual_observation_mode,
        )

    try:
        actuator_execution = actuator.execute(action)
        actuation_completed_at = time.monotonic()
    except ActuatorExecutionError as exc:
        actuation_completed_at = time.monotonic()
        return _build_receipt(
            action=action,
            save_path=resolved_save_path,
            baseline_hash=initial_baseline_hash,
            final_status="FAIL",
            failure_reason=FailureReason.COMMAND_EXECUTION_ERROR,
            contract=contract,
            effective_timeout_s=effective_timeout_s,
            poll_interval_s=poll_interval_s,
            actuator_execution=exc.metadata,
            started_at=started_at,
            candidate_hashes=candidate_hashes,
            verifier_messages=_with_refresh_messages(
                [f"Action '{action}' failed before verification: {exc}"],
                save_refresh_controller,
            ),
            save_refresh_telemetry=_refresh_telemetry(save_refresh_controller),
            actuation_elapsed_seconds=actuation_completed_at - started_at,
            verification_elapsed_seconds=0.0,
            verification_started=False,
            verification_starved_by_timeout=False,
            timeout_scope=(
                "verification_only_after_actuation"
                if verification_timeout_starts_after_actuation
                else "total_run"
            ),
            manual_observation_mode=manual_observation_mode,
        )
    except Exception as exc:
        actuation_completed_at = time.monotonic()
        return _build_receipt(
            action=action,
            save_path=resolved_save_path,
            baseline_hash=initial_baseline_hash,
            final_status="FAIL",
            failure_reason=FailureReason.ACTUATION_ERROR,
            contract=contract,
            effective_timeout_s=effective_timeout_s,
            poll_interval_s=poll_interval_s,
            actuator_execution=ActuatorExecutionMetadata(
                actuator_type=actuator.actuator_type,
                actuator_execution_status="FAILED",
                actuator_command_count=0,
                actuator_command_summary=[],
            ),
            started_at=started_at,
            candidate_hashes=candidate_hashes,
            verifier_messages=_with_refresh_messages(
                [f"Action '{action}' failed before verification: {exc}"],
                save_refresh_controller,
            ),
            save_refresh_telemetry=_refresh_telemetry(save_refresh_controller),
            actuation_elapsed_seconds=actuation_completed_at - started_at,
            verification_elapsed_seconds=0.0,
            verification_started=False,
            verification_starved_by_timeout=False,
            timeout_scope=(
                "verification_only_after_actuation"
                if verification_timeout_starts_after_actuation
                else "total_run"
            ),
            manual_observation_mode=manual_observation_mode,
        )

    verification_started_at = time.monotonic()
    verification_started = True
    if verification_timeout_starts_after_actuation:
        deadline = verification_started_at + effective_timeout_s
    else:
        deadline = started_at + effective_timeout_s
    verification_starved_by_timeout = deadline <= verification_started_at

    while True:
        remaining_s = deadline - time.monotonic()
        if remaining_s <= 0:
            break

        try:
            observation = wait_for_save_change(
                path=save_path,
                baseline_hash=baseline_hash,
                timeout_s=remaining_s,
                poll_interval_s=poll_interval_s,
                before_read=(
                    save_refresh_controller.maybe_refresh
                    if save_refresh_controller is not None
                    else None
                ),
            )
        except Exception as exc:
            return _build_receipt(
                action=action,
                save_path=resolved_save_path,
                baseline_hash=initial_baseline_hash,
                final_status="FAIL",
                failure_reason=FailureReason.SAVE_WATCH_ERROR,
                contract=contract,
                effective_timeout_s=effective_timeout_s,
                poll_interval_s=poll_interval_s,
                actuator_execution=actuator_execution,
                started_at=started_at,
                candidate_hashes=candidate_hashes,
                verifier_messages=_with_refresh_messages(
                    last_verifier_messages + [f"Save watcher error: {exc}"],
                    save_refresh_controller,
                ),
                save_refresh_telemetry=_refresh_telemetry(save_refresh_controller),
                actuation_elapsed_seconds=actuation_completed_at - started_at,
                verification_elapsed_seconds=time.monotonic() - verification_started_at,
                verification_started=verification_started,
                verification_starved_by_timeout=verification_starved_by_timeout,
                timeout_scope=(
                    "verification_only_after_actuation"
                    if verification_timeout_starts_after_actuation
                    else "total_run"
                ),
                manual_observation_mode=manual_observation_mode,
            )

        if observation is None:
            break

        candidate_hashes.append(observation.fingerprint.sha256)
        evaluation = _evaluate_candidate(
            action=action,
            before=snapshot_before,
            after=observation.snapshot,
            contract=contract,
        )
        last_verifier_messages = evaluation.verification.messages
        if evaluation.verification.status == "PASS":
            return _build_receipt(
                action=action,
                save_path=resolved_save_path,
                baseline_hash=initial_baseline_hash,
                final_status="PASS",
                failure_reason=FailureReason.NONE,
                contract=contract,
                effective_timeout_s=effective_timeout_s,
                poll_interval_s=poll_interval_s,
                actuator_execution=actuator_execution,
                started_at=started_at,
                candidate_hashes=candidate_hashes,
                verifier_messages=_with_refresh_messages(
                    evaluation.verification.messages,
                    save_refresh_controller,
                ),
                save_refresh_telemetry=_refresh_telemetry(save_refresh_controller),
                actuation_elapsed_seconds=actuation_completed_at - started_at,
                verification_elapsed_seconds=time.monotonic() - verification_started_at,
                verification_started=verification_started,
                verification_starved_by_timeout=verification_starved_by_timeout,
                timeout_scope=(
                    "verification_only_after_actuation"
                    if verification_timeout_starts_after_actuation
                    else "total_run"
                ),
                manual_observation_mode=manual_observation_mode,
            )

        if evaluation.terminal_failure_reason is not None:
            return _build_receipt(
                action=action,
                save_path=resolved_save_path,
                baseline_hash=initial_baseline_hash,
                final_status=evaluation.verification.status,
                failure_reason=evaluation.terminal_failure_reason,
                contract=contract,
                effective_timeout_s=effective_timeout_s,
                poll_interval_s=poll_interval_s,
                actuator_execution=actuator_execution,
                started_at=started_at,
                candidate_hashes=candidate_hashes,
                verifier_messages=_with_refresh_messages(
                    evaluation.verification.messages,
                    save_refresh_controller,
                ),
                save_refresh_telemetry=_refresh_telemetry(save_refresh_controller),
                actuation_elapsed_seconds=actuation_completed_at - started_at,
                verification_elapsed_seconds=time.monotonic() - verification_started_at,
                verification_started=verification_started,
                verification_starved_by_timeout=verification_starved_by_timeout,
                timeout_scope=(
                    "verification_only_after_actuation"
                    if verification_timeout_starts_after_actuation
                    else "total_run"
                ),
                manual_observation_mode=manual_observation_mode,
            )

        baseline_hash = observation.fingerprint.sha256

    if candidate_hashes:
        return _build_receipt(
            action=action,
            save_path=resolved_save_path,
            baseline_hash=initial_baseline_hash,
            final_status="FAIL",
            failure_reason=FailureReason.TIMEOUT_AFTER_SAVE_CHANGES,
            contract=contract,
            effective_timeout_s=effective_timeout_s,
            poll_interval_s=poll_interval_s,
            actuator_execution=actuator_execution,
            started_at=started_at,
            candidate_hashes=candidate_hashes,
            verifier_messages=_with_timeout_budget_messages(
                _with_refresh_messages(
                    last_verifier_messages,
                    save_refresh_controller,
                ),
                verification_starved_by_timeout=verification_starved_by_timeout,
            ),
            save_refresh_telemetry=_refresh_telemetry(save_refresh_controller),
            actuation_elapsed_seconds=actuation_completed_at - started_at,
            verification_elapsed_seconds=max(0.0, time.monotonic() - verification_started_at),
            verification_started=verification_started,
            verification_starved_by_timeout=verification_starved_by_timeout,
            timeout_scope=(
                "verification_only_after_actuation"
                if verification_timeout_starts_after_actuation
                else "total_run"
            ),
            manual_observation_mode=manual_observation_mode,
        )

    return _build_receipt(
        action=action,
        save_path=resolved_save_path,
        baseline_hash=initial_baseline_hash,
        final_status="FAIL",
        failure_reason=FailureReason.TIMEOUT_NO_SAVE_CHANGE,
        contract=contract,
        effective_timeout_s=effective_timeout_s,
        poll_interval_s=poll_interval_s,
        actuator_execution=actuator_execution,
        started_at=started_at,
        candidate_hashes=candidate_hashes,
        verifier_messages=_with_timeout_budget_messages(
            _with_refresh_messages([], save_refresh_controller),
            verification_starved_by_timeout=verification_starved_by_timeout,
        ),
        save_refresh_telemetry=_refresh_telemetry(save_refresh_controller),
        actuation_elapsed_seconds=actuation_completed_at - started_at,
        verification_elapsed_seconds=max(
            0.0,
            (0.0 if not verification_started else time.monotonic() - verification_started_at),
        ),
        verification_started=verification_started,
        verification_starved_by_timeout=verification_starved_by_timeout,
        timeout_scope=(
            "verification_only_after_actuation"
            if verification_timeout_starts_after_actuation
            else "total_run"
        ),
        manual_observation_mode=manual_observation_mode,
    )


def _evaluate_candidate(
    action: str,
    before: PlayerSnapshot,
    after: PlayerSnapshot,
    contract: ActionContract,
) -> CandidateEvaluation:
    base_result = verify_transition(before, after, dict(contract.expectations))
    if action != "activate_ad_boost":
        return _finalize_candidate(before, after, action, contract, base_result)

    before_fields = before.flat_fields()
    after_fields = after.flat_fields()

    before_ads_watched = _require_int_field(before_fields, "ads_watched")
    after_ads_watched = _require_int_field(after_fields, "ads_watched")
    _require_field(before_fields, "save_timestamp")
    _require_field(after_fields, "save_timestamp")
    _require_bool_field(after_fields, "ad_boost_active")

    if after_ads_watched < before_ads_watched:
        return CandidateEvaluation(
            verification=VerificationResult(
                status="FAIL",
                success=False,
                messages=[
                    "Field 'ads_watched' decreased after attempting to activate ad boost.",
                    *base_result.messages,
                ],
            ),
            terminal_failure_reason=FailureReason.VERIFICATION_FAILED,
        )

    return _finalize_candidate(before, after, action, contract, base_result)


def _finalize_candidate(
    before: PlayerSnapshot,
    after: PlayerSnapshot,
    action: str,
    contract: ActionContract,
    base_result: VerificationResult,
) -> CandidateEvaluation:
    if base_result.status == "PASS":
        return CandidateEvaluation(
            verification=_with_supporting_messages(before, after, contract, base_result)
        )

    ambiguous_result = _classify_ambiguous_transition(
        before=before,
        after=after,
        action=action,
        contract=contract,
        base_result=base_result,
    )
    if ambiguous_result is not None:
        return CandidateEvaluation(
            verification=ambiguous_result,
            terminal_failure_reason=FailureReason.AMBIGUOUS_TRANSITION,
        )

    return CandidateEvaluation(verification=base_result)


def _classify_ambiguous_transition(
    before: PlayerSnapshot,
    after: PlayerSnapshot,
    action: str,
    contract: ActionContract,
    base_result: VerificationResult,
) -> VerificationResult | None:
    changed_supporting_fields = _changed_supporting_fields(
        before, after, contract.supporting_fields
    )
    if not changed_supporting_fields:
        return None

    unmet_expectations = _unmet_expected_values(after, contract)
    if not unmet_expectations:
        return None

    supporting_messages = [
        f"Supporting signal observed: '{field_name}' changed."
        for field_name in changed_supporting_fields
    ]
    unmet_messages = [
        f"Required post-state not reached for '{field_name}': expected={expected_value!r}, actual={actual_value!r}."
        for field_name, expected_value, actual_value in unmet_expectations
    ]
    return VerificationResult(
        status="AMBIGUOUS",
        success=False,
        messages=[
            f"Observed save activity after action '{action}', but the required post-state was not reached.",
            *supporting_messages,
            *unmet_messages,
            *base_result.messages,
        ],
    )


def _with_supporting_messages(
    before: PlayerSnapshot,
    after: PlayerSnapshot,
    contract: ActionContract,
    result: VerificationResult,
) -> VerificationResult:
    if result.status != "PASS":
        return result

    supporting_messages = [
        f"Supporting field '{field_name}' changed during action verification."
        for field_name in _changed_supporting_fields(before, after, contract.supporting_fields)
    ]
    if not supporting_messages:
        return result

    return VerificationResult(
        status=result.status,
        success=result.success,
        messages=result.messages + supporting_messages,
    )


def _changed_supporting_fields(
    before: PlayerSnapshot,
    after: PlayerSnapshot,
    supporting_fields: tuple[str, ...],
) -> list[str]:
    before_fields = before.flat_fields()
    after_fields = after.flat_fields()
    changed_fields: list[str] = []
    for field_name in supporting_fields:
        before_value = _require_field(before_fields, field_name)
        after_value = _require_field(after_fields, field_name)
        if before_value != after_value:
            changed_fields.append(field_name)
    return changed_fields


def _unmet_expected_values(
    after: PlayerSnapshot,
    contract: ActionContract,
) -> list[tuple[str, object, object]]:
    after_fields = after.flat_fields()
    unmet: list[tuple[str, object, object]] = []
    expected_values = contract.expectations.get("expected_values", {})
    for field_name, expected_value in expected_values.items():
        actual_value = _require_field(after_fields, field_name)
        if actual_value != expected_value:
            unmet.append((field_name, expected_value, actual_value))
    return unmet


def _build_receipt(
    action: str,
    save_path: str,
    baseline_hash: str,
    final_status: VerificationStatus,
    failure_reason: FailureReason,
    contract: ActionContract,
    effective_timeout_s: float,
    poll_interval_s: float,
    actuator_execution: ActuatorExecutionMetadata,
    started_at: float,
    candidate_hashes: list[str],
    verifier_messages: list[str],
    save_refresh_telemetry: SaveRefreshTelemetry | None = None,
    actuation_elapsed_seconds: float = 0.0,
    verification_elapsed_seconds: float = 0.0,
    verification_started: bool = False,
    verification_starved_by_timeout: bool = False,
    timeout_scope: str = "total_run",
    manual_observation_mode: bool = False,
) -> ActionAttemptReceipt:
    return ActionAttemptReceipt(
        action=action,
        save_path=save_path,
        baseline_hash=baseline_hash,
        final_status=final_status,
        failure_reason=failure_reason,
        elapsed_seconds=time.monotonic() - started_at,
        changed_save_count=len(candidate_hashes),
        candidate_hashes=list(candidate_hashes),
        final_candidate_hash=candidate_hashes[-1] if candidate_hashes else None,
        contract_identity=contract.identity(action),
        runtime_context=ReceiptRuntimeContext(
            receipt_schema_version=CURRENT_RECEIPT_SCHEMA_VERSION,
            poll_interval_seconds=poll_interval_s,
            timeout_seconds=effective_timeout_s,
            timeout_scope=timeout_scope,
            manual_observation_mode=manual_observation_mode,
            save_repull_interval_seconds=(
                None if save_refresh_telemetry is None else save_refresh_telemetry.refresh_interval_seconds
            ),
            save_repull_count=(
                0 if save_refresh_telemetry is None else save_refresh_telemetry.refresh_attempt_count
            ),
            save_repull_failure_count=(
                0 if save_refresh_telemetry is None else save_refresh_telemetry.refresh_failure_count
            ),
            actuation_elapsed_seconds=actuation_elapsed_seconds,
            verification_elapsed_seconds=verification_elapsed_seconds,
            verification_started=verification_started,
            verification_starved_by_timeout=verification_starved_by_timeout,
        ),
        actuator_execution=actuator_execution,
        verifier_messages=list(verifier_messages),
    )


def _refresh_telemetry(
    save_refresh_controller: SaveRefreshController | None,
) -> SaveRefreshTelemetry | None:
    if save_refresh_controller is None:
        return None
    return save_refresh_controller.telemetry()


def _with_refresh_messages(
    messages: list[str],
    save_refresh_controller: SaveRefreshController | None,
) -> list[str]:
    if save_refresh_controller is None:
        return list(messages)
    telemetry = save_refresh_controller.telemetry()
    return list(messages) + list(telemetry.warning_messages)


def _with_timeout_budget_messages(
    messages: list[str],
    *,
    verification_starved_by_timeout: bool,
) -> list[str]:
    if not verification_starved_by_timeout:
        return list(messages)
    return list(messages) + [
        "Verification budget was exhausted by actuation before verification polling could begin."
    ]


def _require_field(
    fields: Mapping[str, object],
    field_name: str,
) -> object:
    value = fields.get(field_name)
    if value is None:
        raise ValueError(f"Missing required snapshot field: {field_name}.")
    return value


def _require_bool_field(fields: Mapping[str, object], field_name: str) -> bool:
    value = _require_field(fields, field_name)
    if not isinstance(value, bool):
        raise ValueError(f"Field '{field_name}' must be a bool for action classification.")
    return value


def _require_int_field(fields: Mapping[str, object], field_name: str) -> int:
    value = _require_field(fields, field_name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Field '{field_name}' must be an int for action classification.")
    return value

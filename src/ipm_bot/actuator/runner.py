"""Action execution and closed-loop verification helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    planner_nearest_completion_seconds: float | None = None
    planner_save_snapshot_used: bool = False
    planner_deferred_for_imminent_completion: bool = False
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
        if (
            self.planner_nearest_completion_seconds is not None
            and self.planner_nearest_completion_seconds < 0
        ):
            raise ValueError(
                "Planner nearest completion seconds must be non-negative when provided."
            )
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
    contract_evidence: dict[str, object] = field(default_factory=dict)
    claim_attempted: bool = False
    number_of_claim_taps: int = 0
    claim_tap_timestamps: list[float] | None = None
    branch_attempted: bool = False
    branch_policy: str = "disabled"
    branch_choice_tap_count: int = 0
    branch_choice_tap_timestamps: list[float] | None = None
    ad_exit_override_attempted: bool = False
    ad_exit_override_tap_count: int = 0
    ad_exit_override_tap_timestamps: list[float] | None = None
    ad_exit_override_activity: str | None = None
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
        if not isinstance(self.contract_evidence, dict):
            raise ValueError("Receipt contract_evidence must be a dictionary.")
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
        claim_tap_timestamps = [] if self.claim_tap_timestamps is None else self.claim_tap_timestamps
        if self.number_of_claim_taps < 0:
            raise ValueError("Receipt number_of_claim_taps must be non-negative.")
        if self.number_of_claim_taps != len(claim_tap_timestamps):
            raise ValueError(
                "Receipt number_of_claim_taps must match the number of claim tap timestamps."
            )
        if any(timestamp < 0 for timestamp in claim_tap_timestamps):
            raise ValueError("Receipt claim tap timestamps must be non-negative.")
        if self.claim_attempted != (self.number_of_claim_taps > 0):
            raise ValueError(
                "Receipt claim_attempted must match whether any claim taps were recorded."
            )
        branch_choice_tap_timestamps = (
            [] if self.branch_choice_tap_timestamps is None else self.branch_choice_tap_timestamps
        )
        if self.branch_policy not in {"disabled", "single_choice_default"}:
            raise ValueError("Receipt branch_policy must be one of the supported values.")
        if self.branch_choice_tap_count < 0:
            raise ValueError("Receipt branch_choice_tap_count must be non-negative.")
        if self.branch_choice_tap_count != len(branch_choice_tap_timestamps):
            raise ValueError(
                "Receipt branch_choice_tap_count must match the number of branch tap timestamps."
            )
        if any(timestamp < 0 for timestamp in branch_choice_tap_timestamps):
            raise ValueError("Receipt branch tap timestamps must be non-negative.")
        if self.branch_attempted != (self.branch_choice_tap_count > 0):
            raise ValueError(
                "Receipt branch_attempted must match whether any branch taps were recorded."
            )
        ad_exit_override_tap_timestamps = (
            []
            if self.ad_exit_override_tap_timestamps is None
            else self.ad_exit_override_tap_timestamps
        )
        if self.ad_exit_override_tap_count < 0:
            raise ValueError("Receipt ad_exit_override_tap_count must be non-negative.")
        if self.ad_exit_override_tap_count != len(ad_exit_override_tap_timestamps):
            raise ValueError(
                "Receipt ad_exit_override_tap_count must match the number of override tap timestamps."
            )
        if any(timestamp < 0 for timestamp in ad_exit_override_tap_timestamps):
            raise ValueError("Receipt ad exit override tap timestamps must be non-negative.")
        if self.ad_exit_override_attempted != (self.ad_exit_override_tap_count > 0):
            raise ValueError(
                "Receipt ad_exit_override_attempted must match whether any override taps were recorded."
            )
        if self.ad_exit_override_activity is not None and not self.ad_exit_override_activity:
            raise ValueError("Receipt ad_exit_override_activity must not be empty when provided.")
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
    final_candidate_snapshot: PlayerSnapshot | None = None
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
            snapshot_before=snapshot_before,
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
        actuator_execution = actuator.execute(_resolve_actuator_action(action))
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
            snapshot_before=snapshot_before,
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
            snapshot_before=snapshot_before,
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
                snapshot_before=snapshot_before,
                final_candidate_snapshot=final_candidate_snapshot,
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
        final_candidate_snapshot = observation.snapshot
        evaluation = _evaluate_candidate(
            action=action,
            before=snapshot_before,
            after=observation.snapshot,
            contract=contract,
            actuator_execution=actuator_execution,
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
                snapshot_before=snapshot_before,
                final_candidate_snapshot=final_candidate_snapshot,
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
                snapshot_before=snapshot_before,
                final_candidate_snapshot=final_candidate_snapshot,
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
            snapshot_before=snapshot_before,
            final_candidate_snapshot=final_candidate_snapshot,
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
        snapshot_before=snapshot_before,
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
    actuator_execution: ActuatorExecutionMetadata,
) -> CandidateEvaluation:
    base_result = verify_transition(before, after, dict(contract.expectations))
    try:
        reward_followup_attempted = (
            actuator_execution.claim_attempted or actuator_execution.branch_attempted
        )
        if not reward_followup_attempted and action not in {"activate_ad_boost", "claim_reward"}:
            return _finalize_candidate(before, after, action, contract, base_result)

        before_fields = before.flat_fields()
        after_fields = after.flat_fields()

        if action == "activate_ad_boost":
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

        reward_claim_evaluation = _evaluate_claim_proof(
            action=action,
            before=before,
            after=after,
            base_result=base_result,
            claim_attempted=actuator_execution.claim_attempted,
            branch_attempted=actuator_execution.branch_attempted,
            branch_policy=actuator_execution.branch_policy,
        )
        if reward_claim_evaluation is not None:
            return reward_claim_evaluation

        return _finalize_candidate(before, after, action, contract, base_result)
    except ValueError as exc:
        return CandidateEvaluation(
            verification=VerificationResult(
                status="AMBIGUOUS",
                success=False,
                messages=[
                    f"Unable to safely evaluate action '{action}' using required save-backed fields: {exc}",
                    *base_result.messages,
                ],
            ),
            terminal_failure_reason=FailureReason.AMBIGUOUS_TRANSITION,
        )


def _evaluate_claim_proof(
    *,
    action: str,
    before: PlayerSnapshot,
    after: PlayerSnapshot,
    base_result: VerificationResult,
    claim_attempted: bool,
    branch_attempted: bool,
    branch_policy: str,
) -> CandidateEvaluation | None:
    if action != "claim_reward" and not claim_attempted and not branch_attempted:
        return None
    if base_result.status != "PASS":
        return None

    standard_ad_messages = _standard_ad_proof_messages(before, after)
    if standard_ad_messages:
        return CandidateEvaluation(
            verification=VerificationResult(
                status="PASS",
                success=True,
                messages=base_result.messages + standard_ad_messages,
            )
        )

    mining_evaluation = _evaluate_mining_reward_contract(
        before=before,
        after=after,
        base_result=base_result,
    )
    if mining_evaluation is not None:
        return mining_evaluation

    return CandidateEvaluation(
            verification=VerificationResult(
                status="AMBIGUOUS",
                success=False,
                messages=[
                    _missing_reward_proof_message(
                        action=action,
                        claim_attempted=claim_attempted,
                        branch_attempted=branch_attempted,
                        branch_policy=branch_policy,
                    ),
                    *base_result.messages,
                ],
            ),
        terminal_failure_reason=FailureReason.AMBIGUOUS_TRANSITION,
    )


def _standard_ad_proof_messages(
    before: PlayerSnapshot,
    after: PlayerSnapshot,
) -> list[str]:
    before_fields = before.flat_fields()
    after_fields = after.flat_fields()
    messages: list[str] = []

    before_arks_claimed = _require_int_field(before_fields, "arks_claimed")
    after_arks_claimed = _require_int_field(after_fields, "arks_claimed")
    arks_claimed_increased = after_arks_claimed > before_arks_claimed

    before_cash = _require_field(before_fields, "cash")
    after_cash = _require_field(after_fields, "cash")
    if not isinstance(before_cash, float) or not isinstance(after_cash, float):
        raise ValueError("Field 'cash' must be a float for action classification.")
    cash_increased = after_cash > before_cash

    before_dark_matter = _require_int_field(before_fields, "dark_matter")
    after_dark_matter = _require_int_field(after_fields, "dark_matter")
    dark_matter_increased = after_dark_matter > before_dark_matter

    before_ready = _require_bool_field(before_fields, "ark_reward_ready_to_claim")
    after_ready = _require_bool_field(after_fields, "ark_reward_ready_to_claim")
    ready_cleared = before_ready and not after_ready
    if (arks_claimed_increased or cash_increased or dark_matter_increased) and ready_cleared:
        messages.append(
            "Standard ad contract satisfied: reward evidence was observed and "
            "'ark_reward_ready_to_claim' cleared."
        )

    return messages


def _evaluate_mining_reward_contract(
    *,
    before: PlayerSnapshot,
    after: PlayerSnapshot,
    base_result: VerificationResult,
) -> CandidateEvaluation | None:
    before_free_rewards_claimed = _optional_int_field(
        before.flat_fields(),
        "free_rewards_claimed_count",
    )
    after_free_rewards_claimed = _optional_int_field(
        after.flat_fields(),
        "free_rewards_claimed_count",
    )
    free_rewards_claimed_increased = (
        before_free_rewards_claimed is not None
        and after_free_rewards_claimed is not None
        and after_free_rewards_claimed > before_free_rewards_claimed
    )

    before_miner_pass_rewards_claimed = _optional_int_field(
        before.flat_fields(),
        "miner_pass_rewards_claimed_count",
    )
    after_miner_pass_rewards_claimed = _optional_int_field(
        after.flat_fields(),
        "miner_pass_rewards_claimed_count",
    )
    miner_pass_rewards_claimed_increased = (
        before_miner_pass_rewards_claimed is not None
        and after_miner_pass_rewards_claimed is not None
        and after_miner_pass_rewards_claimed > before_miner_pass_rewards_claimed
    )

    before_claimed = _optional_raw_bool(before, "rewardIsClaimed")
    after_claimed = _optional_raw_bool(after, "rewardIsClaimed")
    has_claim_flag_evidence = before_claimed is not None or after_claimed is not None

    effect_observed, effect_messages = _mining_effect_messages(before, after)

    messages: list[str] = []
    if free_rewards_claimed_increased:
        messages.append(
            "Mining reward contract satisfied: 'free_rewards_claimed_count' increased."
        )
    if miner_pass_rewards_claimed_increased:
        messages.append(
            "Mining reward contract satisfied: 'miner_pass_rewards_claimed_count' increased."
        )
    messages.extend(effect_messages)

    if after_claimed is True and before_claimed is not True:
        messages.append("Mining reward contract satisfied: 'rewardIsClaimed' became True.")

    if messages and (after_claimed is True or not has_claim_flag_evidence):
        return CandidateEvaluation(
            verification=VerificationResult(
                status="PASS",
                success=True,
                messages=base_result.messages + messages,
            )
        )

    if effect_observed and has_claim_flag_evidence and after_claimed is not True:
        return CandidateEvaluation(
            verification=VerificationResult(
                status="AMBIGUOUS",
                success=False,
                messages=base_result.messages
                + effect_messages
                + [
                    "Mining reward effect was observed, but 'rewardIsClaimed' has not been persisted yet."
                ],
            ),
            terminal_failure_reason=FailureReason.AMBIGUOUS_TRANSITION,
        )

    return None


def _missing_reward_proof_message(
    *,
    action: str,
    claim_attempted: bool,
    branch_attempted: bool,
    branch_policy: str,
) -> str:
    if claim_attempted and branch_attempted:
        return (
            f"Claim taps and branch taps were issued during action '{action}', but the save diff "
            f"did not prove reward application under branch policy '{branch_policy}'."
        )
    if branch_attempted:
        return (
            f"Branch taps were issued during action '{action}' under branch policy "
            f"'{branch_policy}', but the save diff did not prove reward application."
        )
    return (
        f"Claim taps were issued during action '{action}', but the save diff did not prove "
        "reward application."
    )


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
    snapshot_before: PlayerSnapshot,
    final_candidate_snapshot: PlayerSnapshot | None = None,
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
        contract_evidence=_build_contract_evidence(
            before=snapshot_before,
            after=final_candidate_snapshot,
        ),
        claim_attempted=actuator_execution.claim_attempted,
        number_of_claim_taps=actuator_execution.number_of_claim_taps,
        claim_tap_timestamps=list(actuator_execution.claim_tap_timestamps),
        branch_attempted=actuator_execution.branch_attempted,
        branch_policy=actuator_execution.branch_policy,
        branch_choice_tap_count=actuator_execution.branch_choice_tap_count,
        branch_choice_tap_timestamps=list(actuator_execution.branch_choice_tap_timestamps),
        ad_exit_override_attempted=actuator_execution.ad_exit_override_attempted,
        ad_exit_override_tap_count=actuator_execution.ad_exit_override_tap_count,
        ad_exit_override_tap_timestamps=list(actuator_execution.ad_exit_override_tap_timestamps),
        ad_exit_override_activity=actuator_execution.ad_exit_override_activity,
    )


def _build_contract_evidence(
    *,
    before: PlayerSnapshot,
    after: PlayerSnapshot | None,
) -> dict[str, object]:
    return {
        "standard_ad": {
            "arksClaimed_before": before.ad.arks_claimed,
            "arksClaimed_after": None if after is None else after.ad.arks_claimed,
            "lastAdWatchedDate_before": _isoformat_or_none(before.ad.last_ad_watched_date),
            "lastAdWatchedDate_after": (
                None if after is None else _isoformat_or_none(after.ad.last_ad_watched_date)
            ),
            "arkRewardReadyToClaim_before": before.ad.ark_reward_ready_to_claim,
            "arkRewardReadyToClaim_after": (
                None if after is None else after.ad.ark_reward_ready_to_claim
            ),
            "cash_before": before.currencies.cash,
            "cash_after": None if after is None else after.currencies.cash,
            "darkMatter_before": before.currencies.dark_matter,
            "darkMatter_after": None if after is None else after.currencies.dark_matter,
            "beaconTokens_before": _optional_raw_int(before, "beaconTokens"),
            "beaconTokens_after": None if after is None else _optional_raw_int(after, "beaconTokens"),
        },
        "boost": {
            "adBoostActive_before": before.ad.ad_boost_active,
            "adBoostActive_after": None if after is None else after.ad.ad_boost_active,
            "adBoostStartDate_before": _isoformat_or_none(before.ad.ad_boost_start_date),
            "adBoostStartDate_after": (
                None if after is None else _isoformat_or_none(after.ad.ad_boost_start_date)
            ),
        },
        "mining": {
            "reward_id": _optional_raw_int(before, "rewardId")
            if _optional_raw_int(before, "rewardId") is not None
            else (None if after is None else _optional_raw_int(after, "rewardId")),
            "reward_type": _optional_raw_str(before, "rewardType")
            if _optional_raw_str(before, "rewardType") is not None
            else (None if after is None else _optional_raw_str(after, "rewardType")),
            "isClaimed_before": _optional_raw_bool(before, "rewardIsClaimed"),
            "isClaimed_after": None if after is None else _optional_raw_bool(after, "rewardIsClaimed"),
            "effect_fields": _effect_field_evidence(before, after),
        },
        "integrity": {
            "serverTimeVerified_before": _optional_raw_bool(before, "serverTimeVerified"),
            "serverTimeVerified_after": (
                None if after is None else _optional_raw_bool(after, "serverTimeVerified")
            ),
            "deviceTimeWrong_before": _optional_raw_bool(before, "deviceTimeWrong"),
            "deviceTimeWrong_after": (
                None if after is None else _optional_raw_bool(after, "deviceTimeWrong")
            ),
        },
    }


def _effect_field_evidence(
    before: PlayerSnapshot,
    after: PlayerSnapshot | None,
) -> dict[str, dict[str, object]]:
    field_names = _effect_field_names(before, after)
    return {
        field_name: {
            "before": before.raw_fields.get(field_name),
            "after": None if after is None else after.raw_fields.get(field_name),
        }
        for field_name in field_names
    }


def _effect_field_names(
    before: PlayerSnapshot,
    after: PlayerSnapshot | None,
) -> tuple[str, ...]:
    candidate_names = set()
    for field_name in before.raw_fields:
        if field_name.startswith(("rewardEffect", "miningEffect")):
            candidate_names.add(field_name)
    if after is not None:
        for field_name in after.raw_fields:
            if field_name.startswith(("rewardEffect", "miningEffect")):
                candidate_names.add(field_name)
    return tuple(sorted(candidate_names))


def _mining_effect_messages(
    before: PlayerSnapshot,
    after: PlayerSnapshot,
) -> tuple[bool, list[str]]:
    messages: list[str] = []
    for field_name in _effect_field_names(before, after):
        before_value = before.raw_fields.get(field_name)
        after_value = after.raw_fields.get(field_name)
        if before_value == after_value:
            continue
        messages.append(
            "Mining reward effect observed: "
            f"'{field_name}' changed from {before_value!r} to {after_value!r}."
        )
    return (bool(messages), messages)


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


def _optional_int_field(fields: Mapping[str, object], field_name: str) -> int | None:
    value = fields.get(field_name)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Field '{field_name}' must be an int for action classification.")
    return value


def _optional_raw_bool(snapshot: PlayerSnapshot, field_name: str) -> bool | None:
    value = snapshot.raw_fields.get(field_name)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"Field '{field_name}' must be a bool for action classification.")
    return value


def _optional_raw_int(snapshot: PlayerSnapshot, field_name: str) -> int | None:
    value = snapshot.raw_fields.get(field_name)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Field '{field_name}' must be an int for action classification.")
    return value


def _optional_raw_str(snapshot: PlayerSnapshot, field_name: str) -> str | None:
    value = snapshot.raw_fields.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Field '{field_name}' must be a str for action classification.")
    return value


def _isoformat_or_none(value: object) -> str | None:
    if value is None:
        return None
    if not hasattr(value, "isoformat"):
        raise ValueError("Receipt datetime evidence must support isoformat().")
    return value.isoformat()


def _resolve_actuator_action(action: str) -> str:
    if action == "claim_reward":
        return "claim_ark_reward"
    return action

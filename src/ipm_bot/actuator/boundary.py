"""Actuator interface for executing one game action."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


ActuatorExecutionStatus = Literal["NOT_REQUIRED", "COMPLETED", "FAILED"]
AdPostRewardBranchPolicy = Literal["disabled", "single_choice_default"]


@dataclass(frozen=True, slots=True)
class ActuatorProbeSample:
    sample_offset_seconds: float
    sample_context: str | None = None
    sample_reference_stage: str | None = None
    esc_attempt_index: int | None = None
    focus_window: str | None = None
    focus_package: str | None = None
    focus_activity: str | None = None
    ui_text_excerpt: str | None = None
    ui_text_sha256: str | None = None
    probe_error: str | None = None
    dumpsys_window_output: str | None = None
    dumpsys_activity_output: str | None = None
    ui_dump_xml: str | None = None
    dumpsys_window_artifact_path: str | None = None
    dumpsys_activity_artifact_path: str | None = None
    ui_dump_xml_artifact_path: str | None = None

    def __post_init__(self) -> None:
        if self.sample_offset_seconds < 0:
            raise ValueError("Actuator probe sample offset must be non-negative.")
        if self.sample_context is not None and not self.sample_context:
            raise ValueError("Actuator probe sample context must not be empty when provided.")
        if self.sample_reference_stage is not None and not self.sample_reference_stage:
            raise ValueError(
                "Actuator probe sample reference stage must not be empty when provided."
            )
        if self.esc_attempt_index is not None and self.esc_attempt_index <= 0:
            raise ValueError("Actuator probe sample esc_attempt_index must be positive when provided.")


@dataclass(frozen=True, slots=True)
class ActuatorStageEvent:
    stage_name: str
    wall_clock_utc: str
    elapsed_seconds: float | None = None
    detail: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.stage_name:
            raise ValueError("Actuator stage event stage_name must not be empty.")
        if not self.wall_clock_utc:
            raise ValueError("Actuator stage event wall_clock_utc must not be empty.")
        if self.elapsed_seconds is not None and self.elapsed_seconds < 0:
            raise ValueError("Actuator stage event elapsed_seconds must be non-negative.")


@dataclass(frozen=True, slots=True)
class ActuatorSignalTrace:
    timestamp_offset_seconds: float
    stage: str
    focus_activity: str | None
    focus_package: str | None
    ui_text_excerpt: str | None
    is_ad_activity: bool
    is_playable_ad: bool
    is_store: bool
    is_game_activity: bool
    has_exit_marker: bool | None
    has_ad_markers: bool
    action_taken: str
    action_reason: str

    def __post_init__(self) -> None:
        if self.timestamp_offset_seconds < 0:
            raise ValueError("Actuator signal trace timestamp offset must be non-negative.")
        if not self.stage:
            raise ValueError("Actuator signal trace stage must not be empty.")


@dataclass(frozen=True, slots=True)
class ActuatorExecutionMetadata:
    actuator_type: str
    actuator_execution_status: ActuatorExecutionStatus
    actuator_command_count: int
    actuator_command_summary: list[str]
    stage_events: list[ActuatorStageEvent] = field(default_factory=list)
    probe_samples: list[ActuatorProbeSample] = field(default_factory=list)
    signal_traces: list[ActuatorSignalTrace] = field(default_factory=list)
    claim_attempted: bool = False
    number_of_claim_taps: int = 0
    claim_tap_timestamps: list[float] = field(default_factory=list)
    branch_attempted: bool = False
    branch_policy: AdPostRewardBranchPolicy = "disabled"
    branch_choice_tap_count: int = 0
    branch_choice_tap_timestamps: list[float] = field(default_factory=list)
    ad_exit_override_attempted: bool = False
    ad_exit_override_tap_count: int = 0
    ad_exit_override_tap_timestamps: list[float] = field(default_factory=list)
    ad_exit_override_activity: str | None = None

    def __post_init__(self) -> None:
        if not self.actuator_type:
            raise ValueError("Actuator execution metadata actuator_type must not be empty.")
        if self.actuator_command_count < 0:
            raise ValueError("Actuator command count must be non-negative.")
        if self.actuator_command_count != len(self.actuator_command_summary):
            raise ValueError(
                "Actuator command count must match the number of command summary entries."
            )
        if self.number_of_claim_taps < 0:
            raise ValueError("Actuator claim tap count must be non-negative.")
        if self.number_of_claim_taps != len(self.claim_tap_timestamps):
            raise ValueError(
                "Actuator claim tap count must match the number of claim tap timestamps."
            )
        if any(timestamp < 0 for timestamp in self.claim_tap_timestamps):
            raise ValueError("Actuator claim tap timestamps must be non-negative.")
        if self.claim_attempted != (self.number_of_claim_taps > 0):
            raise ValueError(
                "Actuator claim_attempted must match whether any claim taps were recorded."
            )
        if self.branch_policy not in {"disabled", "single_choice_default"}:
            raise ValueError("Actuator branch policy must be one of the supported values.")
        if self.branch_choice_tap_count < 0:
            raise ValueError("Actuator branch choice tap count must be non-negative.")
        if self.branch_choice_tap_count != len(self.branch_choice_tap_timestamps):
            raise ValueError(
                "Actuator branch choice tap count must match the number of branch tap timestamps."
            )
        if any(timestamp < 0 for timestamp in self.branch_choice_tap_timestamps):
            raise ValueError("Actuator branch tap timestamps must be non-negative.")
        if self.branch_attempted != (self.branch_choice_tap_count > 0):
            raise ValueError(
                "Actuator branch_attempted must match whether any branch taps were recorded."
            )
        if self.ad_exit_override_tap_count < 0:
            raise ValueError("Actuator ad exit override tap count must be non-negative.")
        if self.ad_exit_override_tap_count != len(self.ad_exit_override_tap_timestamps):
            raise ValueError(
                "Actuator ad exit override tap count must match the number of override tap timestamps."
            )
        if any(timestamp < 0 for timestamp in self.ad_exit_override_tap_timestamps):
            raise ValueError("Actuator ad exit override tap timestamps must be non-negative.")
        if self.ad_exit_override_attempted != (self.ad_exit_override_tap_count > 0):
            raise ValueError(
                "Actuator ad_exit_override_attempted must match whether any override taps were recorded."
            )
        if self.ad_exit_override_activity is not None and not self.ad_exit_override_activity:
            raise ValueError("Actuator ad_exit_override_activity must not be empty when provided.")


@dataclass(frozen=True, slots=True)
class ActuatorConfigSnapshot:
    actuator_type: str
    adb_path: str | None = None
    adb_serial: str | None = None
    app_package: str | None = None
    app_activity: str | None = None
    manual_observation_mode: bool = False
    manual_observation_window_seconds: float | None = None
    manual_observation_probe_interval_seconds: float | None = None
    ark_ad_wait_seconds: float | None = None
    ark_skip_close_wait_seconds: float | None = None
    ark_return_wait_seconds: float | None = None
    ark_esc_attempts: int | None = None
    ark_esc_interval_seconds: float | None = None
    ark_post_watch_probe_count: int | None = None
    ark_post_watch_probe_interval_seconds: float | None = None
    ark_post_watch_ui_dump_max_text_length: int | None = None
    ad_boost_open_timeout_seconds: float | None = None
    ad_boost_probe_interval_seconds: float | None = None
    ad_boost_stabilization_seconds: float | None = None
    ad_boost_exit_timeout_seconds: float | None = None
    ad_boost_exit_keyevent: str | None = None
    ad_boost_store_max_redirects: int | None = None
    claim_ark_same_app_endcard_close_tap: str | None = None
    claim_ark_same_app_endcard_close_attempts: int | None = None
    claim_ark_same_app_endcard_close_interval_seconds: float | None = None
    claim_ark_same_app_back_attempts: int | None = None
    claim_ark_same_app_back_interval_seconds: float | None = None
    ad_boost_verbose_signal_tracing: bool | None = None
    ad_boost_soft_exit_timeout_seconds: float | None = None
    ad_boost_hard_exit_timeout_seconds: float | None = None
    ad_exit_override_enabled: bool | None = None
    ad_exit_override_tap: str | None = None
    ad_exit_override_delay_seconds: float | None = None
    ad_exit_override_retry_count: int | None = None
    ad_exit_override_interval_seconds: float | None = None
    ad_exit_override_activity_allowlist: tuple[str, ...] | None = None
    ad_post_reward_claim_tap: str | None = None
    ad_post_reward_claim_retry_count: int | None = None
    ad_post_reward_claim_interval_seconds: float | None = None
    ad_post_reward_claim_settle_seconds: float | None = None
    ad_post_reward_auto_claim_enabled: bool | None = None
    ad_post_reward_branch_policy: AdPostRewardBranchPolicy | None = None
    ad_post_reward_choice_tap: str | None = None
    ad_post_reward_choice_retry_count: int | None = None
    ad_post_reward_choice_interval_seconds: float | None = None
    ad_post_reward_choice_settle_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.actuator_type:
            raise ValueError("Actuator config snapshot actuator_type must not be empty.")
        if (
            self.manual_observation_window_seconds is not None
            and self.manual_observation_window_seconds <= 0
        ):
            raise ValueError(
                "Actuator config snapshot manual observation window must be greater than zero."
            )
        if (
            self.manual_observation_probe_interval_seconds is not None
            and self.manual_observation_probe_interval_seconds <= 0
        ):
            raise ValueError(
                "Actuator config snapshot manual observation probe interval must be greater than zero."
            )
        if self.ark_ad_wait_seconds is not None and self.ark_ad_wait_seconds <= 0:
            raise ValueError("Actuator config snapshot ad wait must be greater than zero.")
        if (
            self.ark_skip_close_wait_seconds is not None
            and self.ark_skip_close_wait_seconds <= 0
        ):
            raise ValueError("Actuator config snapshot skip-close wait must be greater than zero.")
        if self.ark_return_wait_seconds is not None and self.ark_return_wait_seconds <= 0:
            raise ValueError("Actuator config snapshot return wait must be greater than zero.")
        if self.ark_esc_attempts is not None and self.ark_esc_attempts <= 0:
            raise ValueError("Actuator config snapshot esc attempts must be greater than zero.")
        if self.ark_esc_interval_seconds is not None and self.ark_esc_interval_seconds <= 0:
            raise ValueError("Actuator config snapshot esc interval must be greater than zero.")
        if self.ark_post_watch_probe_count is not None and self.ark_post_watch_probe_count < 0:
            raise ValueError("Actuator config snapshot probe count must be non-negative.")
        if (
            self.ark_post_watch_probe_interval_seconds is not None
            and self.ark_post_watch_probe_interval_seconds <= 0
        ):
            raise ValueError("Actuator config snapshot probe interval must be greater than zero.")
        if (
            self.ark_post_watch_ui_dump_max_text_length is not None
            and self.ark_post_watch_ui_dump_max_text_length <= 0
        ):
            raise ValueError("Actuator config snapshot UI dump max text length must be greater than zero.")
        if self.ad_boost_open_timeout_seconds is not None and self.ad_boost_open_timeout_seconds <= 0:
            raise ValueError("Actuator config snapshot ad boost open timeout must be greater than zero.")
        if self.ad_boost_probe_interval_seconds is not None and self.ad_boost_probe_interval_seconds <= 0:
            raise ValueError("Actuator config snapshot ad boost probe interval must be greater than zero.")
        if self.ad_boost_stabilization_seconds is not None and self.ad_boost_stabilization_seconds < 0:
            raise ValueError("Actuator config snapshot ad boost stabilization must be non-negative.")
        if self.ad_boost_exit_timeout_seconds is not None and self.ad_boost_exit_timeout_seconds <= 0:
            raise ValueError("Actuator config snapshot ad boost exit timeout must be greater than zero.")
        if self.ad_boost_store_max_redirects is not None and self.ad_boost_store_max_redirects < 0:
            raise ValueError("Actuator config snapshot ad boost store max redirects must be non-negative.")
        if self.ad_boost_soft_exit_timeout_seconds is not None and self.ad_boost_soft_exit_timeout_seconds <= 0:
            raise ValueError("Actuator config snapshot ad boost soft exit timeout must be greater than zero.")
        if self.ad_boost_hard_exit_timeout_seconds is not None and self.ad_boost_hard_exit_timeout_seconds <= 0:
            raise ValueError("Actuator config snapshot ad boost hard exit timeout must be greater than zero.")
        if self.ad_exit_override_delay_seconds is not None and self.ad_exit_override_delay_seconds < 0:
            raise ValueError("Actuator config snapshot ad exit override delay must be non-negative.")
        if self.ad_exit_override_retry_count is not None and self.ad_exit_override_retry_count < 0:
            raise ValueError("Actuator config snapshot ad exit override retry count must be non-negative.")
        if self.ad_exit_override_interval_seconds is not None and self.ad_exit_override_interval_seconds < 0:
            raise ValueError("Actuator config snapshot ad exit override interval must be non-negative.")
        if self.ad_exit_override_activity_allowlist is not None and any(
            not activity for activity in self.ad_exit_override_activity_allowlist
        ):
            raise ValueError(
                "Actuator config snapshot ad exit override activity allowlist entries must not be empty."
            )
        if self.ad_post_reward_claim_retry_count is not None and self.ad_post_reward_claim_retry_count < 0:
            raise ValueError("Actuator config snapshot ad post reward claim retry count must be non-negative.")
        if self.ad_post_reward_claim_interval_seconds is not None and self.ad_post_reward_claim_interval_seconds < 0:
            raise ValueError("Actuator config snapshot ad post reward claim interval must be non-negative.")
        if self.ad_post_reward_claim_settle_seconds is not None and self.ad_post_reward_claim_settle_seconds < 0:
            raise ValueError("Actuator config snapshot ad post reward claim settle seconds must be non-negative.")
        if (
            self.ad_post_reward_branch_policy is not None
            and self.ad_post_reward_branch_policy not in {"disabled", "single_choice_default"}
        ):
            raise ValueError("Actuator config snapshot ad post reward branch policy must be supported.")
        if (
            self.ad_post_reward_choice_retry_count is not None
            and self.ad_post_reward_choice_retry_count < 0
        ):
            raise ValueError(
                "Actuator config snapshot ad post reward choice retry count must be non-negative."
            )
        if (
            self.ad_post_reward_choice_interval_seconds is not None
            and self.ad_post_reward_choice_interval_seconds < 0
        ):
            raise ValueError(
                "Actuator config snapshot ad post reward choice interval must be non-negative."
            )
        if (
            self.ad_post_reward_choice_settle_seconds is not None
            and self.ad_post_reward_choice_settle_seconds < 0
        ):
            raise ValueError(
                "Actuator config snapshot ad post reward choice settle seconds must be non-negative."
            )

class ActuatorExecutionError(Exception):
    """Raised when a concrete actuator fails while issuing commands."""

    def __init__(
        self,
        message: str,
        metadata: ActuatorExecutionMetadata,
    ) -> None:
        super().__init__(message)
        self.metadata = metadata


class ActionActuator(Protocol):
    """Thin execution boundary for one planned action."""

    actuator_type: str
    config_snapshot: ActuatorConfigSnapshot

    def execute(self, action: str) -> ActuatorExecutionMetadata:
        """Execute the requested action or raise on failure."""

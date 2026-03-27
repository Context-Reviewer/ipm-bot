"""Actuator interface for executing one game action."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


ActuatorExecutionStatus = Literal["NOT_REQUIRED", "COMPLETED", "FAILED"]


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
class ActuatorExecutionMetadata:
    actuator_type: str
    actuator_execution_status: ActuatorExecutionStatus
    actuator_command_count: int
    actuator_command_summary: list[str]
    stage_events: list[ActuatorStageEvent] = field(default_factory=list)
    probe_samples: list[ActuatorProbeSample] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.actuator_type:
            raise ValueError("Actuator execution metadata actuator_type must not be empty.")
        if self.actuator_command_count < 0:
            raise ValueError("Actuator command count must be non-negative.")
        if self.actuator_command_count != len(self.actuator_command_summary):
            raise ValueError(
                "Actuator command count must match the number of command summary entries."
            )


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
    ad_boost_watch_timeout_seconds: float | None = None
    ad_boost_probe_interval_seconds: float | None = None
    ad_boost_stabilization_seconds: float | None = None
    ad_boost_exit_timeout_seconds: float | None = None
    ad_boost_exit_ui_markers: tuple[str, ...] | None = None
    ad_boost_exit_keyevent: str | None = None
    ad_boost_store_max_redirects: int | None = None
    ad_boost_max_close_actions: int | None = None

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
        if self.ad_boost_watch_timeout_seconds is not None and self.ad_boost_watch_timeout_seconds <= 0:
            raise ValueError("Actuator config snapshot ad boost watch timeout must be greater than zero.")
        if self.ad_boost_probe_interval_seconds is not None and self.ad_boost_probe_interval_seconds <= 0:
            raise ValueError("Actuator config snapshot ad boost probe interval must be greater than zero.")
        if self.ad_boost_stabilization_seconds is not None and self.ad_boost_stabilization_seconds < 0:
            raise ValueError("Actuator config snapshot ad boost stabilization must be non-negative.")
        if self.ad_boost_exit_timeout_seconds is not None and self.ad_boost_exit_timeout_seconds <= 0:
            raise ValueError("Actuator config snapshot ad boost exit timeout must be greater than zero.")
        if self.ad_boost_store_max_redirects is not None and self.ad_boost_store_max_redirects < 0:
            raise ValueError("Actuator config snapshot ad boost store max redirects must be non-negative.")
        if self.ad_boost_max_close_actions is not None and self.ad_boost_max_close_actions < 0:
            raise ValueError("Actuator config snapshot ad boost max close actions must be non-negative.")


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

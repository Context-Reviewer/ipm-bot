"""ADB-backed actuator scaffold behind the ActionActuator boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
import subprocess
import time
from typing import Callable, Protocol, Sequence
import xml.etree.ElementTree as ET

from .boundary import (
    ActionActuator,
    ActuatorConfigSnapshot,
    ActuatorExecutionError,
    ActuatorExecutionMetadata,
    ActuatorProbeSample,
    ActuatorStageEvent,
)


_UI_DUMP_REMOTE_PATH = "/sdcard/ipm_bot_window_dump.xml"


@dataclass(frozen=True, slots=True)
class TapPoint:
    x: int
    y: int

    def __post_init__(self) -> None:
        if self.x < 0 or self.y < 0:
            raise ValueError("Tap coordinates must be non-negative.")


@dataclass(frozen=True, slots=True)
class AdbActuatorConfig:
    adb_path: str = "adb"
    device_serial: str | None = None
    app_package: str | None = None
    app_activity: str | None = None
    manual_observation_mode: bool = False
    manual_observation_window_seconds: float = 20.0
    manual_observation_probe_interval_seconds: float = 1.0
    activate_ad_boost_tap: TapPoint = TapPoint(x=848, y=394)
    activate_ad_boost_watch_tap: TapPoint = TapPoint(x=448, y=859)
    claim_ark_reward_tap: TapPoint = TapPoint(x=852, y=311)
    claim_ark_reward_watch_tap: TapPoint = TapPoint(x=449, y=836)
    claim_ark_skip_tap: TapPoint = TapPoint(x=50, y=47)
    claim_ark_reward_final_claim_tap: TapPoint = TapPoint(x=454, y=968)
    ark_popup_wait_seconds: float = 1.5
    ark_ad_wait_seconds: float = 20.0
    ark_skip_close_wait_seconds: float = 1.0
    ark_return_wait_seconds: float = 3.0
    ark_esc_attempts: int = 1
    ark_esc_interval_seconds: float = 1.0
    ark_post_watch_probe_count: int = 0
    ark_post_watch_probe_interval_seconds: float = 2.0
    ark_post_watch_ui_dump_max_text_length: int = 240
    ad_boost_open_timeout_seconds: float = 10.0
    ad_boost_watch_timeout_seconds: float = 60.0
    ad_boost_probe_interval_seconds: float = 2.0
    ad_boost_stabilization_seconds: float = 3.0
    ad_boost_exit_timeout_seconds: float = 120.0
    ad_boost_exit_ui_markers: tuple[str, ...] = ("Close Ad", "Skip", "Reward granted")
    ad_boost_exit_keyevent: str = "KEYCODE_BACK"
    ad_boost_store_max_redirects: int = 3
    ad_boost_max_close_actions: int = 3

    def __post_init__(self) -> None:
        if not self.adb_path.strip():
            raise ValueError("adb_path must not be empty.")
        if self.app_activity and not self.app_package:
            raise ValueError("app_package is required when app_activity is configured.")
        if self.manual_observation_window_seconds <= 0:
            raise ValueError("manual_observation_window_seconds must be greater than zero.")
        if self.manual_observation_probe_interval_seconds <= 0:
            raise ValueError("manual_observation_probe_interval_seconds must be greater than zero.")
        if self.ark_popup_wait_seconds <= 0:
            raise ValueError("ark_popup_wait_seconds must be greater than zero.")
        if self.ark_ad_wait_seconds <= 0:
            raise ValueError("ark_ad_wait_seconds must be greater than zero.")
        if self.ark_skip_close_wait_seconds <= 0:
            raise ValueError("ark_skip_close_wait_seconds must be greater than zero.")
        if self.ark_return_wait_seconds <= 0:
            raise ValueError("ark_return_wait_seconds must be greater than zero.")
        if self.ark_esc_attempts <= 0:
            raise ValueError("ark_esc_attempts must be greater than zero.")
        if self.ark_esc_interval_seconds <= 0:
            raise ValueError("ark_esc_interval_seconds must be greater than zero.")
        if self.ark_post_watch_probe_count < 0:
            raise ValueError("ark_post_watch_probe_count must be non-negative.")
        if self.ark_post_watch_probe_interval_seconds <= 0:
            raise ValueError("ark_post_watch_probe_interval_seconds must be greater than zero.")
        if self.ark_post_watch_ui_dump_max_text_length <= 0:
            raise ValueError("ark_post_watch_ui_dump_max_text_length must be greater than zero.")
        if self.ad_boost_open_timeout_seconds <= 0:
            raise ValueError("ad_boost_open_timeout_seconds must be greater than zero.")
        if self.ad_boost_watch_timeout_seconds <= 0:
            raise ValueError("ad_boost_watch_timeout_seconds must be greater than zero.")
        if self.ad_boost_probe_interval_seconds <= 0:
            raise ValueError("ad_boost_probe_interval_seconds must be greater than zero.")
        if self.ad_boost_stabilization_seconds < 0:
            raise ValueError("ad_boost_stabilization_seconds must be non-negative.")
        if self.ad_boost_exit_timeout_seconds <= 0:
            raise ValueError("ad_boost_exit_timeout_seconds must be greater than zero.")
        if not self.ad_boost_exit_ui_markers:
            raise ValueError("ad_boost_exit_ui_markers must not be empty.")
        if not self.ad_boost_exit_keyevent:
            raise ValueError("ad_boost_exit_keyevent must not be blank.")
        if self.ad_boost_store_max_redirects < 0:
            raise ValueError("ad_boost_store_max_redirects must be non-negative.")
        if self.ad_boost_max_close_actions < 0:
            raise ValueError("ad_boost_max_close_actions must be non-negative.")


@dataclass(frozen=True, slots=True)
class PostWatchProbeStep:
    wait_budget_seconds: float


class CommandRunner(Protocol):
    """Narrow command-execution boundary for ADB command sequences."""

    def run(self, command: Sequence[str]) -> None:
        """Execute one command or raise on failure."""

    def capture(self, command: Sequence[str]) -> str:
        """Execute one command and return captured stdout."""


class SubprocessCommandRunner(CommandRunner):
    """Default subprocess-backed command runner for ADB commands."""

    def run(self, command: Sequence[str]) -> None:
        subprocess.run(list(command), check=True)

    def capture(self, command: Sequence[str]) -> str:
        completed = subprocess.run(
            list(command),
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout


class AdbActionActuator(ActionActuator):
    """Concrete actuator that emits explicit ADB command sequences."""

    actuator_type = "adb"

    def __init__(
        self,
        config: AdbActuatorConfig,
        command_runner: CommandRunner,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._command_runner = command_runner
        self._sleep_fn = sleep_fn
        self._monotonic_fn = monotonic_fn
        self.config_snapshot = ActuatorConfigSnapshot(
            actuator_type=self.actuator_type,
            adb_path=config.adb_path,
            adb_serial=config.device_serial,
            app_package=config.app_package,
            app_activity=config.app_activity,
            manual_observation_mode=config.manual_observation_mode,
            manual_observation_window_seconds=config.manual_observation_window_seconds,
            manual_observation_probe_interval_seconds=config.manual_observation_probe_interval_seconds,
            ark_ad_wait_seconds=config.ark_ad_wait_seconds,
            ark_skip_close_wait_seconds=config.ark_skip_close_wait_seconds,
            ark_return_wait_seconds=config.ark_return_wait_seconds,
            ark_esc_attempts=config.ark_esc_attempts,
            ark_esc_interval_seconds=config.ark_esc_interval_seconds,
            ark_post_watch_probe_count=config.ark_post_watch_probe_count,
            ark_post_watch_probe_interval_seconds=config.ark_post_watch_probe_interval_seconds,
            ark_post_watch_ui_dump_max_text_length=config.ark_post_watch_ui_dump_max_text_length,
            ad_boost_open_timeout_seconds=config.ad_boost_open_timeout_seconds,
            ad_boost_watch_timeout_seconds=config.ad_boost_watch_timeout_seconds,
            ad_boost_probe_interval_seconds=config.ad_boost_probe_interval_seconds,
            ad_boost_stabilization_seconds=config.ad_boost_stabilization_seconds,
            ad_boost_exit_timeout_seconds=config.ad_boost_exit_timeout_seconds,
            ad_boost_exit_ui_markers=config.ad_boost_exit_ui_markers,
            ad_boost_exit_keyevent=config.ad_boost_exit_keyevent,
            ad_boost_store_max_redirects=config.ad_boost_store_max_redirects,
            ad_boost_max_close_actions=config.ad_boost_max_close_actions,
        )

    def execute(self, action: str) -> ActuatorExecutionMetadata:
        normalized_action = action.strip()
        if not normalized_action:
            raise ActuatorExecutionError(
                "Action name must not be empty.",
                ActuatorExecutionMetadata(
                    actuator_type=self.actuator_type,
                    actuator_execution_status="FAILED",
                    actuator_command_count=0,
                    actuator_command_summary=[],
                ),
            )
        if normalized_action == "claim_ark_reward":
            if self._config.manual_observation_mode:
                return self._execute_manual_observation_claim_ark_reward()
            return self._execute_claim_ark_reward()
        if normalized_action == "activate_ad_boost":
            if self._config.manual_observation_mode:
                return self._execute_manual_observation_activate_ad_boost()
            return self._execute_activate_ad_boost()

        commands = self._commands_for_action(normalized_action)
        return self._execute_command_sequence(
            action=normalized_action,
            commands=commands,
        )

    def _execute_command_sequence(
        self,
        *,
        action: str,
        commands: list[list[str] | float | PostWatchProbeStep],
    ) -> ActuatorExecutionMetadata:
        attempted_summaries: list[str] = []
        probe_samples: list[ActuatorProbeSample] = []
        try:
            for command in commands:
                if isinstance(command, float):
                    self._sleep_fn(command)
                    continue
                if isinstance(command, PostWatchProbeStep):
                    probe_samples.extend(
                        self._collect_post_watch_probes(
                            wait_budget_seconds=command.wait_budget_seconds,
                        )
                    )
                    continue
                command_summary = self._summarize_command(command)
                attempted_summaries.append(command_summary)
                self._command_runner.run(command)
        except Exception as exc:
            failure_summary = attempted_summaries[-1] if attempted_summaries else action
            raise ActuatorExecutionError(
                f"ADB command execution failed: {failure_summary}",
                ActuatorExecutionMetadata(
                    actuator_type=self.actuator_type,
                    actuator_execution_status="FAILED",
                    actuator_command_count=len(attempted_summaries),
                    actuator_command_summary=list(attempted_summaries),
                    probe_samples=list(probe_samples),
                ),
            ) from exc

        return ActuatorExecutionMetadata(
            actuator_type=self.actuator_type,
            actuator_execution_status="COMPLETED",
            actuator_command_count=len(attempted_summaries),
            actuator_command_summary=list(attempted_summaries),
            probe_samples=list(probe_samples),
        )

    def _commands_for_action(self, action: str) -> list[list[str] | float | PostWatchProbeStep]:
        if action == "idle":
            return []
        raise ActuatorExecutionError(
            f"Unsupported action for ADB actuator: {action}",
            ActuatorExecutionMetadata(
                actuator_type=self.actuator_type,
                actuator_execution_status="FAILED",
                actuator_command_count=0,
                actuator_command_summary=[],
            ),
        )

    def _execute_activate_ad_boost(self) -> ActuatorExecutionMetadata:
        attempted_summaries: list[str] = []
        stage_events: list[ActuatorStageEvent] = []
        probe_samples: list[ActuatorProbeSample] = []
        watch_started_at: float | None = None
        
        try:
            launch_command = self._launch_command()
            if launch_command is not None:
                self._run_command(launch_command, attempted_summaries)

            self._run_command(
                self._adb_command(
                    "shell", "input", "tap",
                    str(self._config.activate_ad_boost_tap.x),
                    str(self._config.activate_ad_boost_tap.y)
                ),
                attempted_summaries,
            )
            entry_started_at = self._monotonic_fn()
            self._record_stage_event(
                stage_events, "boost_entry_tap", elapsed_started_at=None,
                detail=f"{self._config.activate_ad_boost_tap.x},{self._config.activate_ad_boost_tap.y}"
            )

            self._sleep_fn(self._config.ark_popup_wait_seconds)
            entry_probe = self._capture_probe_sample(
                entry_started_at,
                sample_context="post_entry",
                sample_reference_stage="boost_entry_tap",
            )
            probe_samples.append(entry_probe)

            self._run_command(
                self._adb_command(
                    "shell", "input", "tap",
                    str(self._config.activate_ad_boost_watch_tap.x),
                    str(self._config.activate_ad_boost_watch_tap.y)
                ),
                attempted_summaries,
            )
            watch_started_at = self._monotonic_fn()
            self._record_stage_event(
                stage_events, "boost_watch_tap", elapsed_started_at=watch_started_at,
                detail=f"{self._config.activate_ad_boost_watch_tap.x},{self._config.activate_ad_boost_watch_tap.y}"
            )

            ad_opened = False
            open_deadline = watch_started_at + self._config.ad_boost_open_timeout_seconds
            while self._monotonic_fn() < open_deadline:
                self._sleep_fn(self._config.ad_boost_probe_interval_seconds)
                probe = self._capture_probe_sample(
                    watch_started_at,
                    sample_context="ad_open_monitor",
                    sample_reference_stage="boost_watch_tap"
                )
                probe_samples.append(probe)
                
                if (
                    probe.focus_package != self._config.app_package
                    or (probe.focus_activity and "AdActivity" in probe.focus_activity)
                    or (probe.focus_activity and probe.focus_activity != self._config.app_activity)
                    or (probe.focus_package and "ad" in probe.focus_package.lower())
                ):
                    ad_opened = True
                    break

            if not ad_opened:
                raise RuntimeError("ad_open_timeout: Focus never left the game after watch tap.")

            self._record_stage_event(
                stage_events, "ad_opened", elapsed_started_at=watch_started_at
            )

            current_state = "ad"
            store_redirects_handled = 0
            ad_closes_handled = 0
            last_closed_ui_sha256 = None
            ad_active = True

            exit_monitor_start_time = self._monotonic_fn()
            exit_deadline = exit_monitor_start_time + self._config.ad_boost_exit_timeout_seconds
            
            while self._monotonic_fn() < exit_deadline:
                self._sleep_fn(self._config.ad_boost_probe_interval_seconds)
                probe = self._capture_probe_sample(
                    watch_started_at,
                    sample_context="ad_exit_monitor",
                    sample_reference_stage="ad_opened"
                )
                probe_samples.append(probe)

                # Natively returning? Require game package and activity, and NO ad overlay markers visible.
                if probe.focus_package == self._config.app_package and not (
                    probe.focus_activity and "AdActivity" in probe.focus_activity
                ) and probe.focus_activity == self._config.app_activity:
                    # Ensure it's not a brief flash overlay masking a real ad return
                    has_ad_markers = False
                    if probe.ui_text_excerpt:
                        has_ad_markers = any(m in probe.ui_text_excerpt for m in self._config.ad_boost_exit_ui_markers)
                    
                    if not has_ad_markers:
                        if current_state != "game":
                            self._record_stage_event(
                                stage_events, "returned_to_game", elapsed_started_at=watch_started_at
                            )
                            current_state = "game"
                        ad_active = False
                        break
                
                is_store = probe.focus_package == "com.android.vending" or (
                    probe.focus_activity and "MarketDeepLinkHandlerActivity" in probe.focus_activity
                )

                if is_store:
                    if current_state != "store":
                        self._record_stage_event(
                            stage_events, "store_redirect_detected", elapsed_started_at=watch_started_at
                        )
                        current_state = "store"
                        if store_redirects_handled < self._config.ad_boost_store_max_redirects:
                            self._run_command(
                                self._adb_command("shell", "input", "keyevent", "KEYCODE_BACK"),
                                attempted_summaries,
                            )
                            self._record_stage_event(
                                stage_events, "store_back_sent", elapsed_started_at=watch_started_at
                            )
                            store_redirects_handled += 1
                    continue
                
                # If neither store nor game, we consider it back to ad
                if current_state == "store" and not is_store:
                    self._record_stage_event(
                        stage_events, "returned_to_ad", elapsed_started_at=watch_started_at
                    )
                    current_state = "ad"
                
                if probe.ui_text_excerpt:
                    found_marker = next((m for m in self._config.ad_boost_exit_ui_markers if m in probe.ui_text_excerpt), None)
                    if found_marker and probe.ui_text_sha256 != last_closed_ui_sha256 and ad_closes_handled < self._config.ad_boost_max_close_actions:
                        self._record_stage_event(
                            stage_events, "ad_close_affordance_detected", elapsed_started_at=watch_started_at, detail=found_marker
                        )
                        self._run_command(
                            self._adb_command("shell", "input", "keyevent", self._config.ad_boost_exit_keyevent),
                            attempted_summaries,
                        )
                        self._record_stage_event(
                            stage_events, "ad_close_action_sent", elapsed_started_at=watch_started_at, detail=self._config.ad_boost_exit_keyevent
                        )
                        last_closed_ui_sha256 = probe.ui_text_sha256
                        ad_closes_handled += 1

            if ad_active:
                raise RuntimeError("ad_active_timeout: Ad exit affordance did not appear and game did not auto-return.")

            game_returned = True

            self._sleep_fn(self._config.ad_boost_stabilization_seconds)
            probe_samples.append(self._capture_probe_sample(
                watch_started_at,
                sample_context="post_ad_stabilization",
                sample_reference_stage="game_returned"
            ))

            self._record_stage_event(
                stage_events, "run_end", elapsed_started_at=watch_started_at,
                detail="actuation_complete"
            )

        except Exception as exc:
            self._record_stage_event(
                stage_events, "run_end", elapsed_started_at=watch_started_at,
                error=str(exc)
            )
            failure_summary = attempted_summaries[-1] if attempted_summaries else "activate_ad_boost"
            raise ActuatorExecutionError(
                f"ADB execution failed for activate_ad_boost: {failure_summary} ({exc})",
                ActuatorExecutionMetadata(
                    actuator_type=self.actuator_type,
                    actuator_execution_status="FAILED",
                    actuator_command_count=len(attempted_summaries),
                    actuator_command_summary=list(attempted_summaries),
                    stage_events=list(stage_events),
                    probe_samples=list(probe_samples),
                ),
            ) from exc

        return ActuatorExecutionMetadata(
            actuator_type=self.actuator_type,
            actuator_execution_status="COMPLETED",
            actuator_command_count=len(attempted_summaries),
            actuator_command_summary=list(attempted_summaries),
            stage_events=list(stage_events),
            probe_samples=list(probe_samples),
        )

    def _execute_manual_observation_activate_ad_boost(self) -> ActuatorExecutionMetadata:
        stage_events: list[ActuatorStageEvent] = []
        observation_started_at = self._monotonic_fn()
        self._record_stage_event(
            stage_events,
            "manual_observation_start",
            elapsed_started_at=observation_started_at,
            detail=(
                f"window={self._config.manual_observation_window_seconds},"
                f"interval={self._config.manual_observation_probe_interval_seconds},"
                "no_automated_inputs=true"
            ),
        )
        probe_samples = self._collect_timed_probes(
            started_at=observation_started_at,
            offsets_seconds=self._manual_observation_offsets(),
            sample_context="manual_observation",
            sample_reference_stage="manual_observation_start",
        )
        self._record_stage_event(
            stage_events,
            "manual_observation_end",
            elapsed_started_at=observation_started_at,
            detail="observation_complete",
        )
        return ActuatorExecutionMetadata(
            actuator_type=self.actuator_type,
            actuator_execution_status="COMPLETED",
            actuator_command_count=0,
            actuator_command_summary=[],
            stage_events=list(stage_events),
            probe_samples=list(probe_samples),
        )

    def _execute_claim_ark_reward(self) -> ActuatorExecutionMetadata:
        attempted_summaries: list[str] = []
        stage_events: list[ActuatorStageEvent] = []
        probe_samples: list[ActuatorProbeSample] = []
        entry_started_at: float | None = None
        watch_started_at: float | None = None
        try:
            launch_command = self._launch_command()
            if launch_command is not None:
                self._run_command(launch_command, attempted_summaries)

            self._run_command(
                self._adb_command(
                    "shell",
                    "input",
                    "tap",
                    str(self._config.claim_ark_reward_tap.x),
                    str(self._config.claim_ark_reward_tap.y),
                ),
                attempted_summaries,
            )
            entry_started_at = self._monotonic_fn()
            self._record_stage_event(
                stage_events,
                "ark_entry_tap",
                elapsed_started_at=None,
                detail=f"{self._config.claim_ark_reward_tap.x},{self._config.claim_ark_reward_tap.y}",
            )
            self._sleep_fn(self._config.ark_popup_wait_seconds)
            if entry_started_at is not None and self._config.ark_post_watch_probe_count > 0:
                entry_probe = self._capture_probe_sample(
                    entry_started_at,
                    sample_context="post_entry",
                    sample_reference_stage="ark_entry_tap",
                )
                probe_samples.append(entry_probe)
                self._record_stage_event(
                    stage_events,
                    "entry_observation",
                    elapsed_started_at=entry_started_at,
                    detail=self._summarize_entry_observation(entry_probe),
                )

            self._run_command(
                self._adb_command(
                    "shell",
                    "input",
                    "tap",
                    str(self._config.claim_ark_reward_watch_tap.x),
                    str(self._config.claim_ark_reward_watch_tap.y),
                ),
                attempted_summaries,
            )
            watch_started_at = self._monotonic_fn()
            self._record_stage_event(
                stage_events,
                "ark_watch_tap",
                elapsed_started_at=watch_started_at,
                detail=(
                    f"{self._config.claim_ark_reward_watch_tap.x},"
                    f"{self._config.claim_ark_reward_watch_tap.y}"
                ),
            )
            self._record_stage_event(
                stage_events,
                "probe_window_start",
                elapsed_started_at=watch_started_at,
                detail=(
                    f"count={self._config.ark_post_watch_probe_count},"
                    f"interval={self._config.ark_post_watch_probe_interval_seconds},"
                    f"wait_budget={self._config.ark_ad_wait_seconds}"
                ),
            )
            probe_samples.extend(
                self._collect_post_watch_probes(
                    wait_budget_seconds=self._config.ark_ad_wait_seconds,
                )
            )

            self._run_command(
                self._adb_command(
                    "shell",
                    "input",
                    "tap",
                    str(self._config.claim_ark_skip_tap.x),
                    str(self._config.claim_ark_skip_tap.y),
                ),
                attempted_summaries,
            )
            self._record_stage_event(
                stage_events,
                "ad_close_tap",
                elapsed_started_at=watch_started_at,
                detail=f"{self._config.claim_ark_skip_tap.x},{self._config.claim_ark_skip_tap.y}",
            )
            self._sleep_fn(self._config.ark_skip_close_wait_seconds)

            for attempt_index in range(1, self._config.ark_esc_attempts + 1):
                if watch_started_at is not None and self._config.ark_post_watch_probe_count > 0:
                    probe_samples.append(
                        self._capture_probe_sample(
                            watch_started_at,
                            sample_context="pre_esc",
                            sample_reference_stage="ark_watch_tap",
                            esc_attempt_index=attempt_index,
                        )
                    )
                self._run_command(
                    self._adb_command("shell", "input", "keyevent", "KEYCODE_ESCAPE"),
                    attempted_summaries,
                )
                self._record_stage_event(
                    stage_events,
                    f"esc_attempt_{attempt_index}",
                    elapsed_started_at=watch_started_at,
                )
                if watch_started_at is not None and self._config.ark_post_watch_probe_count > 0:
                    probe_samples.append(
                        self._capture_probe_sample(
                            watch_started_at,
                            sample_context="post_esc",
                            sample_reference_stage="ark_watch_tap",
                            esc_attempt_index=attempt_index,
                        )
                    )
                if attempt_index < self._config.ark_esc_attempts:
                    self._sleep_fn(self._config.ark_esc_interval_seconds)

            self._record_stage_event(
                stage_events,
                "post_esc_settle_start",
                elapsed_started_at=watch_started_at,
            )
            self._sleep_fn(self._config.ark_return_wait_seconds)
            if watch_started_at is not None and self._config.ark_post_watch_probe_count > 0:
                probe_samples.append(
                    self._capture_probe_sample(
                        watch_started_at,
                        sample_context="post_esc_settle",
                        sample_reference_stage="ark_watch_tap",
                    )
                )

            self._run_command(
                self._adb_command(
                    "shell",
                    "input",
                    "tap",
                    str(self._config.claim_ark_reward_final_claim_tap.x),
                    str(self._config.claim_ark_reward_final_claim_tap.y),
                ),
                attempted_summaries,
            )
            self._record_stage_event(
                stage_events,
                "claim_tap",
                elapsed_started_at=watch_started_at,
                detail=(
                    f"{self._config.claim_ark_reward_final_claim_tap.x},"
                    f"{self._config.claim_ark_reward_final_claim_tap.y}"
                ),
            )
            self._record_stage_event(
                stage_events,
                "run_end",
                elapsed_started_at=watch_started_at,
                detail="claim_sent",
            )
        except Exception as exc:
            self._record_stage_event(
                stage_events,
                "run_end",
                elapsed_started_at=watch_started_at,
                error=str(exc),
            )
            failure_summary = attempted_summaries[-1] if attempted_summaries else "claim_ark_reward"
            raise ActuatorExecutionError(
                f"ADB command execution failed: {failure_summary}",
                ActuatorExecutionMetadata(
                    actuator_type=self.actuator_type,
                    actuator_execution_status="FAILED",
                    actuator_command_count=len(attempted_summaries),
                    actuator_command_summary=list(attempted_summaries),
                    stage_events=list(stage_events),
                    probe_samples=list(probe_samples),
                ),
            ) from exc

        return ActuatorExecutionMetadata(
            actuator_type=self.actuator_type,
            actuator_execution_status="COMPLETED",
            actuator_command_count=len(attempted_summaries),
            actuator_command_summary=list(attempted_summaries),
            stage_events=list(stage_events),
            probe_samples=list(probe_samples),
        )

    def _execute_manual_observation_claim_ark_reward(self) -> ActuatorExecutionMetadata:
        stage_events: list[ActuatorStageEvent] = []
        observation_started_at = self._monotonic_fn()
        self._record_stage_event(
            stage_events,
            "manual_observation_start",
            elapsed_started_at=observation_started_at,
            detail=(
                f"window={self._config.manual_observation_window_seconds},"
                f"interval={self._config.manual_observation_probe_interval_seconds},"
                "no_automated_inputs=true"
            ),
        )
        probe_samples = self._collect_timed_probes(
            started_at=observation_started_at,
            offsets_seconds=self._manual_observation_offsets(),
            sample_context="manual_observation",
            sample_reference_stage="manual_observation_start",
        )
        self._record_stage_event(
            stage_events,
            "manual_observation_end",
            elapsed_started_at=observation_started_at,
            detail="observation_complete",
        )
        return ActuatorExecutionMetadata(
            actuator_type=self.actuator_type,
            actuator_execution_status="COMPLETED",
            actuator_command_count=0,
            actuator_command_summary=[],
            stage_events=list(stage_events),
            probe_samples=list(probe_samples),
        )

    def _collect_post_watch_probes(self, wait_budget_seconds: float) -> list[ActuatorProbeSample]:
        if self._config.ark_post_watch_probe_count <= 0:
            self._sleep_fn(wait_budget_seconds)
            return []

        started_at = self._monotonic_fn()
        offsets_seconds: list[float] = [0.0]
        for sample_index in range(1, self._config.ark_post_watch_probe_count):
            offsets_seconds.append(
                min(
                    wait_budget_seconds,
                    sample_index * self._config.ark_post_watch_probe_interval_seconds,
                )
            )
        samples = self._collect_timed_probes(
            started_at=started_at,
            offsets_seconds=offsets_seconds,
            sample_context="post_watch",
            sample_reference_stage="ark_watch_tap",
        )

        remaining_wait = wait_budget_seconds - (self._monotonic_fn() - started_at)
        if remaining_wait > 0:
            self._sleep_fn(remaining_wait)
        return samples

    def _collect_timed_probes(
        self,
        *,
        started_at: float,
        offsets_seconds: Sequence[float],
        sample_context: str,
        sample_reference_stage: str,
    ) -> list[ActuatorProbeSample]:
        samples: list[ActuatorProbeSample] = []
        for offset_seconds in offsets_seconds:
            remaining_before_sample = offset_seconds - (self._monotonic_fn() - started_at)
            if remaining_before_sample > 0:
                self._sleep_fn(remaining_before_sample)
            samples.append(
                self._capture_probe_sample(
                    started_at,
                    sample_context=sample_context,
                    sample_reference_stage=sample_reference_stage,
                )
            )
        return samples

    def _manual_observation_offsets(self) -> list[float]:
        offsets_seconds: list[float] = []
        next_offset = 0.0
        window = self._config.manual_observation_window_seconds
        interval = self._config.manual_observation_probe_interval_seconds
        while next_offset < window:
            offsets_seconds.append(round(next_offset, 3))
            next_offset += interval
        offsets_seconds.append(round(window, 3))
        return offsets_seconds

    def _capture_probe_sample(
        self,
        started_at: float,
        *,
        sample_context: str | None = None,
        sample_reference_stage: str | None = None,
        esc_attempt_index: int | None = None,
    ) -> ActuatorProbeSample:
        elapsed_seconds = round(self._monotonic_fn() - started_at, 3)
        focus_window: str | None = None
        focus_package: str | None = None
        focus_activity: str | None = None
        dumpsys_window_output: str | None = None
        dumpsys_activity_output: str | None = None
        ui_dump_xml: str | None = None
        ui_text_excerpt: str | None = None
        ui_text_sha256: str | None = None
        probe_errors: list[str] = []

        try:
            dumpsys_window_output = self._command_runner.capture(
                self._adb_command("shell", "dumpsys", "window", "windows")
            )
            focus_window, focus_package, focus_activity = self._parse_focus_snapshot(
                dumpsys_window_output
            )
        except Exception as exc:
            probe_errors.append(f"focus:{exc}")

        try:
            dumpsys_activity_output = self._command_runner.capture(
                self._adb_command("shell", "dumpsys", "activity", "activities")
            )
        except Exception as exc:
            probe_errors.append(f"activity:{exc}")

        try:
            self._command_runner.capture(
                self._adb_command("shell", "uiautomator", "dump", _UI_DUMP_REMOTE_PATH)
            )
            ui_dump_xml = self._command_runner.capture(
                self._adb_command("shell", "cat", _UI_DUMP_REMOTE_PATH)
            )
            ui_text_excerpt, ui_text_sha256 = self._extract_ui_text_summary(ui_dump_xml)
        except Exception as exc:
            probe_errors.append(f"ui:{exc}")

        return ActuatorProbeSample(
            sample_offset_seconds=elapsed_seconds,
            sample_context=sample_context,
            sample_reference_stage=sample_reference_stage,
            esc_attempt_index=esc_attempt_index,
            focus_window=focus_window,
            focus_package=focus_package,
            focus_activity=focus_activity,
            ui_text_excerpt=ui_text_excerpt,
            ui_text_sha256=ui_text_sha256,
            probe_error=" | ".join(probe_errors) if probe_errors else None,
            dumpsys_window_output=dumpsys_window_output,
            dumpsys_activity_output=dumpsys_activity_output,
            ui_dump_xml=ui_dump_xml,
        )

    def _parse_focus_snapshot(self, dumpsys_output: str) -> tuple[str | None, str | None, str | None]:
        for raw_line in dumpsys_output.splitlines():
            line = raw_line.strip()
            if "mCurrentFocus=" not in line and "mFocusedApp=" not in line:
                continue
            match = re.search(r" ([A-Za-z0-9._]+)/([A-Za-z0-9.$_/-]+)", line)
            if match is None:
                return line, None, None
            return line, match.group(1), match.group(2)
        return None, None, None

    def _extract_ui_text_summary(self, ui_dump: str) -> tuple[str | None, str | None]:
        xml_start = ui_dump.find("<?xml")
        if xml_start >= 0:
            ui_dump = ui_dump[xml_start:]
        root = ET.fromstring(ui_dump)
        text_tokens: list[str] = []
        seen_tokens: set[str] = set()
        for node in root.iter("node"):
            for attribute_name in ("text", "content-desc"):
                raw_value = node.attrib.get(attribute_name, "").strip()
                if not raw_value or raw_value in seen_tokens:
                    continue
                seen_tokens.add(raw_value)
                text_tokens.append(raw_value)
        if not text_tokens:
            return None, None
        joined_text = " | ".join(text_tokens)
        excerpt = joined_text[: self._config.ark_post_watch_ui_dump_max_text_length]
        digest = hashlib.sha256(joined_text.encode("utf-8")).hexdigest()
        return excerpt, digest

    def _summarize_entry_observation(self, sample: ActuatorProbeSample) -> str:
        classification = "entry_inconclusive"
        if sample.ui_text_excerpt == "Game view":
            classification = "entry_inconclusive_immediate_probe"
        elif sample.focus_activity is not None and "AdActivity" in sample.focus_activity:
            classification = "entry_reached_ad_flow"
        detail_parts = [classification]
        if sample.focus_activity is not None:
            detail_parts.append(f"focus_activity={sample.focus_activity}")
        if sample.ui_text_excerpt is not None:
            detail_parts.append(f"ui_text_excerpt={sample.ui_text_excerpt}")
        return "; ".join(detail_parts)

    def _run_command(self, command: list[str], attempted_summaries: list[str]) -> None:
        command_summary = self._summarize_command(command)
        attempted_summaries.append(command_summary)
        self._command_runner.run(command)

    def _record_stage_event(
        self,
        stage_events: list[ActuatorStageEvent],
        stage_name: str,
        *,
        elapsed_started_at: float | None,
        detail: str | None = None,
        error: str | None = None,
    ) -> None:
        elapsed_seconds = None
        if elapsed_started_at is not None:
            elapsed_seconds = round(self._monotonic_fn() - elapsed_started_at, 3)
        stage_events.append(
            ActuatorStageEvent(
                stage_name=stage_name,
                wall_clock_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                elapsed_seconds=elapsed_seconds,
                detail=detail,
                error=error,
            )
        )

    def _launch_command(self) -> list[str] | None:
        if self._config.app_package is None:
            return None
        if self._config.app_activity is not None:
            component = f"{self._config.app_package}/{self._config.app_activity}"
            return self._adb_command("shell", "am", "start", "-n", component)
        return self._adb_command(
            "shell",
            "monkey",
            "-p",
            self._config.app_package,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        )

    def _adb_command(self, *command_parts: str) -> list[str]:
        command = [self._config.adb_path]
        if self._config.device_serial is not None:
            command.extend(["-s", self._config.device_serial])
        command.extend(command_parts)
        return command

    def _summarize_command(self, command: Sequence[str]) -> str:
        return " ".join(command)

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
    AdPostRewardBranchPolicy,
    ActionActuator,
    ActuatorConfigSnapshot,
    ActuatorExecutionError,
    ActuatorExecutionMetadata,
    ActuatorProbeSample,
    ActuatorStageEvent,
    ActuatorSignalTrace,
)


_UI_DUMP_REMOTE_PATH = "/sdcard/ipm_bot_window_dump.xml"

AD_ACTIVITY_ALLOWLIST: tuple[str, ...] = (
    "com.google.android.gms.ads.AdActivity",
    "com.facebook.ads.AudienceNetworkActivity",
    "com.applovin.adview.AppLovinFullscreenActivity",
    "com.unity3d.ads.adplayer.FullScreenWebViewDisplay",
)

AD_ACTIVITY_SUBSTRINGS: tuple[str, ...] = (
    "adplayer",
    "ads",
)

STORE_ACTIVITY_ALLOWLIST: tuple[str, ...] = (
    "com.google.android.finsky.activities.MainActivity",
    "com.google.android.finsky.activities.MarketDeepLinkHandlerActivity",
    "com.android.vending.AssetBrowserActivity",
)


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
    ad_boost_probe_interval_seconds: float = 2.0
    ad_boost_stabilization_seconds: float = 3.0
    ad_boost_exit_timeout_seconds: float = 120.0
    ad_boost_exit_keyevent: str = "KEYCODE_BACK"
    ad_boost_store_max_redirects: int = 3
    ad_boost_verbose_signal_tracing: bool = False
    ad_boost_soft_exit_timeout_seconds: float = 25.0
    ad_boost_hard_exit_timeout_seconds: float = 45.0
    ad_exit_override_enabled: bool = False
    ad_exit_override_tap: TapPoint = TapPoint(x=948, y=84)
    ad_exit_override_delay_seconds: float = 12.0
    ad_exit_override_retry_count: int = 1
    ad_exit_override_interval_seconds: float = 1.0
    ad_exit_override_activity_allowlist: tuple[str, ...] = ()
    ad_post_reward_claim_tap: TapPoint = TapPoint(x=454, y=975)
    ad_post_reward_claim_retry_count: int = 1
    ad_post_reward_claim_interval_seconds: float = 1.0
    ad_post_reward_claim_settle_seconds: float = 2.0
    ad_post_reward_auto_claim_enabled: bool = False
    ad_post_reward_branch_policy: AdPostRewardBranchPolicy = "disabled"
    ad_post_reward_choice_tap: TapPoint = TapPoint(x=454, y=875)
    ad_post_reward_choice_retry_count: int = 1
    ad_post_reward_choice_interval_seconds: float = 1.0
    ad_post_reward_choice_settle_seconds: float = 2.0

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
        if self.ad_boost_probe_interval_seconds <= 0:
            raise ValueError("ad_boost_probe_interval_seconds must be greater than zero.")
        if self.ad_boost_stabilization_seconds < 0:
            raise ValueError("ad_boost_stabilization_seconds must be non-negative.")
        if self.ad_boost_exit_timeout_seconds <= 0:
            raise ValueError("ad_boost_exit_timeout_seconds must be greater than zero.")
        if not self.ad_boost_exit_keyevent:
            raise ValueError("ad_boost_exit_keyevent must not be blank.")
        if self.ad_boost_store_max_redirects < 0:
            raise ValueError("ad_boost_store_max_redirects must be non-negative.")
        if self.ad_boost_soft_exit_timeout_seconds <= 0:
            raise ValueError("ad_boost_soft_exit_timeout_seconds must be greater than zero.")
        if self.ad_boost_hard_exit_timeout_seconds <= 0:
            raise ValueError("ad_boost_hard_exit_timeout_seconds must be greater than zero.")
        if self.ad_exit_override_delay_seconds < 0:
            raise ValueError("ad_exit_override_delay_seconds must be non-negative.")
        if self.ad_exit_override_retry_count < 0:
            raise ValueError("ad_exit_override_retry_count must be non-negative.")
        if self.ad_exit_override_interval_seconds < 0:
            raise ValueError("ad_exit_override_interval_seconds must be non-negative.")
        if any(not activity for activity in self.ad_exit_override_activity_allowlist):
            raise ValueError("ad_exit_override_activity_allowlist entries must not be empty.")
        if self.ad_post_reward_claim_retry_count < 0:
            raise ValueError("ad_post_reward_claim_retry_count must be non-negative.")
        if self.ad_post_reward_claim_interval_seconds < 0:
            raise ValueError("ad_post_reward_claim_interval_seconds must be non-negative.")
        if self.ad_post_reward_claim_settle_seconds < 0:
            raise ValueError("ad_post_reward_claim_settle_seconds must be non-negative.")
        if self.ad_post_reward_branch_policy not in {"disabled", "single_choice_default"}:
            raise ValueError("ad_post_reward_branch_policy must be one of the supported values.")
        if self.ad_post_reward_choice_retry_count < 0:
            raise ValueError("ad_post_reward_choice_retry_count must be non-negative.")
        if self.ad_post_reward_choice_interval_seconds < 0:
            raise ValueError("ad_post_reward_choice_interval_seconds must be non-negative.")
        if self.ad_post_reward_choice_settle_seconds < 0:
            raise ValueError("ad_post_reward_choice_settle_seconds must be non-negative.")


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
            ad_boost_probe_interval_seconds=config.ad_boost_probe_interval_seconds,
            ad_boost_stabilization_seconds=config.ad_boost_stabilization_seconds,
            ad_boost_exit_timeout_seconds=config.ad_boost_exit_timeout_seconds,
            ad_boost_exit_keyevent=config.ad_boost_exit_keyevent,
            ad_boost_store_max_redirects=config.ad_boost_store_max_redirects,
            ad_boost_verbose_signal_tracing=config.ad_boost_verbose_signal_tracing,
            ad_boost_soft_exit_timeout_seconds=config.ad_boost_soft_exit_timeout_seconds,
            ad_boost_hard_exit_timeout_seconds=config.ad_boost_hard_exit_timeout_seconds,
            ad_exit_override_enabled=config.ad_exit_override_enabled,
            ad_exit_override_tap=f"{config.ad_exit_override_tap.x},{config.ad_exit_override_tap.y}",
            ad_exit_override_delay_seconds=config.ad_exit_override_delay_seconds,
            ad_exit_override_retry_count=config.ad_exit_override_retry_count,
            ad_exit_override_interval_seconds=config.ad_exit_override_interval_seconds,
            ad_exit_override_activity_allowlist=tuple(config.ad_exit_override_activity_allowlist),
            ad_post_reward_claim_tap=f"{config.ad_post_reward_claim_tap.x},{config.ad_post_reward_claim_tap.y}",
            ad_post_reward_claim_retry_count=config.ad_post_reward_claim_retry_count,
            ad_post_reward_claim_interval_seconds=config.ad_post_reward_claim_interval_seconds,
            ad_post_reward_claim_settle_seconds=config.ad_post_reward_claim_settle_seconds,
            ad_post_reward_auto_claim_enabled=config.ad_post_reward_auto_claim_enabled,
            ad_post_reward_branch_policy=config.ad_post_reward_branch_policy,
            ad_post_reward_choice_tap=f"{config.ad_post_reward_choice_tap.x},{config.ad_post_reward_choice_tap.y}",
            ad_post_reward_choice_retry_count=config.ad_post_reward_choice_retry_count,
            ad_post_reward_choice_interval_seconds=config.ad_post_reward_choice_interval_seconds,
            ad_post_reward_choice_settle_seconds=config.ad_post_reward_choice_settle_seconds,
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
        signal_traces: list[ActuatorSignalTrace] = []
        claim_tap_timestamps: list[float] = []
        branch_choice_tap_timestamps: list[float] = []
        ad_exit_override_tap_timestamps: list[float] = []
        ad_exit_override_activity: str | None = None
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
                include_ui_dump=False,
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
            ad_opened_at: float | None = None
            open_deadline = watch_started_at + self._config.ad_boost_open_timeout_seconds
            while self._monotonic_fn() < open_deadline:
                self._sleep_fn(self._config.ad_boost_probe_interval_seconds)
                probe = self._capture_probe_sample(
                    watch_started_at,
                    sample_context="ad_open_monitor",
                    sample_reference_stage="boost_watch_tap",
                    include_ui_dump=False,
                )
                probe_samples.append(probe)
                
                focus_classification = self._classify_focus_activity(
                    focus_package=probe.focus_package,
                    focus_activity=probe.focus_activity,
                )
                if focus_classification in {"ad", "store"}:
                    ad_opened = True
                    ad_opened_at = self._monotonic_fn()
                    break

            if not ad_opened:
                raise RuntimeError("ad_open_timeout: Focus never left the game after watch tap.")

            self._record_stage_event(
                stage_events, "ad_opened", elapsed_started_at=watch_started_at
            )

            current_state = "ad"
            store_redirects_handled = 0
            ad_soft_timeouts_handled = 0
            ad_hard_timeouts_handled = 0
            ad_exit_override_attempted = False
            ad_active = True

            exit_monitor_start_time = self._monotonic_fn()
            exit_deadline = exit_monitor_start_time + self._config.ad_boost_exit_timeout_seconds
            
            def _append_trace(
                t_probe: ActuatorProbeSample,
                t_is_ad: bool,
                t_is_game: bool,
                t_is_store: bool,
                t_is_playable: bool,
                t_has_exit: bool | None,
                t_has_overlay: bool,
                t_action: str,
                t_reason: str,
            ) -> None:
                trace = ActuatorSignalTrace(
                    timestamp_offset_seconds=self._monotonic_fn() - watch_started_at,
                    stage="ad_exit_monitor",
                    focus_activity=t_probe.focus_activity,
                    focus_package=t_probe.focus_package,
                    ui_text_excerpt=t_probe.ui_text_excerpt,
                    is_ad_activity=t_is_ad,
                    is_playable_ad=t_is_playable,
                    is_store=t_is_store,
                    is_game_activity=t_is_game,
                    has_exit_marker=t_has_exit,
                    has_ad_markers=t_has_overlay,
                    action_taken=t_action,
                    action_reason=t_reason,
                )
                signal_traces.append(trace)
                if self._config.ad_boost_verbose_signal_tracing:
                    print(
                        f"[{trace.timestamp_offset_seconds:05.1f}s] {trace.stage} "
                        f"act={trace.focus_activity} pkg={trace.focus_package} "
                        f"ad={trace.is_ad_activity} play={trace.is_playable_ad} game={trace.is_game_activity} store={trace.is_store} "
                        f"overlay={trace.has_ad_markers} exit_m={trace.has_exit_marker} "
                        f"-> {trace.action_taken} ({trace.action_reason})"
                    )

            while self._monotonic_fn() < exit_deadline:
                self._sleep_fn(self._config.ad_boost_probe_interval_seconds)
                probe = self._capture_probe_sample(
                    watch_started_at,
                    sample_context="ad_exit_monitor",
                    sample_reference_stage="ad_opened",
                    include_ui_dump=False,
                )
                probe_samples.append(probe)

                focus_classification = self._classify_focus_activity(
                    focus_package=probe.focus_package,
                    focus_activity=probe.focus_activity,
                )
                is_game_activity = focus_classification == "game"
                is_ad_activity = focus_classification == "ad"
                is_store = focus_classification == "store"

                if is_game_activity:
                    _append_trace(
                        probe,
                        is_ad_activity,
                        is_game_activity,
                        is_store,
                        False,
                        None,
                        False,
                        "NONE",
                        "natively_returned",
                    )
                    if current_state != "game":
                        self._record_stage_event(
                            stage_events, "returned_to_game", elapsed_started_at=watch_started_at
                        )
                        current_state = "game"
                    ad_active = False
                    break
                
                if is_store:
                    if current_state != "store":
                        self._record_stage_event(
                            stage_events, "store_redirect_detected", elapsed_started_at=watch_started_at
                        )
                        current_state = "store"
                        
                    if store_redirects_handled < self._config.ad_boost_store_max_redirects:
                        _append_trace(
                            probe,
                            is_ad_activity,
                            is_game_activity,
                            is_store,
                            False,
                            None,
                            False,
                            self._config.ad_boost_exit_keyevent,
                            "store_escape",
                        )
                        self._run_command(
                            self._adb_command("shell", "input", "keyevent", self._config.ad_boost_exit_keyevent),
                            attempted_summaries,
                        )
                        self._record_stage_event(
                            stage_events, "store_back_sent", elapsed_started_at=watch_started_at
                        )
                        store_redirects_handled += 1
                    else:
                        _append_trace(
                            probe,
                            is_ad_activity,
                            is_game_activity,
                            is_store,
                            False,
                            None,
                            False,
                            "NONE",
                            "store_escape_limit_reached",
                        )
                    continue
                
                if current_state == "store" and not is_store:
                    self._record_stage_event(
                        stage_events, "returned_to_ad", elapsed_started_at=watch_started_at
                    )
                    current_state = "ad"

                elapsed_since_watch = self._monotonic_fn() - watch_started_at
                elapsed_since_ad_open = (
                    0.0 if ad_opened_at is None else self._monotonic_fn() - ad_opened_at
                )
                total_timeouts_handled = ad_soft_timeouts_handled + ad_hard_timeouts_handled

                if (
                    is_ad_activity
                    and not ad_exit_override_attempted
                    and self._config.ad_exit_override_enabled
                    and elapsed_since_ad_open >= self._config.ad_exit_override_delay_seconds
                    and self._focus_activity_matches_exit_override_allowlist(probe.focus_activity)
                ):
                    ad_exit_override_attempted = True
                    ad_exit_override_activity = probe.focus_activity
                    ad_exit_override_tap_timestamps.extend(
                        self._execute_ad_exit_override_sequence(
                            attempted_summaries=attempted_summaries,
                            stage_events=stage_events,
                            signal_traces=signal_traces,
                            watch_started_at=watch_started_at,
                            focus_probe=probe,
                        )
                    )
                    continue

                if (
                    is_ad_activity
                    and
                    not ad_exit_override_attempted
                    and elapsed_since_watch >= self._config.ad_boost_soft_exit_timeout_seconds
                    and ad_soft_timeouts_handled == 0
                    and total_timeouts_handled < 2
                ):
                    _append_trace(
                        probe,
                        is_ad_activity,
                        is_game_activity,
                        is_store,
                        False,
                        None,
                        False,
                        self._config.ad_boost_exit_keyevent,
                        "soft_timeout_escape",
                    )
                    self._record_stage_event(
                        stage_events, "ad_soft_timeout_back_sent", elapsed_started_at=watch_started_at
                    )
                    self._run_command(
                        self._adb_command("shell", "input", "keyevent", self._config.ad_boost_exit_keyevent),
                        attempted_summaries,
                    )
                    ad_soft_timeouts_handled += 1

                elif (
                    is_ad_activity
                    and elapsed_since_watch >= self._config.ad_boost_hard_exit_timeout_seconds
                    and ad_hard_timeouts_handled == 0
                    and total_timeouts_handled < 2
                ):
                    _append_trace(
                        probe,
                        is_ad_activity,
                        is_game_activity,
                        is_store,
                        False,
                        None,
                        False,
                        self._config.ad_boost_exit_keyevent,
                        "hard_timeout_escape",
                    )
                    self._record_stage_event(
                        stage_events, "ad_hard_timeout_back_sent", elapsed_started_at=watch_started_at
                    )
                    self._run_command(
                        self._adb_command("shell", "input", "keyevent", self._config.ad_boost_exit_keyevent),
                        attempted_summaries,
                    )
                    ad_hard_timeouts_handled += 1

                else:
                    _append_trace(
                        probe,
                        is_ad_activity,
                        is_game_activity,
                        is_store,
                        False,
                        None,
                        False,
                        "NONE",
                        "monitoring" if is_ad_activity else "unknown_focus",
                    )

            if ad_active:
                raise RuntimeError("ad_active_timeout: Ad exit affordance did not appear and game did not auto-return.")

            game_returned = True

            self._sleep_fn(self._config.ad_boost_stabilization_seconds)
            stabilization_probe = self._capture_probe_sample(
                watch_started_at,
                sample_context="post_ad_stabilization",
                sample_reference_stage="game_returned",
                include_ui_dump=False,
            )
            probe_samples.append(stabilization_probe)

            if self._config.ad_post_reward_auto_claim_enabled:
                claim_tap_timestamps.extend(
                    self._execute_post_ad_claim_sequence(
                        attempted_summaries=attempted_summaries,
                        stage_events=stage_events,
                        signal_traces=signal_traces,
                        watch_started_at=watch_started_at,
                        stabilization_probe=stabilization_probe,
                    )
                )
                if self._config.ad_post_reward_branch_policy == "single_choice_default":
                    branch_choice_tap_timestamps.extend(
                        self._execute_post_ad_branch_choice_sequence(
                            attempted_summaries=attempted_summaries,
                            stage_events=stage_events,
                            signal_traces=signal_traces,
                            watch_started_at=watch_started_at,
                            stabilization_probe=stabilization_probe,
                        )
                    )

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
                    signal_traces=list(signal_traces),
                    claim_attempted=bool(claim_tap_timestamps),
                    number_of_claim_taps=len(claim_tap_timestamps),
                    claim_tap_timestamps=list(claim_tap_timestamps),
                    branch_attempted=bool(branch_choice_tap_timestamps),
                    branch_policy=self._config.ad_post_reward_branch_policy,
                    branch_choice_tap_count=len(branch_choice_tap_timestamps),
                    branch_choice_tap_timestamps=list(branch_choice_tap_timestamps),
                    ad_exit_override_attempted=bool(ad_exit_override_tap_timestamps),
                    ad_exit_override_tap_count=len(ad_exit_override_tap_timestamps),
                    ad_exit_override_tap_timestamps=list(ad_exit_override_tap_timestamps),
                    ad_exit_override_activity=ad_exit_override_activity,
                ),
            ) from exc

        return ActuatorExecutionMetadata(
            actuator_type=self.actuator_type,
            actuator_execution_status="COMPLETED",
            actuator_command_count=len(attempted_summaries),
            actuator_command_summary=list(attempted_summaries),
            stage_events=list(stage_events),
            probe_samples=list(probe_samples),
            signal_traces=list(signal_traces),
            claim_attempted=bool(claim_tap_timestamps),
            number_of_claim_taps=len(claim_tap_timestamps),
            claim_tap_timestamps=list(claim_tap_timestamps),
            branch_attempted=bool(branch_choice_tap_timestamps),
            branch_policy=self._config.ad_post_reward_branch_policy,
            branch_choice_tap_count=len(branch_choice_tap_timestamps),
            branch_choice_tap_timestamps=list(branch_choice_tap_timestamps),
            ad_exit_override_attempted=bool(ad_exit_override_tap_timestamps),
            ad_exit_override_tap_count=len(ad_exit_override_tap_timestamps),
            ad_exit_override_tap_timestamps=list(ad_exit_override_tap_timestamps),
            ad_exit_override_activity=ad_exit_override_activity,
        )

    def _execute_post_ad_claim_sequence(
        self,
        *,
        attempted_summaries: list[str],
        stage_events: list[ActuatorStageEvent],
        signal_traces: list[ActuatorSignalTrace],
        watch_started_at: float,
        stabilization_probe: ActuatorProbeSample,
    ) -> list[float]:
        claim_tap_timestamps: list[float] = []
        tap_detail = (
            f"{self._config.ad_post_reward_claim_tap.x},"
            f"{self._config.ad_post_reward_claim_tap.y}"
        )
        for attempt_index in range(1, self._config.ad_post_reward_claim_retry_count + 1):
            claim_timestamp = round(self._monotonic_fn() - watch_started_at, 3)
            claim_tap_timestamps.append(claim_timestamp)
            self._run_command(
                self._adb_command(
                    "shell",
                    "input",
                    "tap",
                    str(self._config.ad_post_reward_claim_tap.x),
                    str(self._config.ad_post_reward_claim_tap.y),
                ),
                attempted_summaries,
            )
            self._record_stage_event(
                stage_events,
                "post_ad_reward_claim_tap",
                elapsed_started_at=watch_started_at,
                detail=f"attempt={attempt_index};tap={tap_detail}",
            )
            signal_traces.append(
                ActuatorSignalTrace(
                    timestamp_offset_seconds=claim_timestamp,
                    stage="post_ad_reward_claim",
                    focus_activity=stabilization_probe.focus_activity,
                    focus_package=stabilization_probe.focus_package,
                    ui_text_excerpt=None,
                    is_ad_activity=False,
                    is_playable_ad=False,
                    is_store=False,
                    is_game_activity=True,
                    has_exit_marker=None,
                    has_ad_markers=False,
                    action_taken=tap_detail,
                    action_reason=f"bounded_claim_tap_{attempt_index}",
                )
            )
            if attempt_index < self._config.ad_post_reward_claim_retry_count:
                self._sleep_fn(self._config.ad_post_reward_claim_interval_seconds)
        if claim_tap_timestamps and self._config.ad_post_reward_claim_settle_seconds > 0:
            self._record_stage_event(
                stage_events,
                "post_ad_reward_claim_settle",
                elapsed_started_at=watch_started_at,
                detail=f"seconds={self._config.ad_post_reward_claim_settle_seconds}",
            )
            self._sleep_fn(self._config.ad_post_reward_claim_settle_seconds)
        return claim_tap_timestamps

    def _execute_post_ad_branch_choice_sequence(
        self,
        *,
        attempted_summaries: list[str],
        stage_events: list[ActuatorStageEvent],
        signal_traces: list[ActuatorSignalTrace],
        watch_started_at: float,
        stabilization_probe: ActuatorProbeSample,
    ) -> list[float]:
        branch_tap_timestamps: list[float] = []
        tap_detail = (
            f"{self._config.ad_post_reward_choice_tap.x},"
            f"{self._config.ad_post_reward_choice_tap.y}"
        )
        for attempt_index in range(1, self._config.ad_post_reward_choice_retry_count + 1):
            branch_timestamp = round(self._monotonic_fn() - watch_started_at, 3)
            branch_tap_timestamps.append(branch_timestamp)
            self._run_command(
                self._adb_command(
                    "shell",
                    "input",
                    "tap",
                    str(self._config.ad_post_reward_choice_tap.x),
                    str(self._config.ad_post_reward_choice_tap.y),
                ),
                attempted_summaries,
            )
            self._record_stage_event(
                stage_events,
                "post_ad_reward_branch_choice_tap",
                elapsed_started_at=watch_started_at,
                detail=(
                    f"policy={self._config.ad_post_reward_branch_policy};"
                    f"attempt={attempt_index};tap={tap_detail}"
                ),
            )
            signal_traces.append(
                ActuatorSignalTrace(
                    timestamp_offset_seconds=branch_timestamp,
                    stage="post_ad_reward_branch_choice",
                    focus_activity=stabilization_probe.focus_activity,
                    focus_package=stabilization_probe.focus_package,
                    ui_text_excerpt=None,
                    is_ad_activity=False,
                    is_playable_ad=False,
                    is_store=False,
                    is_game_activity=True,
                    has_exit_marker=None,
                    has_ad_markers=False,
                    action_taken=tap_detail,
                    action_reason=f"bounded_branch_choice_tap_{attempt_index}",
                )
            )
            if attempt_index < self._config.ad_post_reward_choice_retry_count:
                self._sleep_fn(self._config.ad_post_reward_choice_interval_seconds)
        if branch_tap_timestamps and self._config.ad_post_reward_choice_settle_seconds > 0:
            self._record_stage_event(
                stage_events,
                "post_ad_reward_branch_choice_settle",
                elapsed_started_at=watch_started_at,
                detail=(
                    f"policy={self._config.ad_post_reward_branch_policy};"
                    f"seconds={self._config.ad_post_reward_choice_settle_seconds}"
                ),
            )
            self._sleep_fn(self._config.ad_post_reward_choice_settle_seconds)
        return branch_tap_timestamps

    def _execute_ad_exit_override_sequence(
        self,
        *,
        attempted_summaries: list[str],
        stage_events: list[ActuatorStageEvent],
        signal_traces: list[ActuatorSignalTrace],
        watch_started_at: float,
        focus_probe: ActuatorProbeSample,
    ) -> list[float]:
        override_tap_timestamps: list[float] = []
        tap_detail = f"{self._config.ad_exit_override_tap.x},{self._config.ad_exit_override_tap.y}"
        for attempt_index in range(1, self._config.ad_exit_override_retry_count + 1):
            tap_timestamp = round(self._monotonic_fn() - watch_started_at, 3)
            override_tap_timestamps.append(tap_timestamp)
            self._run_command(
                self._adb_command(
                    "shell",
                    "input",
                    "tap",
                    str(self._config.ad_exit_override_tap.x),
                    str(self._config.ad_exit_override_tap.y),
                ),
                attempted_summaries,
            )
            self._record_stage_event(
                stage_events,
                "ad_exit_override_tap",
                elapsed_started_at=watch_started_at,
                detail=(
                    f"activity={focus_probe.focus_activity};"
                    f"attempt={attempt_index};tap={tap_detail}"
                ),
            )
            signal_traces.append(
                ActuatorSignalTrace(
                    timestamp_offset_seconds=tap_timestamp,
                    stage="ad_exit_override",
                    focus_activity=focus_probe.focus_activity,
                    focus_package=focus_probe.focus_package,
                    ui_text_excerpt=None,
                    is_ad_activity=True,
                    is_playable_ad=False,
                    is_store=False,
                    is_game_activity=False,
                    has_exit_marker=None,
                    has_ad_markers=False,
                    action_taken=tap_detail,
                    action_reason=f"bounded_ad_exit_override_tap_{attempt_index}",
                )
            )
            if attempt_index < self._config.ad_exit_override_retry_count:
                self._sleep_fn(self._config.ad_exit_override_interval_seconds)
        return override_tap_timestamps

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
        claim_tap_timestamps: list[float] = []
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
                    include_ui_dump=False,
                )
                probe_samples.append(entry_probe)

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
                    include_ui_dump=False,
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
                            include_ui_dump=False,
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
                            include_ui_dump=False,
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
                        include_ui_dump=False,
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
            claim_tap_timestamps.append(round(self._monotonic_fn() - watch_started_at, 3))
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
                    claim_attempted=bool(claim_tap_timestamps),
                    number_of_claim_taps=len(claim_tap_timestamps),
                    claim_tap_timestamps=list(claim_tap_timestamps),
                ),
            ) from exc

        return ActuatorExecutionMetadata(
            actuator_type=self.actuator_type,
            actuator_execution_status="COMPLETED",
            actuator_command_count=len(attempted_summaries),
            actuator_command_summary=list(attempted_summaries),
            stage_events=list(stage_events),
            probe_samples=list(probe_samples),
            claim_attempted=bool(claim_tap_timestamps),
            number_of_claim_taps=len(claim_tap_timestamps),
            claim_tap_timestamps=list(claim_tap_timestamps),
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

    def _collect_post_watch_probes(
        self,
        wait_budget_seconds: float,
        *,
        include_ui_dump: bool = True,
    ) -> list[ActuatorProbeSample]:
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
            include_ui_dump=include_ui_dump,
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
        include_ui_dump: bool = True,
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
                    include_ui_dump=include_ui_dump,
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
        include_ui_dump: bool = True,
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

        if include_ui_dump:
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

    def _focus_activity_matches_exit_override_allowlist(self, focus_activity: str | None) -> bool:
        if focus_activity is None:
            return False
        return any(
            allowlisted_activity == focus_activity
            for allowlisted_activity in self._config.ad_exit_override_activity_allowlist
        )

    def _focus_activity_is_allowlisted_ad(self, focus_activity: str | None) -> bool:
        if focus_activity is None:
            return False
        if any(
            allowlisted_activity == focus_activity
            for allowlisted_activity in AD_ACTIVITY_ALLOWLIST
        ):
            return True
        focus_activity_lower = focus_activity.lower()
        return any(token in focus_activity_lower for token in AD_ACTIVITY_SUBSTRINGS)

    def _focus_activity_is_allowlisted_store(self, focus_activity: str | None) -> bool:
        if focus_activity is None:
            return False
        return any(
            allowlisted_activity == focus_activity
            for allowlisted_activity in STORE_ACTIVITY_ALLOWLIST
        )

    def _classify_focus_activity(
        self,
        *,
        focus_package: str | None,
        focus_activity: str | None,
    ) -> str:
        if (
            focus_package == self._config.app_package
            and focus_activity == self._config.app_activity
        ):
            return "game"
        if self._focus_activity_is_allowlisted_store(focus_activity):
            return "store"
        if self._focus_activity_is_allowlisted_ad(focus_activity):
            return "ad"
        return "unknown"

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

"""ADB-backed actuator scaffold behind the ActionActuator boundary."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
from typing import Protocol, Sequence

from .boundary import ActionActuator


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
    activate_ad_boost_tap: TapPoint = TapPoint(x=540, y=960)
    claim_ark_reward_tap: TapPoint = TapPoint(x=540, y=780)

    def __post_init__(self) -> None:
        if not self.adb_path.strip():
            raise ValueError("adb_path must not be empty.")
        if self.app_activity and not self.app_package:
            raise ValueError("app_package is required when app_activity is configured.")


class CommandRunner(Protocol):
    """Narrow command-execution boundary for ADB command sequences."""

    def run(self, command: Sequence[str]) -> None:
        """Execute one command or raise on failure."""


class SubprocessCommandRunner(CommandRunner):
    """Default subprocess-backed command runner for ADB commands."""

    def run(self, command: Sequence[str]) -> None:
        subprocess.run(list(command), check=True)


class AdbActionActuator(ActionActuator):
    """Concrete actuator that emits explicit ADB command sequences."""

    def __init__(
        self,
        config: AdbActuatorConfig,
        command_runner: CommandRunner,
    ) -> None:
        self._config = config
        self._command_runner = command_runner

    def execute(self, action: str) -> None:
        normalized_action = action.strip()
        if not normalized_action:
            raise ValueError("Action name must not be empty.")

        for command in self._commands_for_action(normalized_action):
            self._command_runner.run(command)

    def _commands_for_action(self, action: str) -> list[list[str]]:
        if action == "idle":
            return []
        if action == "activate_ad_boost":
            return self._action_commands(self._config.activate_ad_boost_tap)
        if action == "claim_ark_reward":
            return self._action_commands(self._config.claim_ark_reward_tap)
        raise ValueError(f"Unsupported action for ADB actuator: {action}")

    def _action_commands(self, tap_point: TapPoint) -> list[list[str]]:
        commands: list[list[str]] = []
        launch_command = self._launch_command()
        if launch_command is not None:
            commands.append(launch_command)
        commands.append(self._adb_command("shell", "input", "tap", str(tap_point.x), str(tap_point.y)))
        return commands

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

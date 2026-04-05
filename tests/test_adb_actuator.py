from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.actuator.adb import AdbActionActuator, AdbActuatorConfig, TapPoint
from ipm_bot.actuator.boundary import ActuatorExecutionError


class AdbActuatorTests(unittest.TestCase):
    def test_activate_ad_boost_monitors_ad_flow_and_succeeds(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_ad = (
            "mCurrentFocus=Window{42 u0 com.google.android.gms/com.google.android.gms.ads.AdActivity}"
        )
        runner = RecordingCommandRunner(
            captured_outputs={
                "adb -s emulator-5554 shell dumpsys window windows": dumpsys_window_game,
                "adb -s emulator-5554 shell dumpsys activity activities": "ACTIVITY MANAGER ACTIVITIES",
                "adb -s emulator-5554 shell uiautomator dump /sdcard/ipm_bot_window_dump.xml": "dumped",
                "adb -s emulator-5554 shell cat /sdcard/ipm_bot_window_dump.xml": '<?xml version="1.0" encoding="UTF-8"?><hierarchy/>',
            }
        )
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                activate_ad_boost_watch_tap=TapPoint(x=333, y=555),
                ark_popup_wait_seconds=1.5,
                ad_boost_open_timeout_seconds=10.0,
                ad_boost_probe_interval_seconds=2.0,
                ad_boost_stabilization_seconds=3.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        # We will dynamically change the mock output based on the clock
        # 1.5s popup wait + taps
        # at t=1.5 we tap watch.
        # open loop starts. Ad opens at t=3.5.
        # return loop starts. Game returns at t=7.5.
        # stabilization 3.0.
        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                if clock.monotonic() < 3.0:
                    return dumpsys_window_game
                if clock.monotonic() < 7.0:
                    return dumpsys_window_ad
                return dumpsys_window_game
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return '<?xml version="1.0" encoding="UTF-8"?><hierarchy/>'
        
        runner.capture = dynamic_capture

        metadata = actuator.execute("activate_ad_boost")

        self.assertEqual(
            runner.commands,
            [
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "am",
                    "start",
                    "-n",
                    "com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "111",
                    "222",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "333",
                    "555",
                ],
            ],
        )
        self.assertEqual(metadata.actuator_type, "adb")
        self.assertEqual(metadata.actuator_execution_status, "COMPLETED")
        self.assertEqual(metadata.actuator_command_count, 3)
        self.assertEqual(sleeper.durations, [1.5, 2.0, 2.0, 2.0, 3.0])
        self.assertFalse(metadata.ad_exit_override_attempted)
        self.assertEqual(metadata.ad_exit_override_tap_count, 0)
        self.assertEqual(metadata.ad_exit_override_tap_timestamps, [])
        self.assertIsNone(metadata.ad_exit_override_activity)
        self.assertEqual(
            [e.stage_name for e in metadata.stage_events],
            ["boost_entry_tap", "boost_watch_tap", "ad_opened", "returned_to_game", "run_end"]
        )
        self.assertEqual(
            [p.sample_context for p in metadata.probe_samples],
            ["post_entry", "ad_open_monitor", "ad_exit_monitor", "ad_exit_monitor", "post_ad_stabilization"]
        )

    def test_activate_ad_boost_monitors_same_package_ad_flow_and_succeeds(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_same_package_ad = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.facebook.ads.AudienceNetworkActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                activate_ad_boost_watch_tap=TapPoint(x=333, y=555),
                ark_popup_wait_seconds=1.5,
                ad_boost_open_timeout_seconds=10.0,
                ad_boost_probe_interval_seconds=2.0,
                ad_boost_stabilization_seconds=3.0,
                ad_boost_exit_timeout_seconds=10.0,
                ad_boost_soft_exit_timeout_seconds=5.0,
                ad_boost_hard_exit_timeout_seconds=8.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                if clock.monotonic() < 3.0:
                    return dumpsys_window_game
                if clock.monotonic() < 9.0:
                    return dumpsys_window_same_package_ad
                return dumpsys_window_game
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""
        
        runner.capture = dynamic_capture

        metadata = actuator.execute("activate_ad_boost")
        
        self.assertEqual(metadata.actuator_type, "adb")
        self.assertEqual(metadata.actuator_execution_status, "COMPLETED")
        self.assertIn(["adb", "-s", "emulator-5554", "shell", "input", "keyevent", "KEYCODE_BACK"], runner.commands)
        self.assertEqual(
            [e.stage_name for e in metadata.stage_events],
            ["boost_entry_tap", "boost_watch_tap", "ad_opened", "ad_soft_timeout_back_sent", "returned_to_game", "run_end"]
        )

    def test_activate_ad_boost_monitors_unity_ad_activity_in_same_package(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_unity_ad = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.ads.adplayer.FullScreenWebViewDisplay}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                activate_ad_boost_watch_tap=TapPoint(x=333, y=555),
                ark_popup_wait_seconds=1.5,
                ad_boost_open_timeout_seconds=10.0,
                ad_boost_probe_interval_seconds=2.0,
                ad_boost_stabilization_seconds=3.0,
                ad_boost_exit_timeout_seconds=10.0,
                ad_boost_soft_exit_timeout_seconds=5.0,
                ad_boost_hard_exit_timeout_seconds=8.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                if clock.monotonic() < 3.0:
                    return dumpsys_window_game
                if clock.monotonic() < 9.0:
                    return dumpsys_window_unity_ad
                return dumpsys_window_game
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        metadata = actuator.execute("activate_ad_boost")

        self.assertEqual(metadata.actuator_type, "adb")
        self.assertEqual(metadata.actuator_execution_status, "COMPLETED")
        self.assertIn(["adb", "-s", "emulator-5554", "shell", "input", "keyevent", "KEYCODE_BACK"], runner.commands)
        self.assertEqual(
            [e.stage_name for e in metadata.stage_events],
            ["boost_entry_tap", "boost_watch_tap", "ad_opened", "ad_soft_timeout_back_sent", "returned_to_game", "run_end"]
        )

    def test_activate_ad_boost_aborts_if_game_never_returns_before_exit_timeout(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_same_package_ad = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.facebook.ads.AudienceNetworkActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                activate_ad_boost_watch_tap=TapPoint(x=333, y=555),
                ark_popup_wait_seconds=1.5,
                ad_boost_open_timeout_seconds=10.0,
                ad_boost_probe_interval_seconds=2.0,
                ad_boost_stabilization_seconds=3.0,
                ad_boost_exit_timeout_seconds=5.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                if clock.monotonic() < 3.0:
                    return dumpsys_window_game
                return dumpsys_window_same_package_ad
            return '<?xml version="1.0" encoding="UTF-8"?><hierarchy/>'
        
        runner.capture = dynamic_capture

        with self.assertRaises(ActuatorExecutionError) as context:
            actuator.execute("activate_ad_boost")

        metadata = context.exception.metadata
        self.assertEqual(metadata.actuator_execution_status, "FAILED")
        self.assertEqual(metadata.stage_events[-1].stage_name, "run_end")
        self.assertIn("ad_active_timeout", metadata.stage_events[-1].error)

    def test_activate_ad_boost_handles_soft_timeout_fallback_and_succeeds(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_same_package_ad = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.facebook.ads.AudienceNetworkActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                activate_ad_boost_watch_tap=TapPoint(x=333, y=555),
                ark_popup_wait_seconds=1.5,
                ad_boost_open_timeout_seconds=10.0,
                ad_boost_probe_interval_seconds=2.0,
                ad_boost_stabilization_seconds=3.0,
                ad_boost_exit_timeout_seconds=15.0,
                ad_boost_soft_exit_timeout_seconds=5.0,
                ad_boost_hard_exit_timeout_seconds=10.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            cmd = " ".join(command)
            if "dumpsys window windows" in cmd:
                if clock.monotonic() < 3.0:
                    return dumpsys_window_game
                elif clock.monotonic() < 9.0:
                    return dumpsys_window_same_package_ad
                else:
                    return dumpsys_window_game
            elif "cat" in cmd and "ipm_bot_window_dump.xml" in cmd:
                return '<?xml version="1.0" encoding="UTF-8"?><hierarchy node="[0,0][100,100]"><node text="Playable"/></hierarchy>'
            elif "dumpsys activity activities" in cmd:
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""
        
        runner.capture = dynamic_capture

        metadata = actuator.execute("activate_ad_boost")

        self.assertEqual(metadata.actuator_execution_status, "COMPLETED")
        self.assertTrue(any(e.stage_name == "ad_soft_timeout_back_sent" for e in metadata.stage_events))
        self.assertFalse(any(e.stage_name == "ad_hard_timeout_back_sent" for e in metadata.stage_events))
        escape_trace = next((t for t in metadata.signal_traces if t.action_reason == "soft_timeout_escape"), None)
        self.assertIsNotNone(escape_trace)
        self.assertEqual(escape_trace.action_taken, "KEYCODE_BACK")
        self.assertTrue(all(trace.ui_text_excerpt is None for trace in metadata.signal_traces))

    def test_activate_ad_boost_handles_hard_timeout_fallback_and_succeeds(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_same_package_ad = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.facebook.ads.AudienceNetworkActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                activate_ad_boost_watch_tap=TapPoint(x=333, y=555),
                ark_popup_wait_seconds=1.5,
                ad_boost_open_timeout_seconds=10.0,
                ad_boost_probe_interval_seconds=2.0,
                ad_boost_stabilization_seconds=3.0,
                ad_boost_exit_timeout_seconds=20.0,
                ad_boost_soft_exit_timeout_seconds=5.0,
                ad_boost_hard_exit_timeout_seconds=10.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            cmd = " ".join(command)
            if "dumpsys window windows" in cmd:
                # < 3.0 -> game
                # < 13.0 -> ad (surpasses both 5.0 and 10.0 bounds)
                # > 13.0 -> game
                if clock.monotonic() < 3.0:
                    return dumpsys_window_game
                if clock.monotonic() < 13.0:
                    return dumpsys_window_same_package_ad
                return dumpsys_window_game
            elif "dumpsys activity activities" in cmd:
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""
        
        runner.capture = dynamic_capture

        metadata = actuator.execute("activate_ad_boost")

        self.assertEqual(metadata.actuator_execution_status, "COMPLETED")
        self.assertTrue(any(e.stage_name == "ad_soft_timeout_back_sent" for e in metadata.stage_events))
        self.assertTrue(any(e.stage_name == "ad_hard_timeout_back_sent" for e in metadata.stage_events))
        # Ensure only 2 timeouts mapped
        timeout_traces = [t for t in metadata.signal_traces if "timeout_escape" in t.action_reason]
        self.assertEqual(len(timeout_traces), 2)

    def test_activate_ad_boost_aborts_if_game_does_not_return_after_bounded_exit_attempts(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_same_package_ad = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.facebook.ads.AudienceNetworkActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                activate_ad_boost_watch_tap=TapPoint(x=333, y=555),
                ark_popup_wait_seconds=1.5,
                ad_boost_open_timeout_seconds=10.0,
                ad_boost_probe_interval_seconds=2.0,
                ad_boost_stabilization_seconds=3.0,
                ad_boost_exit_timeout_seconds=15.0,
                ad_boost_soft_exit_timeout_seconds=5.0,
                ad_boost_hard_exit_timeout_seconds=10.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                if clock.monotonic() < 3.0:
                    return dumpsys_window_game
                return dumpsys_window_same_package_ad
            return ""
        
        runner.capture = dynamic_capture

        with self.assertRaises(ActuatorExecutionError) as context:
            actuator.execute("activate_ad_boost")

        metadata = context.exception.metadata
        self.assertEqual(metadata.actuator_execution_status, "FAILED")
        self.assertTrue(any(event.stage_name == "ad_soft_timeout_back_sent" for event in metadata.stage_events))
        self.assertTrue(any(event.stage_name == "ad_hard_timeout_back_sent" for event in metadata.stage_events))
        self.assertEqual(metadata.stage_events[-1].stage_name, "run_end")
        self.assertIn("ad_active_timeout", metadata.stage_events[-1].error)

    def test_activate_ad_boost_executes_bounded_post_ad_claim_sequence_when_enabled(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_ad = (
            "mCurrentFocus=Window{42 u0 com.google.android.gms/com.google.android.gms.ads.AdActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                activate_ad_boost_watch_tap=TapPoint(x=333, y=555),
                ark_popup_wait_seconds=1.5,
                ad_boost_open_timeout_seconds=10.0,
                ad_boost_probe_interval_seconds=2.0,
                ad_boost_stabilization_seconds=3.0,
                ad_post_reward_auto_claim_enabled=True,
                ad_post_reward_claim_tap=TapPoint(x=454, y=975),
                ad_post_reward_claim_retry_count=2,
                ad_post_reward_claim_interval_seconds=1.25,
                ad_post_reward_claim_settle_seconds=2.5,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                if clock.monotonic() < 3.0:
                    return dumpsys_window_game
                if clock.monotonic() < 7.0:
                    return dumpsys_window_ad
                return dumpsys_window_game
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return '<?xml version="1.0" encoding="UTF-8"?><hierarchy/>'

        runner.capture = dynamic_capture

        metadata = actuator.execute("activate_ad_boost")

        self.assertEqual(
            runner.commands[-2:],
            [
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "454",
                    "975",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "454",
                    "975",
                ],
            ],
        )
        self.assertTrue(metadata.claim_attempted)
        self.assertEqual(metadata.number_of_claim_taps, 2)
        self.assertEqual(len(metadata.claim_tap_timestamps), 2)
        self.assertFalse(metadata.branch_attempted)
        self.assertEqual(metadata.branch_policy, "disabled")
        self.assertEqual(metadata.branch_choice_tap_count, 0)
        self.assertEqual(metadata.branch_choice_tap_timestamps, [])
        self.assertEqual(
            [
                event.stage_name
                for event in metadata.stage_events
                if event.stage_name.startswith("post_ad_reward_claim")
            ],
            [
                "post_ad_reward_claim_tap",
                "post_ad_reward_claim_tap",
                "post_ad_reward_claim_settle",
            ],
        )
        self.assertEqual(sleeper.durations, [1.5, 2.0, 2.0, 2.0, 3.0, 1.25, 2.5])

    def test_activate_ad_boost_does_not_issue_claim_taps_when_auto_claim_is_disabled(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_ad = (
            "mCurrentFocus=Window{42 u0 com.google.android.gms/com.google.android.gms.ads.AdActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                activate_ad_boost_watch_tap=TapPoint(x=333, y=555),
                ark_popup_wait_seconds=1.5,
                ad_boost_open_timeout_seconds=10.0,
                ad_boost_probe_interval_seconds=2.0,
                ad_boost_stabilization_seconds=3.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                if clock.monotonic() < 3.0:
                    return dumpsys_window_game
                if clock.monotonic() < 7.0:
                    return dumpsys_window_ad
                return dumpsys_window_game
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        metadata = actuator.execute("activate_ad_boost")

        self.assertEqual(metadata.actuator_command_count, 3)
        self.assertFalse(metadata.claim_attempted)
        self.assertEqual(metadata.number_of_claim_taps, 0)
        self.assertEqual(metadata.claim_tap_timestamps, [])
        self.assertFalse(metadata.branch_attempted)
        self.assertEqual(metadata.branch_policy, "disabled")
        self.assertEqual(metadata.branch_choice_tap_count, 0)
        self.assertEqual(metadata.branch_choice_tap_timestamps, [])
        self.assertFalse(
            any(
                event.stage_name.startswith("post_ad_reward_claim")
                for event in metadata.stage_events
            )
        )

    def test_activate_ad_boost_executes_bounded_post_ad_branch_choice_sequence_when_enabled(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_ad = (
            "mCurrentFocus=Window{42 u0 com.google.android.gms/com.google.android.gms.ads.AdActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                activate_ad_boost_watch_tap=TapPoint(x=333, y=555),
                ark_popup_wait_seconds=1.5,
                ad_boost_open_timeout_seconds=10.0,
                ad_boost_probe_interval_seconds=2.0,
                ad_boost_stabilization_seconds=3.0,
                ad_post_reward_auto_claim_enabled=True,
                ad_post_reward_claim_tap=TapPoint(x=454, y=975),
                ad_post_reward_claim_retry_count=1,
                ad_post_reward_claim_interval_seconds=1.25,
                ad_post_reward_claim_settle_seconds=2.5,
                ad_post_reward_branch_policy="single_choice_default",
                ad_post_reward_choice_tap=TapPoint(x=500, y=820),
                ad_post_reward_choice_retry_count=2,
                ad_post_reward_choice_interval_seconds=0.75,
                ad_post_reward_choice_settle_seconds=1.5,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                if clock.monotonic() < 3.0:
                    return dumpsys_window_game
                if clock.monotonic() < 7.0:
                    return dumpsys_window_ad
                return dumpsys_window_game
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        metadata = actuator.execute("activate_ad_boost")

        self.assertEqual(
            runner.commands[-3:],
            [
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "454",
                    "975",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "500",
                    "820",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "500",
                    "820",
                ],
            ],
        )
        self.assertTrue(metadata.claim_attempted)
        self.assertTrue(metadata.branch_attempted)
        self.assertEqual(metadata.branch_policy, "single_choice_default")
        self.assertEqual(metadata.branch_choice_tap_count, 2)
        self.assertEqual(len(metadata.branch_choice_tap_timestamps), 2)
        self.assertEqual(
            [
                event.stage_name
                for event in metadata.stage_events
                if event.stage_name.startswith("post_ad_reward_branch_choice")
            ],
            [
                "post_ad_reward_branch_choice_tap",
                "post_ad_reward_branch_choice_tap",
                "post_ad_reward_branch_choice_settle",
            ],
        )
        self.assertFalse(any("uiautomator" in " ".join(command) for command in runner.capture_commands))
        self.assertEqual(sleeper.durations, [1.5, 2.0, 2.0, 2.0, 3.0, 2.5, 0.75, 1.5])

    def test_activate_ad_boost_executes_bounded_ad_exit_override_for_allowlisted_activity(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_applovin = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.applovin.adview.AppLovinFullscreenActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                activate_ad_boost_watch_tap=TapPoint(x=333, y=555),
                ark_popup_wait_seconds=1.5,
                ad_boost_open_timeout_seconds=10.0,
                ad_boost_probe_interval_seconds=2.0,
                ad_boost_stabilization_seconds=3.0,
                ad_boost_exit_timeout_seconds=20.0,
                ad_boost_soft_exit_timeout_seconds=10.0,
                ad_boost_hard_exit_timeout_seconds=15.0,
                ad_exit_override_enabled=True,
                ad_exit_override_tap=TapPoint(x=948, y=84),
                ad_exit_override_delay_seconds=3.0,
                ad_exit_override_retry_count=2,
                ad_exit_override_interval_seconds=0.5,
                ad_exit_override_activity_allowlist=(
                    "com.applovin.adview.AppLovinFullscreenActivity",
                ),
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                if clock.monotonic() < 3.0:
                    return dumpsys_window_game
                if clock.monotonic() < 10.0:
                    return dumpsys_window_applovin
                return dumpsys_window_game
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        metadata = actuator.execute("activate_ad_boost")

        self.assertEqual(
            runner.commands[-2:],
            [
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "948",
                    "84",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "948",
                    "84",
                ],
            ],
        )
        self.assertTrue(metadata.ad_exit_override_attempted)
        self.assertEqual(metadata.ad_exit_override_tap_count, 2)
        self.assertEqual(metadata.ad_exit_override_tap_timestamps, [6.0, 6.5])
        self.assertEqual(
            metadata.ad_exit_override_activity,
            "com.applovin.adview.AppLovinFullscreenActivity",
        )
        self.assertEqual(
            [
                event.stage_name
                for event in metadata.stage_events
                if event.stage_name == "ad_exit_override_tap"
            ],
            ["ad_exit_override_tap", "ad_exit_override_tap"],
        )
        self.assertFalse(any("uiautomator" in " ".join(command) for command in runner.capture_commands))
        self.assertFalse(any("KEYCODE_BACK" in " ".join(command) for command in runner.commands))

    def test_activate_ad_boost_keeps_legacy_back_flow_when_override_is_disabled_for_allowlisted_activity(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_applovin = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.applovin.adview.AppLovinFullscreenActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                activate_ad_boost_watch_tap=TapPoint(x=333, y=555),
                ark_popup_wait_seconds=1.5,
                ad_boost_open_timeout_seconds=10.0,
                ad_boost_probe_interval_seconds=2.0,
                ad_boost_stabilization_seconds=3.0,
                ad_boost_exit_timeout_seconds=20.0,
                ad_boost_soft_exit_timeout_seconds=4.0,
                ad_boost_hard_exit_timeout_seconds=10.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                if clock.monotonic() < 3.0:
                    return dumpsys_window_game
                if clock.monotonic() < 7.0:
                    return dumpsys_window_applovin
                return dumpsys_window_game
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        metadata = actuator.execute("activate_ad_boost")

        self.assertFalse(metadata.ad_exit_override_attempted)
        self.assertEqual(metadata.ad_exit_override_tap_count, 0)
        self.assertEqual(metadata.ad_exit_override_tap_timestamps, [])
        self.assertIsNone(metadata.ad_exit_override_activity)
        self.assertTrue(any("KEYCODE_BACK" in " ".join(command) for command in runner.commands))
        self.assertFalse(any(event.stage_name == "ad_exit_override_tap" for event in metadata.stage_events))
        self.assertFalse(any("uiautomator" in " ".join(command) for command in runner.capture_commands))

    def test_activate_ad_boost_does_not_execute_ad_exit_override_for_non_allowlisted_activity(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_other_ad = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.facebook.ads.AudienceNetworkActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                activate_ad_boost_watch_tap=TapPoint(x=333, y=555),
                ark_popup_wait_seconds=1.5,
                ad_boost_open_timeout_seconds=10.0,
                ad_boost_probe_interval_seconds=2.0,
                ad_boost_stabilization_seconds=3.0,
                ad_boost_exit_timeout_seconds=20.0,
                ad_boost_soft_exit_timeout_seconds=12.0,
                ad_boost_hard_exit_timeout_seconds=16.0,
                ad_exit_override_enabled=True,
                ad_exit_override_tap=TapPoint(x=948, y=84),
                ad_exit_override_delay_seconds=3.0,
                ad_exit_override_retry_count=2,
                ad_exit_override_interval_seconds=0.5,
                ad_exit_override_activity_allowlist=(
                    "com.applovin.adview.AppLovinFullscreenActivity",
                ),
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                if clock.monotonic() < 3.0:
                    return dumpsys_window_game
                if clock.monotonic() < 7.0:
                    return dumpsys_window_other_ad
                return dumpsys_window_game
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        metadata = actuator.execute("activate_ad_boost")

        self.assertFalse(metadata.ad_exit_override_attempted)
        self.assertEqual(metadata.ad_exit_override_tap_count, 0)
        self.assertEqual(metadata.ad_exit_override_tap_timestamps, [])
        self.assertIsNone(metadata.ad_exit_override_activity)
        self.assertFalse(any(event.stage_name == "ad_exit_override_tap" for event in metadata.stage_events))
        self.assertFalse(any("uiautomator" in " ".join(command) for command in runner.capture_commands))

    def test_activate_ad_boost_store_package_is_treated_as_store_context(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_unknown_store = (
            "mCurrentFocus=Window{42 u0 com.android.vending/com.google.android.finsky.activities.UnknownActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                activate_ad_boost_watch_tap=TapPoint(x=333, y=555),
                ark_popup_wait_seconds=1.5,
                ad_boost_open_timeout_seconds=6.0,
                ad_boost_probe_interval_seconds=2.0,
                ad_boost_stabilization_seconds=3.0,
                ad_boost_exit_timeout_seconds=20.0,
                ad_boost_soft_exit_timeout_seconds=5.0,
                ad_boost_hard_exit_timeout_seconds=10.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                if clock.monotonic() < 3.0:
                    return dumpsys_window_game
                return dumpsys_window_unknown_store
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        with self.assertRaises(ActuatorExecutionError) as context:
            actuator.execute("activate_ad_boost")

        metadata = context.exception.metadata
        self.assertEqual(metadata.actuator_execution_status, "FAILED")
        self.assertEqual(metadata.stage_events[-1].stage_name, "run_end")
        self.assertTrue(any(event.stage_name == "store_redirect_detected" for event in metadata.stage_events))
        self.assertTrue(any("KEYCODE_BACK" in " ".join(command) for command in runner.commands))
        self.assertFalse(any("uiautomator" in " ".join(command) for command in runner.capture_commands))

    def test_activate_ad_boost_handles_store_redirect_and_succeeds(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_same_package_ad = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.facebook.ads.AudienceNetworkActivity}"
        )
        dumpsys_window_store = (
            "mCurrentFocus=Window{42 u0 com.android.vending/com.google.android.finsky.activities.MainActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                activate_ad_boost_watch_tap=TapPoint(x=333, y=555),
                ark_popup_wait_seconds=1.5,
                ad_boost_open_timeout_seconds=10.0,
                ad_boost_probe_interval_seconds=2.0,
                ad_boost_stabilization_seconds=3.0,
                ad_boost_exit_timeout_seconds=20.0,
                ad_boost_store_max_redirects=3,
                ad_boost_soft_exit_timeout_seconds=5.0,
                ad_boost_hard_exit_timeout_seconds=10.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                t = clock.monotonic()
                if t < 3.0:
                    return dumpsys_window_game
                if t < 5.0:
                    return dumpsys_window_same_package_ad
                if t < 7.0:
                    return dumpsys_window_store
                if t < 9.0:
                    return dumpsys_window_same_package_ad
                return dumpsys_window_game
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        metadata = actuator.execute("activate_ad_boost")
        
        self.assertEqual(metadata.actuator_type, "adb")
        self.assertEqual(metadata.actuator_execution_status, "COMPLETED")
        self.assertEqual(
            [e.stage_name for e in metadata.stage_events],
            [
                "boost_entry_tap",
                "boost_watch_tap",
                "ad_opened",
                "store_redirect_detected",
                "store_back_sent",
                "returned_to_ad",
                "ad_soft_timeout_back_sent",
                "returned_to_game",
                "run_end"
            ]
        )

    def test_activate_ad_boost_handles_multi_ad_chains_and_succeeds(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_ad_one = (
            "mCurrentFocus=Window{42 u0 com.google.android.gms/com.google.android.gms.ads.AdActivity}"
        )
        dumpsys_window_ad_two = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.facebook.ads.AudienceNetworkActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                activate_ad_boost_watch_tap=TapPoint(x=333, y=555),
                ark_popup_wait_seconds=1.5,
                ad_boost_open_timeout_seconds=10.0,
                ad_boost_probe_interval_seconds=2.0,
                ad_boost_stabilization_seconds=3.0,
                ad_boost_exit_timeout_seconds=30.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                t = clock.monotonic()
                if t < 3.0:
                    return dumpsys_window_game
                if t < 7.0:
                    return dumpsys_window_ad_one
                if t < 11.0:
                    return dumpsys_window_ad_two
                return dumpsys_window_game
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        metadata = actuator.execute("activate_ad_boost")
        
        self.assertEqual(metadata.actuator_type, "adb")
        self.assertEqual(metadata.actuator_execution_status, "COMPLETED")
        self.assertEqual(
            [e.stage_name for e in metadata.stage_events],
            [
                "boost_entry_tap",
                "boost_watch_tap",
                "ad_opened",
                "returned_to_game",
                "run_end"
            ]
        )

    def test_activate_ad_boost_aborts_if_ad_does_not_open(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                activate_ad_boost_watch_tap=TapPoint(x=333, y=555),
                ark_popup_wait_seconds=1.5,
                ad_boost_open_timeout_seconds=5.0,
                ad_boost_probe_interval_seconds=2.0,
                ad_boost_stabilization_seconds=3.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                return dumpsys_window_game
            return '<?xml version="1.0" encoding="UTF-8"?><hierarchy/>'
        
        runner.capture = dynamic_capture

        with self.assertRaises(ActuatorExecutionError) as context:
            actuator.execute("activate_ad_boost")

        metadata = context.exception.metadata
        self.assertEqual(metadata.actuator_execution_status, "FAILED")
        self.assertEqual(metadata.stage_events[-1].stage_name, "run_end")
        self.assertIn("ad_open_timeout", metadata.stage_events[-1].error)

    def test_activate_ad_boost_aborts_if_game_does_not_return(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_ad = (
            "mCurrentFocus=Window{42 u0 com.google.android.gms/com.google.android.gms.ads.AdActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                activate_ad_boost_watch_tap=TapPoint(x=333, y=555),
                ark_popup_wait_seconds=1.5,
                ad_boost_open_timeout_seconds=10.0,
                ad_boost_probe_interval_seconds=2.0,
                ad_boost_stabilization_seconds=3.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                if clock.monotonic() < 3.0:
                    return dumpsys_window_game
                return dumpsys_window_ad
            return '<?xml version="1.0" encoding="UTF-8"?><hierarchy/>'
        
        runner.capture = dynamic_capture

        with self.assertRaises(ActuatorExecutionError) as context:
            actuator.execute("activate_ad_boost")

        metadata = context.exception.metadata
        self.assertEqual(metadata.actuator_execution_status, "FAILED")
        self.assertEqual(metadata.stage_events[-1].stage_name, "run_end")
        self.assertIn("ad_active_timeout", metadata.stage_events[-1].error)

    def test_claim_ark_reward_emits_expected_multi_step_commands(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_ad = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.ads.adplayer.FullScreenWebViewDisplay}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                claim_ark_reward_tap=TapPoint(x=333, y=444),
                claim_ark_reward_watch_tap=TapPoint(x=555, y=666),
                claim_ark_skip_tap=TapPoint(x=12, y=34),
                claim_ark_reward_final_claim_tap=TapPoint(x=777, y=889),
                ark_popup_wait_seconds=1.25,
                ark_ad_wait_seconds=20.0,
                ark_skip_close_wait_seconds=1.0,
                ark_return_wait_seconds=2.5,
                ad_boost_open_timeout_seconds=4.0,
                ad_boost_probe_interval_seconds=1.0,
                ad_boost_exit_timeout_seconds=12.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                if clock.monotonic() < 2.0:
                    return dumpsys_window_game
                if clock.monotonic() < 6.0:
                    return dumpsys_window_ad
                return dumpsys_window_game
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        metadata = actuator.execute("claim_ark_reward")
        self.assertEqual(metadata.actuator_execution_status, "COMPLETED")
        self.assertEqual(metadata.actuator_command_count, 4)
        self.assertTrue(metadata.claim_attempted)
        self.assertEqual(metadata.number_of_claim_taps, 1)
        self.assertEqual(len(metadata.claim_tap_timestamps), 1)
        self.assertTrue(any(event.stage_name == "ad_open_detected" for event in metadata.stage_events))
        self.assertTrue(any(event.stage_name == "return_detected" for event in metadata.stage_events))
        self.assertTrue(any(event.stage_name == "claim_tap" for event in metadata.stage_events))
        self.assertFalse(any(event.stage_name == "ad_close_tap" for event in metadata.stage_events))
        self.assertTrue(metadata.probe_samples)

    def test_claim_ark_reward_collects_probe_samples_when_enabled(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_ad = (
            "mCurrentFocus=Window{42 u0 com.google.android.gms/com.google.android.gms.ads.AdActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                claim_ark_reward_tap=TapPoint(x=333, y=444),
                claim_ark_reward_watch_tap=TapPoint(x=555, y=666),
                claim_ark_skip_tap=TapPoint(x=12, y=34),
                claim_ark_reward_final_claim_tap=TapPoint(x=777, y=889),
                ark_popup_wait_seconds=1.25,
                ark_ad_wait_seconds=8.0,
                ark_skip_close_wait_seconds=1.0,
                ark_return_wait_seconds=2.5,
                ad_boost_open_timeout_seconds=4.0,
                ad_boost_probe_interval_seconds=1.0,
                ad_boost_exit_timeout_seconds=10.0,
                ark_post_watch_ui_dump_max_text_length=80,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                if clock.monotonic() < 2.0:
                    return dumpsys_window_game
                if clock.monotonic() < 6.0:
                    return dumpsys_window_ad
                return dumpsys_window_game
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        metadata = actuator.execute("claim_ark_reward")

        self.assertTrue(metadata.probe_samples)
        self.assertTrue(any(sample.sample_context == "ad_open_monitor" for sample in metadata.probe_samples))
        self.assertTrue(any(sample.sample_context == "ad_monitor" for sample in metadata.probe_samples))
        self.assertTrue(any(sample.focus_activity == "com.google.android.gms.ads.AdActivity" for sample in metadata.probe_samples))
        self.assertFalse(any("uiautomator" in " ".join(command) for command in runner.capture_commands))
        self.assertTrue(metadata.claim_attempted)
        self.assertEqual(metadata.number_of_claim_taps, 1)
        self.assertEqual(len(metadata.claim_tap_timestamps), 1)

    def test_claim_ark_reward_emits_multiple_escape_attempts_when_configured(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_ad = (
            "mCurrentFocus=Window{42 u0 com.google.android.gms/com.google.android.gms.ads.AdActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                claim_ark_reward_tap=TapPoint(x=333, y=444),
                claim_ark_reward_watch_tap=TapPoint(x=555, y=666),
                claim_ark_skip_tap=TapPoint(x=12, y=34),
                claim_ark_reward_final_claim_tap=TapPoint(x=777, y=889),
                ark_popup_wait_seconds=1.25,
                ark_ad_wait_seconds=3.0,
                ark_skip_close_wait_seconds=1.0,
                ark_return_wait_seconds=2.5,
                ark_esc_attempts=3,
                ark_esc_interval_seconds=1.25,
                ad_boost_open_timeout_seconds=4.0,
                ad_boost_probe_interval_seconds=1.0,
                ad_boost_exit_timeout_seconds=6.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                if clock.monotonic() < 2.0:
                    return dumpsys_window_game
                return dumpsys_window_ad
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        with self.assertRaises(ActuatorExecutionError) as context:
            actuator.execute("claim_ark_reward")

        metadata = context.exception.metadata

        self.assertEqual(metadata.actuator_execution_status, "FAILED")
        self.assertTrue(any(event.stage_name == "ad_close_tap" for event in metadata.stage_events))
        self.assertTrue(any(event.stage_name == "esc_attempt_1" for event in metadata.stage_events))
        self.assertTrue(any(event.stage_name == "esc_attempt_2" for event in metadata.stage_events))
        self.assertTrue(any(event.stage_name == "esc_attempt_3" for event in metadata.stage_events))
        self.assertFalse(metadata.claim_attempted)

    def test_claim_ark_reward_handles_external_ad_and_returns(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_ad = (
            "mCurrentFocus=Window{42 u0 com.google.android.gms/com.google.android.gms.ads.AdActivity}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                claim_ark_reward_tap=TapPoint(x=333, y=444),
                claim_ark_reward_watch_tap=TapPoint(x=555, y=666),
                claim_ark_skip_tap=TapPoint(x=12, y=34),
                claim_ark_reward_final_claim_tap=TapPoint(x=777, y=889),
                ark_popup_wait_seconds=1.25,
                ark_ad_wait_seconds=20.0,
                ark_skip_close_wait_seconds=1.0,
                ark_return_wait_seconds=2.5,
                ad_boost_open_timeout_seconds=4.0,
                ad_boost_probe_interval_seconds=1.0,
                ad_boost_exit_timeout_seconds=12.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                if clock.monotonic() < 2.0:
                    return dumpsys_window_game
                if clock.monotonic() < 6.0:
                    return dumpsys_window_ad
                return dumpsys_window_game
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        metadata = actuator.execute("claim_ark_reward")

        self.assertTrue(metadata.claim_attempted)
        self.assertTrue(any(event.stage_name == "ad_open_detected" for event in metadata.stage_events))
        self.assertTrue(any(event.stage_name == "return_detected" for event in metadata.stage_events))
        self.assertFalse(any(event.stage_name == "ad_close_tap" for event in metadata.stage_events))
        self.assertFalse(any(event.stage_name == "store_redirect_detected" for event in metadata.stage_events))
        self.assertFalse(any(event.stage_name.startswith("same_app_") for event in metadata.stage_events))
        self.assertFalse(any("KEYCODE_BACK" in " ".join(command) for command in runner.commands))

    def test_claim_ark_reward_handles_store_redirect_with_bounded_back_and_returns_directly_to_game(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_unity_ad = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.ads.adplayer.FullScreenWebViewDisplay}"
        )
        dumpsys_window_store = (
            "mCurrentFocus=Window{42 u0 com.android.vending/com.google.android.finsky.transparentmainactivity.HsdpAlias}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                claim_ark_reward_tap=TapPoint(x=333, y=444),
                claim_ark_reward_watch_tap=TapPoint(x=555, y=666),
                claim_ark_skip_tap=TapPoint(x=12, y=34),
                claim_ark_reward_final_claim_tap=TapPoint(x=777, y=889),
                ark_popup_wait_seconds=1.25,
                ark_ad_wait_seconds=20.0,
                ark_skip_close_wait_seconds=1.0,
                ark_return_wait_seconds=2.5,
                ad_boost_open_timeout_seconds=4.0,
                ad_boost_probe_interval_seconds=1.0,
                ad_boost_exit_timeout_seconds=12.0,
                ad_boost_store_max_redirects=3,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                t = clock.monotonic()
                if t < 2.0:
                    return dumpsys_window_game
                if t < 4.0:
                    return dumpsys_window_unity_ad
                if t < 6.0:
                    return dumpsys_window_store
                return dumpsys_window_game
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        metadata = actuator.execute("claim_ark_reward")

        self.assertTrue(metadata.claim_attempted)
        self.assertTrue(any(event.stage_name == "store_redirect_detected" for event in metadata.stage_events))
        self.assertTrue(any(event.stage_name == "store_back_attempt_1" for event in metadata.stage_events))
        self.assertTrue(any(event.stage_name == "return_detected" for event in metadata.stage_events))
        self.assertFalse(any(event.stage_name == "post_store_same_app_detected" for event in metadata.stage_events))
        self.assertFalse(any(event.stage_name.startswith("same_app_endcard_close_attempt_") for event in metadata.stage_events))
        self.assertFalse(any(event.stage_name.startswith("same_app_back_attempt_") for event in metadata.stage_events))
        self.assertFalse(any(event.stage_name == "ad_close_tap" for event in metadata.stage_events))
        self.assertIn(
            ["adb", "-s", "emulator-5554", "shell", "input", "keyevent", "KEYCODE_BACK"],
            runner.commands,
        )
        claim_command_index = runner.commands.index(
            ["adb", "-s", "emulator-5554", "shell", "input", "tap", "777", "889"]
        )
        back_command_index = runner.commands.index(
            ["adb", "-s", "emulator-5554", "shell", "input", "keyevent", "KEYCODE_BACK"]
        )
        self.assertGreater(claim_command_index, back_command_index)

    def test_claim_ark_reward_handles_store_redirect_then_same_app_endcard_close_and_returns_to_game(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_unity_ad = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.ads.adplayer.FullScreenWebViewDisplay}"
        )
        dumpsys_window_store = (
            "mCurrentFocus=Window{42 u0 com.android.vending/com.google.android.finsky.transparentmainactivity.HsdpAlias}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                claim_ark_reward_tap=TapPoint(x=333, y=444),
                claim_ark_reward_watch_tap=TapPoint(x=555, y=666),
                claim_ark_skip_tap=TapPoint(x=12, y=34),
                claim_ark_reward_final_claim_tap=TapPoint(x=777, y=889),
                ark_popup_wait_seconds=1.25,
                ark_ad_wait_seconds=20.0,
                ark_skip_close_wait_seconds=1.0,
                ark_return_wait_seconds=2.5,
                ad_boost_open_timeout_seconds=4.0,
                ad_boost_probe_interval_seconds=1.0,
                ad_boost_exit_timeout_seconds=12.0,
                ad_boost_store_max_redirects=3,
                claim_ark_same_app_endcard_close_tap=TapPoint(x=839, y=75),
                claim_ark_same_app_endcard_close_attempts=2,
                claim_ark_same_app_endcard_close_interval_seconds=0.5,
                claim_ark_same_app_back_attempts=2,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                t = clock.monotonic()
                if t < 2.0:
                    return dumpsys_window_game
                if t < 4.0:
                    return dumpsys_window_unity_ad
                if t < 6.0:
                    return dumpsys_window_store
                if t < 6.5:
                    return dumpsys_window_unity_ad
                return dumpsys_window_game
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        metadata = actuator.execute("claim_ark_reward")

        self.assertTrue(metadata.claim_attempted)
        self.assertTrue(any(event.stage_name == "store_redirect_detected" for event in metadata.stage_events))
        self.assertTrue(any(event.stage_name == "store_back_attempt_1" for event in metadata.stage_events))
        self.assertTrue(any(event.stage_name == "post_store_same_app_detected" for event in metadata.stage_events))
        self.assertTrue(
            any(event.stage_name == "same_app_endcard_close_attempt_1" for event in metadata.stage_events)
        )
        self.assertFalse(any(event.stage_name.startswith("same_app_back_attempt_") for event in metadata.stage_events))
        self.assertTrue(any(event.stage_name == "return_detected" for event in metadata.stage_events))
        close_command_index = runner.commands.index(
            ["adb", "-s", "emulator-5554", "shell", "input", "tap", "839", "75"]
        )
        claim_command_index = runner.commands.index(
            ["adb", "-s", "emulator-5554", "shell", "input", "tap", "777", "889"]
        )
        self.assertGreater(claim_command_index, close_command_index)

    def test_claim_ark_reward_same_app_endcard_close_attempts_are_bounded(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_unity_ad = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.ads.adplayer.FullScreenWebViewDisplay}"
        )
        dumpsys_window_store = (
            "mCurrentFocus=Window{42 u0 com.android.vending/com.google.android.finsky.transparentmainactivity.HsdpAlias}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                claim_ark_reward_tap=TapPoint(x=333, y=444),
                claim_ark_reward_watch_tap=TapPoint(x=555, y=666),
                claim_ark_skip_tap=TapPoint(x=12, y=34),
                claim_ark_reward_final_claim_tap=TapPoint(x=777, y=889),
                ark_popup_wait_seconds=1.25,
                ark_ad_wait_seconds=20.0,
                ark_skip_close_wait_seconds=1.0,
                ark_return_wait_seconds=2.5,
                ad_boost_open_timeout_seconds=4.0,
                ad_boost_probe_interval_seconds=1.0,
                ad_boost_exit_timeout_seconds=12.0,
                ad_boost_store_max_redirects=2,
                claim_ark_same_app_endcard_close_tap=TapPoint(x=839, y=75),
                claim_ark_same_app_endcard_close_attempts=2,
                claim_ark_same_app_endcard_close_interval_seconds=0.5,
                claim_ark_same_app_back_attempts=0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                t = clock.monotonic()
                if t < 2.0:
                    return dumpsys_window_game
                if t < 4.0:
                    return dumpsys_window_unity_ad
                if t < 6.0:
                    return dumpsys_window_store
                return dumpsys_window_unity_ad
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        with self.assertRaises(ActuatorExecutionError) as context:
            actuator.execute("claim_ark_reward")

        metadata = context.exception.metadata

        self.assertEqual(metadata.actuator_execution_status, "FAILED")
        self.assertIn("ark_same_app_exit_timeout", metadata.stage_events[-1].error)
        self.assertTrue(any(event.stage_name == "post_store_same_app_detected" for event in metadata.stage_events))
        self.assertTrue(
            any(event.stage_name == "same_app_endcard_close_attempt_1" for event in metadata.stage_events)
        )
        self.assertTrue(
            any(event.stage_name == "same_app_endcard_close_attempt_2" for event in metadata.stage_events)
        )
        self.assertFalse(any(event.stage_name.startswith("same_app_back_attempt_") for event in metadata.stage_events))
        self.assertEqual(
            sum(1 for command in runner.commands if "KEYCODE_BACK" in " ".join(command)),
            2,
        )
        self.assertFalse(metadata.claim_attempted)

    def test_claim_ark_reward_same_app_back_attempts_are_bounded(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_unity_ad = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.ads.adplayer.FullScreenWebViewDisplay}"
        )
        dumpsys_window_store = (
            "mCurrentFocus=Window{42 u0 com.android.vending/com.google.android.finsky.transparentmainactivity.HsdpAlias}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                claim_ark_reward_tap=TapPoint(x=333, y=444),
                claim_ark_reward_watch_tap=TapPoint(x=555, y=666),
                claim_ark_skip_tap=TapPoint(x=12, y=34),
                claim_ark_reward_final_claim_tap=TapPoint(x=777, y=889),
                ark_popup_wait_seconds=1.25,
                ark_ad_wait_seconds=20.0,
                ark_skip_close_wait_seconds=1.0,
                ark_return_wait_seconds=2.5,
                ad_boost_open_timeout_seconds=4.0,
                ad_boost_probe_interval_seconds=1.0,
                ad_boost_exit_timeout_seconds=12.0,
                ad_boost_store_max_redirects=2,
                claim_ark_same_app_back_attempts=2,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                t = clock.monotonic()
                if t < 2.0:
                    return dumpsys_window_game
                if t < 4.0:
                    return dumpsys_window_unity_ad
                if t < 6.0:
                    return dumpsys_window_store
                return dumpsys_window_unity_ad
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        with self.assertRaises(ActuatorExecutionError) as context:
            actuator.execute("claim_ark_reward")

        metadata = context.exception.metadata

        self.assertIn("ark_same_app_exit_timeout", metadata.stage_events[-1].error)
        self.assertFalse(any(event.stage_name.startswith("same_app_endcard_close_attempt_") for event in metadata.stage_events))
        self.assertTrue(any(event.stage_name == "same_app_back_attempt_1" for event in metadata.stage_events))
        self.assertTrue(any(event.stage_name == "same_app_back_attempt_2" for event in metadata.stage_events))
        self.assertEqual(
            sum(1 for command in runner.commands if "KEYCODE_BACK" in " ".join(command)),
            4,
        )
        self.assertFalse(metadata.claim_attempted)

    def test_claim_ark_reward_does_not_attempt_claim_before_game_focus_is_restored(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_unity_ad = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.ads.adplayer.FullScreenWebViewDisplay}"
        )
        dumpsys_window_store = (
            "mCurrentFocus=Window{42 u0 com.android.vending/com.google.android.finsky.transparentmainactivity.HsdpAlias}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                claim_ark_reward_tap=TapPoint(x=333, y=444),
                claim_ark_reward_watch_tap=TapPoint(x=555, y=666),
                claim_ark_skip_tap=TapPoint(x=12, y=34),
                claim_ark_reward_final_claim_tap=TapPoint(x=777, y=889),
                ark_popup_wait_seconds=1.25,
                ark_ad_wait_seconds=20.0,
                ark_skip_close_wait_seconds=1.0,
                ark_return_wait_seconds=2.5,
                ad_boost_open_timeout_seconds=4.0,
                ad_boost_probe_interval_seconds=1.0,
                ad_boost_exit_timeout_seconds=12.0,
                ad_boost_store_max_redirects=2,
                claim_ark_same_app_endcard_close_tap=TapPoint(x=839, y=75),
                claim_ark_same_app_endcard_close_attempts=1,
                claim_ark_same_app_endcard_close_interval_seconds=0.5,
                claim_ark_same_app_back_attempts=1,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                t = clock.monotonic()
                if t < 2.0:
                    return dumpsys_window_game
                if t < 4.0:
                    return dumpsys_window_unity_ad
                if t < 6.0:
                    return dumpsys_window_store
                return dumpsys_window_unity_ad
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        with self.assertRaises(ActuatorExecutionError) as context:
            actuator.execute("claim_ark_reward")

        metadata = context.exception.metadata

        self.assertFalse(metadata.claim_attempted)
        self.assertFalse(
            any(
                command == ["adb", "-s", "emulator-5554", "shell", "input", "tap", "777", "889"]
                for command in runner.commands
            )
        )

    def test_claim_ark_reward_aborts_if_ad_never_opens(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        runner = RecordingCommandRunner(
            captured_outputs={
                "adb -s emulator-5554 shell dumpsys window windows": dumpsys_window_game,
                "adb -s emulator-5554 shell dumpsys activity activities": "ACTIVITY MANAGER ACTIVITIES",
            }
        )
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                claim_ark_reward_tap=TapPoint(x=333, y=444),
                claim_ark_reward_watch_tap=TapPoint(x=555, y=666),
                claim_ark_skip_tap=TapPoint(x=12, y=34),
                claim_ark_reward_final_claim_tap=TapPoint(x=777, y=889),
                ark_popup_wait_seconds=1.25,
                ark_ad_wait_seconds=6.0,
                ark_skip_close_wait_seconds=1.0,
                ark_return_wait_seconds=2.5,
                ad_boost_open_timeout_seconds=3.0,
                ad_boost_probe_interval_seconds=1.0,
                ad_boost_exit_timeout_seconds=6.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        with self.assertRaises(ActuatorExecutionError) as context:
            actuator.execute("claim_ark_reward")

        metadata = context.exception.metadata

        self.assertIn("ark_ad_open_timeout", metadata.stage_events[-1].error)
        self.assertFalse(metadata.claim_attempted)

    def test_claim_ark_reward_records_focus_probe_error_when_dumpsys_is_unavailable(self) -> None:
        runner = RecordingCommandRunner(
            captured_outputs={
                "adb -s emulator-5554 shell dumpsys activity activities": "ACTIVITY MANAGER ACTIVITIES",
            }
        )
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                claim_ark_reward_tap=TapPoint(x=333, y=444),
                claim_ark_reward_watch_tap=TapPoint(x=555, y=666),
                claim_ark_skip_tap=TapPoint(x=12, y=34),
                claim_ark_reward_final_claim_tap=TapPoint(x=777, y=889),
                ark_popup_wait_seconds=1.25,
                ark_ad_wait_seconds=4.0,
                ark_skip_close_wait_seconds=1.0,
                ark_return_wait_seconds=2.5,
                ad_boost_open_timeout_seconds=2.0,
                ad_boost_probe_interval_seconds=1.0,
                ad_boost_exit_timeout_seconds=4.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        with self.assertRaises(ActuatorExecutionError) as context:
            actuator.execute("claim_ark_reward")

        metadata = context.exception.metadata

        self.assertTrue(metadata.probe_samples)
        self.assertIn("focus:", metadata.probe_samples[0].probe_error)
        self.assertIsNone(metadata.probe_samples[0].ui_dump_xml)
        self.assertIsNone(metadata.probe_samples[0].dumpsys_window_output)
        self.assertIsNotNone(metadata.probe_samples[0].dumpsys_activity_output)
        self.assertFalse(any("uiautomator" in " ".join(command) for command in runner.capture_commands))

    def test_claim_ark_reward_does_not_issue_ui_dump_commands_when_probe_sampling_is_enabled(self) -> None:
        dumpsys_window_game = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
        )
        dumpsys_window_ad = (
            "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.ads.adplayer.FullScreenWebViewDisplay}"
        )
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="com.unity3d.player.UnityPlayerActivity",
                claim_ark_reward_tap=TapPoint(x=333, y=444),
                claim_ark_reward_watch_tap=TapPoint(x=555, y=666),
                claim_ark_skip_tap=TapPoint(x=12, y=34),
                claim_ark_reward_final_claim_tap=TapPoint(x=777, y=889),
                ark_popup_wait_seconds=1.25,
                ark_ad_wait_seconds=4.0,
                ark_skip_close_wait_seconds=1.0,
                ark_return_wait_seconds=2.5,
                ad_boost_open_timeout_seconds=3.0,
                ad_boost_probe_interval_seconds=1.0,
                ad_boost_exit_timeout_seconds=8.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        def dynamic_capture(command: list[str]) -> str:
            if "dumpsys window windows" in " ".join(command):
                if clock.monotonic() < 2.0:
                    return dumpsys_window_game
                if clock.monotonic() < 5.0:
                    return dumpsys_window_ad
                return dumpsys_window_game
            if "dumpsys activity activities" in " ".join(command):
                return "ACTIVITY MANAGER ACTIVITIES"
            return ""

        runner.capture = dynamic_capture

        metadata = actuator.execute("claim_ark_reward")

        self.assertTrue(all(sample.ui_text_excerpt is None for sample in metadata.probe_samples))
        self.assertTrue(all(sample.ui_dump_xml is None for sample in metadata.probe_samples))
        self.assertFalse(any("uiautomator" in " ".join(command) for command in runner.capture_commands))

    def test_manual_observation_mode_skips_ark_commands_and_collects_probes(self) -> None:
        ui_dump_output = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<hierarchy><node text="Ad 1 of 2" content-desc="Close ad" /></hierarchy>'
        )
        runner = RecordingCommandRunner(
            captured_outputs={
                "adb -s emulator-5554 shell dumpsys window windows": (
                    "mCurrentFocus=Window{42 u0 "
                    "com.facebook.ads/com.facebook.ads.AudienceNetworkActivity}"
                ),
                "adb -s emulator-5554 shell dumpsys activity activities": (
                    "ACTIVITY MANAGER ACTIVITIES"
                ),
                "adb -s emulator-5554 shell uiautomator dump /sdcard/ipm_bot_window_dump.xml": (
                    "UI hierchary dumped to: /sdcard/ipm_bot_window_dump.xml"
                ),
                "adb -s emulator-5554 shell cat /sdcard/ipm_bot_window_dump.xml": ui_dump_output,
            }
        )
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                manual_observation_mode=True,
                manual_observation_window_seconds=2.0,
                manual_observation_probe_interval_seconds=1.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        metadata = actuator.execute("claim_ark_reward")

        self.assertEqual(runner.commands, [])
        self.assertEqual(metadata.actuator_execution_status, "COMPLETED")
        self.assertEqual(metadata.actuator_command_count, 0)
        self.assertEqual(metadata.actuator_command_summary, [])
        self.assertEqual(
            [event.stage_name for event in metadata.stage_events],
            ["manual_observation_start", "manual_observation_end"],
        )
        self.assertEqual(
            [sample.sample_context for sample in metadata.probe_samples],
            ["manual_observation", "manual_observation", "manual_observation"],
        )
        self.assertTrue(
            all(
                sample.sample_reference_stage == "manual_observation_start"
                for sample in metadata.probe_samples
            )
        )
        self.assertEqual(
            [sample.sample_offset_seconds for sample in metadata.probe_samples],
            [0.0, 1.0, 2.0],
        )
        self.assertEqual(sleeper.durations, [1.0, 1.0])

    def test_idle_emits_no_commands(self) -> None:
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        metadata = actuator.execute("idle")

        self.assertEqual(runner.commands, [])
        self.assertEqual(metadata.actuator_execution_status, "COMPLETED")
        self.assertEqual(metadata.actuator_command_count, 0)
        self.assertEqual(metadata.actuator_command_summary, [])
        self.assertEqual(sleeper.durations, [])
        self.assertEqual(metadata.stage_events, [])
        self.assertEqual(metadata.probe_samples, [])

    def test_command_runner_failure_raises_classified_error(self) -> None:
        runner = FailingCommandRunner()
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                app_package="com.example.idleplanetminer",
                app_activity="MainActivity",
            ),
            command_runner=runner,
        )

        with self.assertRaises(ActuatorExecutionError) as context:
            actuator.execute("activate_ad_boost")

        self.assertEqual(context.exception.metadata.actuator_type, "adb")
        self.assertEqual(context.exception.metadata.actuator_execution_status, "FAILED")
        self.assertEqual(context.exception.metadata.actuator_command_count, 1)
        self.assertEqual(
            context.exception.metadata.actuator_command_summary,
            ["adb shell am start -n com.example.idleplanetminer/MainActivity"],
        )


class RecordingCommandRunner:
    def __init__(self, captured_outputs: dict[str, str] | None = None) -> None:
        self.commands: list[list[str]] = []
        self.capture_commands: list[list[str]] = []
        self.captured_outputs = {} if captured_outputs is None else dict(captured_outputs)

    def run(self, command: list[str]) -> None:
        self.commands.append(list(command))

    def capture(self, command: list[str]) -> str:
        self.capture_commands.append(list(command))
        normalized = " ".join(command)
        try:
            return self.captured_outputs[normalized]
        except KeyError as exc:
            raise AssertionError(f"unexpected capture command: {normalized}") from exc


class FailingCommandRunner:
    def run(self, command: list[str]) -> None:
        raise RuntimeError(f"command failed: {' '.join(command)}")

    def capture(self, command: list[str]) -> str:
        raise RuntimeError(f"capture failed: {' '.join(command)}")


class RecordingSleeper:
    def __init__(self, clock: "RecordingClock") -> None:
        self._clock = clock
        self.durations: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.durations.append(seconds)
        self._clock.advance(seconds)


class RecordingClock:
    def __init__(self) -> None:
        self._value = 0.0

    def monotonic(self) -> float:
        return self._value

    def advance(self, seconds: float) -> None:
        self._value += seconds


if __name__ == "__main__":
    unittest.main()

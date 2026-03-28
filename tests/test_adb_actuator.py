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
                ad_boost_watch_timeout_seconds=60.0,
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
                ad_boost_watch_timeout_seconds=60.0,
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
                ad_boost_watch_timeout_seconds=60.0,
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
                ad_boost_watch_timeout_seconds=60.0,
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
                ad_boost_watch_timeout_seconds=60.0,
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
                ad_boost_watch_timeout_seconds=5.0,
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
                ad_boost_watch_timeout_seconds=60.0,
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
                ad_boost_watch_timeout_seconds=60.0,
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
        self.assertFalse(
            any(
                event.stage_name.startswith("post_ad_reward_claim")
                for event in metadata.stage_events
            )
        )

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
                ad_boost_watch_timeout_seconds=60.0,
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
                ad_boost_watch_timeout_seconds=60.0,
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
                ad_boost_watch_timeout_seconds=60.0,
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
                ad_boost_watch_timeout_seconds=5.0,
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
        runner = RecordingCommandRunner()
        clock = RecordingClock()
        sleeper = RecordingSleeper(clock)
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                claim_ark_reward_tap=TapPoint(x=333, y=444),
                claim_ark_reward_watch_tap=TapPoint(x=555, y=666),
                claim_ark_skip_tap=TapPoint(x=12, y=34),
                claim_ark_reward_final_claim_tap=TapPoint(x=777, y=889),
                ark_popup_wait_seconds=1.25,
                ark_ad_wait_seconds=20.0,
                ark_skip_close_wait_seconds=1.0,
                ark_return_wait_seconds=2.5,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        metadata = actuator.execute("claim_ark_reward")

        self.assertEqual(
            runner.commands,
            [
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "monkey",
                    "-p",
                    "com.example.idleplanetminer",
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "1",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "333",
                    "444",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "555",
                    "666",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "12",
                    "34",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "keyevent",
                    "KEYCODE_ESCAPE",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "777",
                    "889",
                ],
            ],
        )
        self.assertEqual(metadata.actuator_execution_status, "COMPLETED")
        self.assertEqual(metadata.actuator_command_count, 6)
        self.assertTrue(metadata.claim_attempted)
        self.assertEqual(metadata.number_of_claim_taps, 1)
        self.assertEqual(len(metadata.claim_tap_timestamps), 1)
        self.assertEqual(sleeper.durations, [1.25, 20.0, 1.0, 2.5])
        self.assertEqual(
            metadata.actuator_command_summary,
            [
                "adb -s emulator-5554 shell monkey -p com.example.idleplanetminer -c android.intent.category.LAUNCHER 1",
                "adb -s emulator-5554 shell input tap 333 444",
                "adb -s emulator-5554 shell input tap 555 666",
                "adb -s emulator-5554 shell input tap 12 34",
                "adb -s emulator-5554 shell input keyevent KEYCODE_ESCAPE",
                "adb -s emulator-5554 shell input tap 777 889",
            ],
        )
        self.assertEqual(
            [event.stage_name for event in metadata.stage_events],
            [
                "ark_entry_tap",
                "ark_watch_tap",
                "probe_window_start",
                "ad_close_tap",
                "esc_attempt_1",
                "post_esc_settle_start",
                "claim_tap",
                "run_end",
            ],
        )
        self.assertEqual(metadata.probe_samples, [])

    def test_claim_ark_reward_collects_probe_samples_when_enabled(self) -> None:
        dumpsys_output = (
            "mCurrentFocus=Window{42 u0 com.google.android.gms/com.google.android.gms.ads.AdActivity}"
        )
        ui_dump_output = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<hierarchy><node text="Reward granted" content-desc="Close ad" /></hierarchy>'
        )
        runner = RecordingCommandRunner(
            captured_outputs={
                "adb -s emulator-5554 shell dumpsys window windows": dumpsys_output,
                "adb -s emulator-5554 shell dumpsys activity activities": "ACTIVITY MANAGER ACTIVITIES",
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
                claim_ark_reward_tap=TapPoint(x=333, y=444),
                claim_ark_reward_watch_tap=TapPoint(x=555, y=666),
                claim_ark_skip_tap=TapPoint(x=12, y=34),
                claim_ark_reward_final_claim_tap=TapPoint(x=777, y=889),
                ark_popup_wait_seconds=1.25,
                ark_ad_wait_seconds=8.0,
                ark_skip_close_wait_seconds=1.0,
                ark_return_wait_seconds=2.5,
                ark_post_watch_probe_count=2,
                ark_post_watch_probe_interval_seconds=1.5,
                ark_post_watch_ui_dump_max_text_length=80,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        metadata = actuator.execute("claim_ark_reward")

        self.assertEqual(len(metadata.probe_samples), 6)
        self.assertEqual(metadata.probe_samples[0].sample_context, "post_entry")
        self.assertEqual(metadata.probe_samples[0].sample_reference_stage, "ark_entry_tap")
        self.assertIsNone(metadata.probe_samples[0].esc_attempt_index)
        self.assertEqual(metadata.probe_samples[1].sample_context, "post_watch")
        self.assertEqual(metadata.probe_samples[1].sample_reference_stage, "ark_watch_tap")
        self.assertIsNone(metadata.probe_samples[1].esc_attempt_index)
        self.assertEqual(metadata.probe_samples[1].focus_package, "com.google.android.gms")
        self.assertEqual(
            metadata.probe_samples[1].focus_activity,
            "com.google.android.gms.ads.AdActivity",
        )
        self.assertEqual(metadata.probe_samples[1].ui_text_excerpt, "Reward granted | Close ad")
        self.assertEqual(
            metadata.probe_samples[1].dumpsys_activity_output,
            "ACTIVITY MANAGER ACTIVITIES",
        )
        self.assertIn("mCurrentFocus=Window", metadata.probe_samples[1].dumpsys_window_output)
        self.assertTrue(metadata.probe_samples[1].ui_dump_xml.startswith("<?xml version=\"1.0\""))
        self.assertIsNone(metadata.probe_samples[1].probe_error)
        self.assertEqual(metadata.probe_samples[3].sample_context, "pre_esc")
        self.assertEqual(metadata.probe_samples[3].esc_attempt_index, 1)
        self.assertEqual(metadata.probe_samples[4].sample_context, "post_esc")
        self.assertEqual(metadata.probe_samples[4].esc_attempt_index, 1)
        self.assertEqual(metadata.probe_samples[5].sample_context, "post_esc_settle")
        self.assertEqual(
            metadata.stage_events[1].stage_name,
            "entry_observation",
        )
        self.assertTrue(metadata.claim_attempted)
        self.assertEqual(metadata.number_of_claim_taps, 1)
        self.assertEqual(len(metadata.claim_tap_timestamps), 1)
        self.assertEqual(sleeper.durations, [1.25, 1.5, 6.5, 1.0, 2.5])

    def test_claim_ark_reward_emits_multiple_escape_attempts_when_configured(self) -> None:
        dumpsys_output = (
            "mCurrentFocus=Window{42 u0 com.google.android.gms/com.google.android.gms.ads.AdActivity}"
        )
        ui_dump_output = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<hierarchy><node text="Ad 1 of 2" content-desc="Close ad" /></hierarchy>'
        )
        runner = RecordingCommandRunner(
            captured_outputs={
                "adb -s emulator-5554 shell dumpsys window windows": dumpsys_output,
                "adb -s emulator-5554 shell dumpsys activity activities": "ACTIVITY MANAGER ACTIVITIES",
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
                claim_ark_reward_tap=TapPoint(x=333, y=444),
                claim_ark_reward_watch_tap=TapPoint(x=555, y=666),
                claim_ark_skip_tap=TapPoint(x=12, y=34),
                claim_ark_reward_final_claim_tap=TapPoint(x=777, y=889),
                ark_popup_wait_seconds=1.25,
                ark_ad_wait_seconds=6.0,
                ark_skip_close_wait_seconds=1.0,
                ark_return_wait_seconds=2.5,
                ark_esc_attempts=3,
                ark_esc_interval_seconds=1.25,
                ark_post_watch_probe_count=1,
                ark_post_watch_probe_interval_seconds=1.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        metadata = actuator.execute("claim_ark_reward")

        self.assertEqual(
            runner.commands,
            [
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "monkey",
                    "-p",
                    "com.example.idleplanetminer",
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "1",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "333",
                    "444",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "555",
                    "666",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "12",
                    "34",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "keyevent",
                    "KEYCODE_ESCAPE",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "keyevent",
                    "KEYCODE_ESCAPE",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "keyevent",
                    "KEYCODE_ESCAPE",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "777",
                    "889",
                ],
            ],
        )
        self.assertEqual(
            [event.stage_name for event in metadata.stage_events],
            [
                "ark_entry_tap",
                "entry_observation",
                "ark_watch_tap",
                "probe_window_start",
                "ad_close_tap",
                "esc_attempt_1",
                "esc_attempt_2",
                "esc_attempt_3",
                "post_esc_settle_start",
                "claim_tap",
                "run_end",
            ],
        )
        self.assertEqual(
            [(sample.sample_context, sample.esc_attempt_index) for sample in metadata.probe_samples],
            [
                ("post_entry", None),
                ("post_watch", None),
                ("pre_esc", 1),
                ("post_esc", 1),
                ("pre_esc", 2),
                ("post_esc", 2),
                ("pre_esc", 3),
                ("post_esc", 3),
                ("post_esc_settle", None),
            ],
        )
        self.assertTrue(metadata.claim_attempted)
        self.assertEqual(metadata.number_of_claim_taps, 1)
        self.assertEqual(len(metadata.claim_tap_timestamps), 1)
        self.assertEqual(sleeper.durations, [1.25, 6.0, 1.0, 1.25, 1.25, 2.5])

    def test_claim_ark_reward_records_probe_error_when_ui_dump_is_unavailable(self) -> None:
        runner = RecordingCommandRunner(
            captured_outputs={
                "adb -s emulator-5554 shell dumpsys window windows": (
                    "mCurrentFocus=Window{42 u0 com.google.android.gms/com.google.android.gms.ads.AdActivity}"
                ),
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
                ark_post_watch_probe_count=1,
                ark_post_watch_probe_interval_seconds=1.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        metadata = actuator.execute("claim_ark_reward")

        self.assertEqual(len(metadata.probe_samples), 5)
        self.assertIn("ui:", metadata.probe_samples[0].probe_error)
        self.assertIsNone(metadata.probe_samples[0].ui_dump_xml)
        self.assertIsNotNone(metadata.probe_samples[0].dumpsys_window_output)
        self.assertIsNotNone(metadata.probe_samples[0].dumpsys_activity_output)

    def test_claim_ark_reward_labels_entry_probe_when_it_stays_on_game_view(self) -> None:
        ui_dump_output = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<hierarchy><node text="Game view" /></hierarchy>'
        )
        runner = RecordingCommandRunner(
            captured_outputs={
                "adb -s emulator-5554 shell dumpsys window windows": (
                    "mCurrentFocus=Window{42 u0 com.example.idleplanetminer/com.unity3d.player.UnityPlayerActivity}"
                ),
                "adb -s emulator-5554 shell dumpsys activity activities": "ACTIVITY MANAGER ACTIVITIES",
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
                app_activity="com.unity3d.player.UnityPlayerActivity",
                claim_ark_reward_tap=TapPoint(x=333, y=444),
                claim_ark_reward_watch_tap=TapPoint(x=555, y=666),
                claim_ark_skip_tap=TapPoint(x=12, y=34),
                claim_ark_reward_final_claim_tap=TapPoint(x=777, y=889),
                ark_popup_wait_seconds=1.25,
                ark_ad_wait_seconds=4.0,
                ark_skip_close_wait_seconds=1.0,
                ark_return_wait_seconds=2.5,
                ark_post_watch_probe_count=1,
                ark_post_watch_probe_interval_seconds=1.0,
            ),
            command_runner=runner,
            sleep_fn=sleeper.sleep,
            monotonic_fn=clock.monotonic,
        )

        metadata = actuator.execute("claim_ark_reward")

        self.assertEqual(metadata.probe_samples[0].sample_context, "post_entry")
        self.assertEqual(metadata.probe_samples[0].ui_text_excerpt, "Game view")
        self.assertEqual(metadata.stage_events[1].stage_name, "entry_observation")
        self.assertIn("entry_inconclusive_immediate_probe", metadata.stage_events[1].detail)

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
        self.captured_outputs = {} if captured_outputs is None else dict(captured_outputs)

    def run(self, command: list[str]) -> None:
        self.commands.append(list(command))

    def capture(self, command: list[str]) -> str:
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

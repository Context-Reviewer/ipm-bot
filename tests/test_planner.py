from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.control.save_source import SavePlanetSnapshot, SaveProductionSlotSnapshot, SaveResourceSnapshot, SaveSnapshot
from ipm_bot.planner.planner import (
    decide_from_save_snapshot,
    decide_next_action,
    decide_next_action_details,
    format_active_smelter_lines,
)
from ipm_bot.save import parse_player_snapshot


class PlannerTests(unittest.TestCase):
    def test_activate_ad_boost_is_selected_when_boost_is_inactive(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=False,
            ark_reward_ready_to_claim=False,
        )

        decision = decide_next_action_details(snapshot)

        self.assertEqual(decision.selected_action, "activate_ad_boost")
        self.assertEqual(decision.decision_reason, "ad_boost_inactive")
        self.assertTrue(decision.actuation_required)
        self.assertEqual(decide_next_action(snapshot), "activate_ad_boost")

    def test_ark_ready_does_not_override_activate_ad_boost_in_production_planner(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=False,
            ark_reward_ready_to_claim=True,
        )

        decision = decide_next_action_details(snapshot)

        self.assertEqual(decision.selected_action, "activate_ad_boost")
        self.assertEqual(decision.decision_reason, "ad_boost_inactive")
        self.assertTrue(decision.actuation_required)

    def test_ark_ready_with_active_boost_now_idles_in_production_planner(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=True,
            ark_reward_ready_to_claim=True,
        )

        decision = decide_next_action_details(snapshot)

        self.assertEqual(decision.selected_action, "idle")
        self.assertEqual(decision.decision_reason, "no_action_needed")
        self.assertFalse(decision.actuation_required)
        self.assertEqual(decide_next_action(snapshot), "idle")

    def test_save_snapshot_can_refine_idle_reason_when_smelter_is_near_completion(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=True,
            ark_reward_ready_to_claim=False,
        )
        save_snapshot = _save_snapshot(timespan_left_seconds=3.25)

        decision = decide_next_action_details(snapshot, save_snapshot=save_snapshot)

        self.assertEqual(decision.selected_action, "idle")
        self.assertEqual(decision.decision_reason, "production_completion_imminent")
        self.assertFalse(decision.actuation_required)

    def test_save_snapshot_example_helpers_render_active_smelters_and_idle_hint(self) -> None:
        save_snapshot = _save_snapshot(timespan_left_seconds=12.5)

        decision = decide_from_save_snapshot(save_snapshot)
        lines = format_active_smelter_lines(save_snapshot)

        self.assertEqual(decision.selected_action, "idle")
        self.assertEqual(decision.decision_reason, "production_in_flight")
        self.assertEqual(
            lines,
            ("slot 0: recipe=4 duration=53.333s left=12.500s",),
        )

    def test_active_crafter_alone_still_counts_as_production_in_flight(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=True,
            ark_reward_ready_to_claim=False,
        )
        save_snapshot = SaveSnapshot(
            source_path="C:\\dev\\ipm-bot\\data\\playerInfo.dat",
            resources=(),
            planets=(),
            smelters=(),
            crafters=(
                SaveProductionSlotSnapshot(
                    index=1,
                    on=True,
                    recipe_number=3,
                    start_date=None,
                    end_date=None,
                    original_end_date=None,
                    timespan_left=timedelta(seconds=25.0),
                    seconds_completed=455.0,
                    duration_estimate=480.0,
                ),
            ),
        )

        decision = decide_next_action_details(snapshot, save_snapshot=save_snapshot)

        self.assertEqual(decision.selected_action, "idle")
        self.assertEqual(decision.decision_reason, "production_in_flight")
        self.assertFalse(decision.actuation_required)


def _snapshot(
    *,
    ad_boost_active: bool,
    ark_reward_ready_to_claim: bool,
) -> object:
    with tempfile.TemporaryDirectory() as tmpdir:
        save_path = Path(tmpdir) / "save.json"
        save_path.write_text(
            json.dumps(
                {
                    "adBoostActive": ad_boost_active,
                    "adsWatched": 1,
                    "saveTimestamp": "2026-03-22T14:31:05",
                    "arkRewardReadyToClaim": ark_reward_ready_to_claim,
                    "playerLevel": 5,
                }
            ),
            encoding="utf-8",
        )
        return parse_player_snapshot(save_path)


def _save_snapshot(*, timespan_left_seconds: float) -> SaveSnapshot:
    return SaveSnapshot(
        source_path="C:\\dev\\ipm-bot\\data\\playerInfo.dat",
        resources=(
            SaveResourceSnapshot(
                index=0,
                discovered=True,
                count=1.0,
                gathered_total=1.0,
                gathered_this_galaxy=1.0,
                sold_total=0.0,
                sold_this_galaxy=0.0,
            ),
        ),
        planets=(
            SavePlanetSnapshot(
                index=0,
                unlocked=True,
                mining_speed_level=1,
                speed_level=1,
                cargo_level=1,
                trip_start_date=None,
                trip_end_date=None,
            ),
        ),
        smelters=(
            SaveProductionSlotSnapshot(
                index=0,
                on=True,
                recipe_number=4,
                start_date=None,
                end_date=None,
                original_end_date=None,
                timespan_left=timedelta(seconds=timespan_left_seconds),
                seconds_completed=53.333 - timespan_left_seconds,
                duration_estimate=53.333,
            ),
        ),
        crafters=(),
    )


if __name__ == "__main__":
    unittest.main()

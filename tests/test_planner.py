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
from ipm_bot.planner.reward_state import map_snapshot_to_reward_state
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

    def test_activate_ad_boost_is_deferred_when_completion_is_imminent(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=False,
            ark_reward_ready_to_claim=False,
        )
        save_snapshot = _save_snapshot(timespan_left_seconds=3.25)

        decision = decide_next_action_details(snapshot, save_snapshot=save_snapshot)

        self.assertEqual(decision.selected_action, "activate_ad_boost")
        self.assertEqual(decision.decision_reason, "ad_boost_inactive")
        self.assertTrue(decision.actuation_required)

    def test_activate_ad_boost_is_unchanged_without_save_snapshot(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=False,
            ark_reward_ready_to_claim=False,
        )

        decision = decide_next_action_details(snapshot, save_snapshot=None)

        self.assertEqual(decision.selected_action, "activate_ad_boost")
        self.assertEqual(decision.decision_reason, "ad_boost_inactive")
        self.assertTrue(decision.actuation_required)

    def test_ark_ready_does_not_override_activate_ad_boost_in_production_planner(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=False,
            ark_reward_ready_to_claim=True,
        )

        decision = decide_next_action_details(snapshot)

        self.assertEqual(decision.selected_action, "claim_reward")
        self.assertEqual(decision.decision_reason, "reward_available:none")
        self.assertTrue(decision.actuation_required)

    def test_ark_ready_with_active_boost_now_idles_in_production_planner(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=True,
            ark_reward_ready_to_claim=True,
        )

        decision = decide_next_action_details(snapshot)

        self.assertEqual(decision.selected_action, "claim_reward")
        self.assertEqual(decision.decision_reason, "reward_available:none")
        self.assertTrue(decision.actuation_required)
        self.assertEqual(decide_next_action(snapshot), "claim_reward")

    def test_save_snapshot_can_refine_idle_reason_when_smelter_is_near_completion(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=True,
            ark_reward_ready_to_claim=False,
        )
        save_snapshot = _save_snapshot(timespan_left_seconds=3.25)

        decision = decide_next_action_details(snapshot, save_snapshot=save_snapshot)

        self.assertEqual(decision.selected_action, "idle")
        self.assertEqual(decision.decision_reason, "defer_ad_boost_for_imminent_completion")
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


    def test_ad_boost_suppressed_returns_idle_when_boost_would_be_selected(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=False,
            ark_reward_ready_to_claim=False,
        )

        decision = decide_next_action_details(
            snapshot,
            ad_boost_suppressed=True,
        )

        self.assertEqual(decision.selected_action, "idle")
        self.assertEqual(decision.decision_reason, "ad_boost_suppressed_after_repeated_failures")
        self.assertFalse(decision.actuation_required)

    def test_ad_boost_suppressed_does_not_affect_idle(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=True,
            ark_reward_ready_to_claim=False,
        )

        decision = decide_next_action_details(
            snapshot,
            ad_boost_suppressed=True,
        )

        self.assertEqual(decision.selected_action, "idle")
        self.assertNotEqual(decision.decision_reason, "ad_boost_suppressed_after_repeated_failures")

    def test_claim_reward_selected_when_boost_active_and_ark_ready(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=True,
            ark_reward_ready_to_claim=True,
        )

        decision = decide_next_action_details(snapshot)

        self.assertEqual(decision.selected_action, "claim_reward")
        self.assertEqual(decision.decision_reason, "reward_available:none")
        self.assertTrue(decision.actuation_required)

    def test_claim_reward_suppressed_returns_idle(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=True,
            ark_reward_ready_to_claim=True,
        )

        decision = decide_next_action_details(
            snapshot,
            claim_reward_suppressed=True,
        )

        self.assertEqual(decision.selected_action, "idle")
        self.assertEqual(decision.decision_reason, "claim_reward_suppressed_after_repeated_failures")
        self.assertFalse(decision.actuation_required)

    def test_pending_reward_type_selects_claim_reward_before_boost(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=False,
            ark_reward_ready_to_claim=False,
            pending_reward_type=2,
        )

        decision = decide_next_action_details(snapshot)

        self.assertEqual(decision.selected_action, "claim_reward")
        self.assertEqual(decision.decision_reason, "reward_available:pending_reward_type_2")
        self.assertTrue(decision.actuation_required)

    def test_pending_reward_type_selection_is_deterministic_for_multiple_reward_types(self) -> None:
        for pending_reward_type in (1, 2, 7):
            snapshot = _snapshot(
                ad_boost_active=True,
                ark_reward_ready_to_claim=False,
                pending_reward_type=pending_reward_type,
            )

            decision = decide_next_action_details(snapshot)

            self.assertEqual(decision.selected_action, "claim_reward")
            self.assertEqual(
                decision.decision_reason,
                f"reward_available:pending_reward_type_{pending_reward_type}",
            )

    def test_reward_state_mapping_exposes_event_reward_fields(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=True,
            ark_reward_ready_to_claim=False,
            pending_reward_type=3,
            reward_is_dark_matter=True,
            free_rewards_claimed=[True, False, True],
            miner_pass_rewards_claimed=[False, False],
        )

        reward_state = map_snapshot_to_reward_state(snapshot)

        self.assertEqual(reward_state.pending_reward_type_raw, 3)
        self.assertEqual(reward_state.reward_type, "pending_reward_type_3")
        self.assertTrue(reward_state.reward_available)
        self.assertFalse(reward_state.reward_requires_ad)
        self.assertTrue(reward_state.reward_claim_pending)
        self.assertIsNone(reward_state.reward_applied)
        self.assertTrue(reward_state.reward_is_dark_matter)
        self.assertEqual(reward_state.free_rewards_claimed_count, 2)
        self.assertEqual(reward_state.miner_pass_rewards_claimed_count, 0)

    def test_unattended_safe_allows_idle_and_ad_boost(self) -> None:
        snapshot_idle = _snapshot(
            ad_boost_active=True,
            ark_reward_ready_to_claim=False,
        )
        snapshot_boost = _snapshot(
            ad_boost_active=False,
            ark_reward_ready_to_claim=False,
        )

        decision_idle = decide_next_action_details(
            snapshot_idle,
            unattended_safe=True,
        )
        decision_boost = decide_next_action_details(
            snapshot_boost,
            unattended_safe=True,
        )

        self.assertEqual(decision_idle.selected_action, "idle")
        self.assertEqual(decision_boost.selected_action, "activate_ad_boost")

    def test_imminent_completion_takes_precedence_over_suppression(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=False,
            ark_reward_ready_to_claim=False,
        )
        save_snapshot = _save_snapshot(timespan_left_seconds=3.25)

        decision = decide_next_action_details(
            snapshot,
            save_snapshot=save_snapshot,
            ad_boost_suppressed=True,
        )

        self.assertEqual(decision.selected_action, "idle")
        self.assertEqual(decision.decision_reason, "ad_boost_suppressed_after_repeated_failures")

    def test_ark_reward_selected_even_when_completion_is_imminent(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=False,
            ark_reward_ready_to_claim=True,
        )
        save_snapshot = _save_snapshot(timespan_left_seconds=1.0)

        decision = decide_next_action_details(snapshot, save_snapshot=save_snapshot)

        self.assertEqual(decision.selected_action, "claim_reward")
        self.assertEqual(decision.decision_reason, "reward_available:none")
        self.assertTrue(decision.actuation_required)

    def test_ad_boost_selected_even_when_completion_is_imminent(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=False,
            ark_reward_ready_to_claim=False,
        )
        save_snapshot = _save_snapshot(timespan_left_seconds=1.0)

        decision = decide_next_action_details(snapshot, save_snapshot=save_snapshot)

        self.assertEqual(decision.selected_action, "activate_ad_boost")
        self.assertEqual(decision.decision_reason, "ad_boost_inactive")
        self.assertTrue(decision.actuation_required)


def _snapshot(
    *,
    ad_boost_active: bool,
    ark_reward_ready_to_claim: bool,
    pending_reward_type: int | None = None,
    reward_is_dark_matter: bool | None = None,
    free_rewards_claimed: list[bool] | None = None,
    miner_pass_rewards_claimed: list[bool] | None = None,
) -> object:
    with tempfile.TemporaryDirectory() as tmpdir:
        save_path = Path(tmpdir) / "save.json"
        payload: dict[str, object] = {
            "adBoostActive": ad_boost_active,
            "adsWatched": 1,
            "saveTimestamp": "2026-03-22T14:31:05",
            "arkRewardReadyToClaim": ark_reward_ready_to_claim,
            "playerLevel": 5,
        }
        if pending_reward_type is not None:
            payload["pendingRewardType"] = pending_reward_type
        if reward_is_dark_matter is not None:
            payload["rewardIsDarkMatterBool"] = reward_is_dark_matter
        if free_rewards_claimed is not None:
            payload["freeRewardsClaimed"] = free_rewards_claimed
        if miner_pass_rewards_claimed is not None:
            payload["minerPassRewardsClaimed"] = miner_pass_rewards_claimed
        save_path.write_text(
            json.dumps(payload),
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

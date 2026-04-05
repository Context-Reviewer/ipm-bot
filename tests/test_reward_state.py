from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.planner.reward_state import evaluate_reward_application, map_snapshot_to_reward_state
from ipm_bot.save import parse_player_snapshot


class RewardStateTests(unittest.TestCase):
    def test_maps_pending_reward_type_into_canonical_reward_state(self) -> None:
        snapshot = _snapshot(
            ad_boost_active=True,
            ark_reward_ready_to_claim=False,
            pending_reward_type=4,
            reward_is_dark_matter=True,
        )

        reward_state = map_snapshot_to_reward_state(snapshot)

        self.assertEqual(reward_state.pending_reward_type_raw, 4)
        self.assertEqual(reward_state.reward_type, "pending_reward_type_4")
        self.assertTrue(reward_state.reward_available)
        self.assertFalse(reward_state.reward_requires_ad)
        self.assertTrue(reward_state.reward_claim_pending)
        self.assertIsNone(reward_state.reward_applied)
        self.assertTrue(reward_state.reward_is_dark_matter)

    def test_evaluate_reward_application_accepts_ark_transition(self) -> None:
        before = _snapshot(
            ad_boost_active=True,
            ark_reward_ready_to_claim=True,
            pending_reward_type=1,
            arks_claimed=5,
        )
        after = _snapshot(
            ad_boost_active=True,
            ark_reward_ready_to_claim=False,
            pending_reward_type=0,
            arks_claimed=6,
        )

        reward_state = evaluate_reward_application(before, after)

        self.assertTrue(reward_state.reward_applied)
        self.assertFalse(reward_state.reward_available)

    def test_evaluate_reward_application_accepts_event_counter_transition(self) -> None:
        before = _snapshot(
            ad_boost_active=True,
            ark_reward_ready_to_claim=False,
            pending_reward_type=3,
            free_rewards_claimed=[False, False, False],
        )
        after = _snapshot(
            ad_boost_active=True,
            ark_reward_ready_to_claim=False,
            pending_reward_type=0,
            free_rewards_claimed=[True, False, False],
        )

        reward_state = evaluate_reward_application(before, after)

        self.assertTrue(reward_state.reward_applied)
        self.assertEqual(reward_state.free_rewards_claimed_count, 1)
        self.assertFalse(reward_state.reward_available)

    def test_reward_type_mapping_is_deterministic_for_multiple_pending_types(self) -> None:
        observed_types = [
            map_snapshot_to_reward_state(
                _snapshot(
                    ad_boost_active=True,
                    ark_reward_ready_to_claim=False,
                    pending_reward_type=pending_reward_type,
                )
            ).reward_type
            for pending_reward_type in (1, 2, 9)
        ]

        self.assertEqual(
            observed_types,
            [
                "pending_reward_type_1",
                "pending_reward_type_2",
                "pending_reward_type_9",
            ],
        )


def _snapshot(
    *,
    ad_boost_active: bool,
    ark_reward_ready_to_claim: bool,
    pending_reward_type: int | None = None,
    reward_is_dark_matter: bool | None = None,
    free_rewards_claimed: list[bool] | None = None,
    miner_pass_rewards_claimed: list[bool] | None = None,
    arks_claimed: int = 0,
) -> object:
    with tempfile.TemporaryDirectory() as tmpdir:
        save_path = Path(tmpdir) / "save.json"
        payload: dict[str, object] = {
            "adBoostActive": ad_boost_active,
            "adsWatched": 1,
            "saveTimestamp": "2026-03-22T14:31:05",
            "arkRewardReadyToClaim": ark_reward_ready_to_claim,
            "arksClaimed": arks_claimed,
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
        save_path.write_text(json.dumps(payload), encoding="utf-8")
        return parse_player_snapshot(save_path)


if __name__ == "__main__":
    unittest.main()

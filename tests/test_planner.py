from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.planner.planner import decide_next_action, decide_next_action_details
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


if __name__ == "__main__":
    unittest.main()

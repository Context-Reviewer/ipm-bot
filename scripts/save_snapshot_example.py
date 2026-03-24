"""Minimal SaveSnapshot example: acquire one save, print active smelters, show planner inputs."""

from __future__ import annotations

import argparse
from pathlib import Path

from ipm_bot.control.composition import add_tick_composition_arguments, build_save_source
from ipm_bot.control.save_source import prepare_and_load_save_snapshot
from ipm_bot.planner.planner import (
    decide_from_save_snapshot,
    decide_next_action_details,
    format_active_smelter_lines,
)
from ipm_bot.save import parse_player_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Acquire one SaveSnapshot and show how the planner can consume it."
    )
    add_tick_composition_arguments(parser)
    args = parser.parse_args()

    save_source = build_save_source(args)
    metadata, save_snapshot = prepare_and_load_save_snapshot(save_source, args.save_path)
    prepared_save_path = Path(metadata.prepared_local_path)
    player_snapshot = parse_player_snapshot(prepared_save_path)

    print(f"Save source: {metadata.save_source_type}")
    print(f"Prepared path: {prepared_save_path}")
    print("Active smelters:")
    active_lines = format_active_smelter_lines(save_snapshot)
    if active_lines:
        for line in active_lines:
            print(f"  {line}")
    else:
        print("  none")

    save_only_decision = decide_from_save_snapshot(save_snapshot)
    planner_decision = decide_next_action_details(
        player_snapshot,
        save_snapshot=save_snapshot,
    )

    print(
        "SaveSnapshot timing decision: "
        f"{save_only_decision.selected_action} "
        f"({save_only_decision.decision_reason})"
    )
    print(
        "Full planner decision: "
        f"{planner_decision.selected_action} "
        f"({planner_decision.decision_reason})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

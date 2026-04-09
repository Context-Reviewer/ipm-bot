# Architecture

The bot is intentionally state-first:

1. Read game state from `playerInfo.dat`.
2. Normalize it into a planner-friendly model.
3. Decide on the next action.
4. Execute through emulator / ADB input.
5. Verify the resulting save transition.

The production truth boundary is save-backed state, not UI observation.

Current design notes:

- [Ad/Reward Automation](ad_reward_automation.md)

Supporting BlueStacks-side artifact notes:

- [`bluestacks_artifacts.md`](C:\dev\ipm-bot\docs\architecture\bluestacks_artifacts.md)

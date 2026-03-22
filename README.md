# ipm-bot

Save-driven automation tooling for Idle Planet Miner.

This repo is the new clean runtime project for the bot architecture:

- `save`: read-only save parsing, schema mapping, normalized state
- `planner`: decision logic driven by parsed game state
- `actuator`: emulator / ADB input execution
- `verifier`: post-action validation using save deltas
- `ui`: thin visual helpers only when state cannot be inferred from save data

The reverse-engineering and experiment tooling remains in:

- `C:\Users\lwpar\Desktop\ipm_project`

## Layout

```text
src/ipm_bot/save
src/ipm_bot/planner
src/ipm_bot/actuator
src/ipm_bot/verifier
src/ipm_bot/ui
docs/architecture
docs/save_schema
docs/experiments
data/samples
data/captures
data/reports
logs
archive
```

## Initial priorities

1. Extract a field inventory for `SaveLoad.PlayerData`.
2. Build a read-only save parser around the recovered schema.
3. Define a normalized state model for planning decisions.
4. Add a thin ADB actuation layer.
5. Verify state transitions from subsequent saves.

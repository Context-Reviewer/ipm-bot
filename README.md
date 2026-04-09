# ipm-bot

Save-driven automation tooling for Idle Planet Miner.

This repo is the new clean runtime project for the bot architecture:

- `save`: read-only save parsing, schema mapping, normalized state
- `planner`: decision logic driven by parsed game state
- `actuator`: emulator / ADB input execution
- `verifier`: post-action validation using save deltas
- `ui`: thin visual helpers only when state cannot be inferred from save data

The project is intentionally save-grounded and fail-closed:

- save state is authoritative truth
- UI/runtime are actuation surfaces, not truth sources
- unsupported or unproven transitions must resolve to `FAIL` or `AMBIGUOUS`

The reverse-engineering and experiment tooling remains in:

- `C:\Users\lwpar\Desktop\ipm_project`

## Artifact discovery

The repo now includes a safe artifact discovery CLI for package-focused census/snapshot/diff work:

```text
python -m ipm_bot.artifacts census
python -m ipm_bot.artifacts snapshot
python -m ipm_bot.artifacts diff <before_snapshot_dir> <after_snapshot_dir>
```

See `docs/architecture/artifact_discovery.md` for the safety model, output structure, and exact Windows commands.

See `docs/architecture/ad_reward_automation.md` for the ad/reward automation objective and the research-vs-production boundary.

For IL2CPP reverse-engineering output, the artifact pipeline now includes an assembly triage step so research starts in the right place:

- `Assembly-CSharp.dll` first for game-owned schema and runtime/save field mapping
- `Unity.LevelPlay.dll` for rewarded-ad callback vocabulary
- `PlayFab.dll` and `Firebase.Firestore.dll` only for backend/cloud side paths
- framework DLLs as background context only

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

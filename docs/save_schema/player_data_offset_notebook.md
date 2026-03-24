# PlayerData Offset Notebook

## Current Model

- `SaveLoad.PlayerData` is the strongest schema anchor for local `playerInfo.dat`.
- `0xC1C1 + index` is the strongest current candidate for the persisted `smelterOn` per-index boolean region.
- `0xC3DD + index` is the strongest current candidate for a parallel smelter companion region.
- `0xC3F1` and `0xC60D` are the strongest current crafter-state candidates.
- Larger recurring clusters are treated as timer/progress/date companions until proven otherwise.

## Protocol

- Take a baseline snapshot.
- Perform exactly one in-game toggle.
- Wait `50` seconds to cross autosave.
- Take a second snapshot.
- Run `artifacts diff`.
- Run `save bytes-diff` on the copied `playerInfo.dat` files.

## Confirmed Offsets

| Feature | Index | Offset | Flip | Confidence | Note |
|---|---:|---|---|---|---|
| Smelter | 0 | `0xC1C1` | `00 <-> 01` | High | primary candidate |
| Smelter | 0 | `0xC3DD` | `00 <-> 01` | High | companion candidate |
| Smelter | 1 | `0xC1C2` | `00 <-> 01` | High | primary candidate |
| Smelter | 1 | `0xC3DE` | `00 <-> 01` | High | companion candidate |
| Crafter | 0 | `0xC3F1` | `00 <-> 01` | High | primary candidate |
| Crafter | 0 | `0xC60D` | `00 <-> 01` | High | companion candidate |

## Cluster Notes

| Feature | Index | Anchor | Nearby Regions | Repeatability | Hypothesis |
|---|---:|---|---|---|---|
| Smelter | 0 | `0xC1C1` | `0x72xx`, `0x75xx`, `0x77xx`, `0x81xx`, `0xC2xx-C3xx` | reversible on/off | timers/progress/date companions |
| Smelter | 1 | `0xC1C2` | `0x72xx`, `0x75xx`, `0x77xx`, `0x81xx`, `0xC2xx-C3xx` | reversible on/off | timers/progress/date companions |
| Crafter | 0 | `0xC3F1` | `0x72xx`, `0x75xx`, `0x77xx`, `0x81xx`, `0xC4xx-C6xx` | reversible on/off | timers/progress/date companions |

## Evidence Summary

- Smelter 0 on: `0xC1C1`, `0xC3DD` -> `01`
- Smelter 0 off: `0xC1C1`, `0xC3DD` -> `00`
- Smelter 1 on: `0xC1C2`, `0xC3DE` -> `01`
- Smelter 1 off: `0xC1C2`, `0xC3DE` -> `00`
- Crafter 0 on: `0xC3F1`, `0xC60D` -> `01`
- Crafter 0 off: `0xC3F1`, `0xC60D` -> `00`

## Chronological Experiment Log

### Smelter 0 on

- Before snapshot:
  - `C:\dev\ipm-bot\data\artifacts\snapshots\2026-03-24T02-02-20-524494Z_snapshot_com.TironiumTech.IdlePlanetMiner`
- After snapshot:
  - `C:\dev\ipm-bot\data\artifacts\snapshots\2026-03-24T02-03-30-755494Z_snapshot_com.TironiumTech.IdlePlanetMiner`
- Artifact diff:
  - `C:\dev\ipm-bot\data\artifacts\diffs\2026-03-24T02-04-05-904382Z_artifact_diff`
- Key reversible candidates:
  - `0x0000C1C1: 00 -> 01`
  - `0x0000C3DD: 00 -> 01`

### Smelter 0 off

- Before snapshot:
  - `C:\dev\ipm-bot\data\artifacts\snapshots\2026-03-24T02-03-30-755494Z_snapshot_com.TironiumTech.IdlePlanetMiner`
- After snapshot:
  - `C:\dev\ipm-bot\data\artifacts\snapshots\2026-03-24T02-07-34-369648Z_snapshot_com.TironiumTech.IdlePlanetMiner`
- Artifact diff:
  - `C:\dev\ipm-bot\data\artifacts\diffs\2026-03-24T02-07-55-367783Z_artifact_diff`
- Key reversible candidates:
  - `0x0000C1C1: 01 -> 00`
  - `0x0000C3DD: 01 -> 00`

### Smelter 1 on

- Before snapshot:
  - `C:\dev\ipm-bot\data\artifacts\snapshots\2026-03-24T02-07-34-369648Z_snapshot_com.TironiumTech.IdlePlanetMiner`
- After snapshot:
  - `C:\dev\ipm-bot\data\artifacts\snapshots\2026-03-24T02-10-34-881346Z_snapshot_com.TironiumTech.IdlePlanetMiner`
- Artifact diff:
  - `C:\dev\ipm-bot\data\artifacts\diffs\2026-03-24T02-10-54-367302Z_artifact_diff`
- Key reversible candidates:
  - `0x0000C1C2: 00 -> 01`
  - `0x0000C3DE: 00 -> 01`

### Smelter 1 off

- Before snapshot:
  - `C:\dev\ipm-bot\data\artifacts\snapshots\2026-03-24T02-10-34-881346Z_snapshot_com.TironiumTech.IdlePlanetMiner`
- After snapshot:
  - `C:\dev\ipm-bot\data\artifacts\snapshots\2026-03-24T02-13-44-187867Z_snapshot_com.TironiumTech.IdlePlanetMiner`
- Artifact diff:
  - `C:\dev\ipm-bot\data\artifacts\diffs\2026-03-24T02-14-02-944122Z_artifact_diff`
- Key reversible candidates:
  - `0x0000C1C2: 01 -> 00`
  - `0x0000C3DE: 01 -> 00`

### Crafter 0 on

- Before snapshot:
  - `C:\dev\ipm-bot\data\artifacts\snapshots\2026-03-24T02-15-40-285124Z_snapshot_com.TironiumTech.IdlePlanetMiner`
- After snapshot:
  - `C:\dev\ipm-bot\data\artifacts\snapshots\2026-03-24T02-16-45-166633Z_snapshot_com.TironiumTech.IdlePlanetMiner`
- Artifact diff:
  - `C:\dev\ipm-bot\data\artifacts\diffs\2026-03-24T02-16-59-803209Z_artifact_diff`
- Key reversible candidates:
  - `0x0000C3F1: 00 -> 01`
  - `0x0000C60D: 00 -> 01`
- Additional moving candidate:
  - `0x0000C419: 02 -> 00`

### Crafter 0 off

- Before snapshot:
  - `C:\dev\ipm-bot\data\artifacts\snapshots\2026-03-24T02-16-45-166633Z_snapshot_com.TironiumTech.IdlePlanetMiner`
- After snapshot:
  - `C:\dev\ipm-bot\data\artifacts\snapshots\2026-03-24T02-19-33-788532Z_snapshot_com.TironiumTech.IdlePlanetMiner`
- Artifact diff:
  - `C:\dev\ipm-bot\data\artifacts\diffs\2026-03-24T02-20-00-272382Z_artifact_diff`
- Key reversible candidates:
  - `0x0000C3F1: 01 -> 00`
  - `0x0000C60D: 01 -> 00`
- Non-primary companion from on-run did not cleanly behave as a simple mirrored boolean:
  - `0x0000C419`

## Schema Anchors From Manual IL2CPP Review

- `SaveLoad.PlayerData` contains direct production-state fields:
  - `smelterOn`
  - `smelterStartDate`
  - `smelterEndDate`
  - `smelterSecondsCompleted`
  - `crafterOn`
  - `crafterStartDate`
  - `crafterEndDate`
  - `crafterSecondsCompleted`
- `SaveLoad.PlayerData` also contains persisted ad/reward fields:
  - `lastAdWatchedDate`
  - `adsWatched`
  - `arksClaimed`
  - `pendingRewardType`
  - `rewardIsDarkMatterBool`
  - `arkRewardReadyToClaim`

## Next Experiments

1. Same smelter `on`, compare `+50s` vs `+120s`.
2. Same smelter `on -> off` with controlled timing.
3. Second crafter index to test stride behavior.

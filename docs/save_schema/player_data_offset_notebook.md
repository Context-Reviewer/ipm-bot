# PlayerData Offset Notebook

> **v2 — Parser-Derived (2026-03-24)**
> All offsets below are deterministic, produced by `sub_records.py` with 100% file coverage.
> Manual offset assignments from v1 have been superseded.

## Format

- `playerInfo.dat` is a raw .NET `BinaryFormatter` stream (uncompressed).
- `playerInfoBackup.dat` is a near-synchronous mirror copy (~7ms later), NOT a previous save state.
- Root class: `SaveLoad+PlayerData`, 478 top-level members, 228 MemberReference sub-records.

## ⚠ Corrections From v1

| Offset | v1 Assignment (WRONG) | v2 Assignment (CORRECT) |
|---|---|---|
| `0xC1C1` | `smelterOn[0]` | **`smeltRecipeSelectedBool[0]`** (ref 63) |
| `0xC1C2` | `smelterOn[1]` | **`smeltRecipeSelectedBool[1]`** (ref 63) |
| `0xC3F1` | `crafterOn[0]` | **`craftRecipeSelectedBool[0]`** (ref 72) |

**Root cause:** BinaryFormatter serializes sub-records in object-ID order, not field-semantic order.
"Nearby in file" ≠ "related in meaning". The v1 experiment correctly observed both `0xC1C1` and `0xC3DD`
flipping together on smelter toggle — but misidentified which was `smelterOn` and which was
`smeltRecipeSelectedBool`. Both flip because starting a smelter both selects a recipe AND sets on=true.

## Smelter Arrays (10 slots each)

| Ref | Type | Base Offset | Size | Field |
|---:|---|---|---:|---|
| 63 | BOOLEAN[10] | `0xC1C1` | 10 | `smeltRecipeSelectedBool` |
| 64 | BOOLEAN[10] | `0xC1D5` | 10 | `alternateSmeltRecipeSelected` |
| 65 | INT32[10] | `0xC1E9` | 40 | `smeltRecipeNumber` |
| 66 | DATETIME[10] | `0xC21B` | 80 | `smelterStartDate` |
| 67 | DATETIME[10] | `0xC275` | 80 | `smelterEndDate` |
| 68 | DATETIME[10] | `0xC2CF` | 80 | `smelterOriginalEndDate` |
| 69 | TIMESPAN[10] | `0xC329` | 80 | `smelterTimespanLeft` |
| 70 | DOUBLE[10] | `0xC383` | 80 | `smelterSecondsCompleted` |
| **71** | **BOOLEAN[10]** | **`0xC3DD`** | **10** | **`smelterOn`** |

## Crafter Arrays (10 slots each)

| Ref | Type | Base Offset | Size | Field |
|---:|---|---|---:|---|
| 72 | BOOLEAN[10] | `0xC3F1` | 10 | `craftRecipeSelectedBool` |
| 73 | BOOLEAN[10] | `0xC405` | 10 | `alternateCraftRecipeSelected` |
| 74 | INT32[10] | `0xC419` | 40 | `craftRecipeNumber` |
| 75 | DATETIME[10] | `0xC44B` | 80 | `crafterStartDate` |
| 76 | DATETIME[10] | `0xC4A5` | 80 | `crafterEndDate` |
| 77 | DATETIME[10] | `0xC4FF` | 80 | `crafterOriginalEndDate` |
| 78 | TIMESPAN[10] | `0xC559` | 80 | `crafterTimespanLeft` |
| 79 | DOUBLE[10] | `0xC5B3` | 80 | `crafterSecondsCompleted` |
| **80** | **BOOLEAN[10]** | **`0xC60D`** | **10** | **`crafterOn`** |

## Save-Pipeline Metadata

| Offset | Type | Field | Note |
|---|---|---|---|
| `0x3648` | DATETIME | save timestamp 1 | ~7ms earlier in active vs backup |
| `0x3D55` | DATETIME | save timestamp 2 | ~7ms earlier in active vs backup |

## High-Value Resource/Economy Arrays

| Ref | Type | Base Offset | Size | Field |
|---:|---|---|---:|---|
| 4 | BOOLEAN[120] | `0x4276` | 120 | `resourceDiscovered` |
| 5 | SINGLE[120] | `0x42F8` | 480 | `resourceCount` |
| 9 | SINGLE[120] | `0x5900` | 480 | `resourceGatheredTotal` |
| 11 | SINGLE[120] | `0x5CD4` | 480 | `resourceSoldTotal` |

## Planet Arrays (76 slots)

| Ref | Type | Base Offset | Size | Field |
|---:|---|---|---:|---|
| 19 | INT32[76] | `0x6C24` | 304 | `miningSpeedLevel` |
| 20 | INT32[76] | `0x6D5E` | 304 | `speedLevel` |
| 21 | INT32[76] | `0x6E98` | 304 | `cargoLevel` |
| 23 | BOOLEAN[76] | `0x710C` | 76 | `planetUnlocked` |
| 26 | DATETIME[76] | `0x7506` | 608 | `tripStartDate` |
| 27 | DATETIME[76] | `0x7770` | 608 | `tripEndDate` |

## Element Addressing

To address element `[i]` within an array:

```
byte_offset = base_offset + (i * element_size)
```

Element sizes: BOOLEAN=1, INT32=4, SINGLE=4, DOUBLE=8, DATETIME=8, TIMESPAN=8

## Historical Experiment Log

Preserved from v1 for provenance. All interpretations below should use v2 field names.

- Smelter toggle experiments correctly observed `0xC1C1` and `0xC3DD` flipping together.
- v1 incorrectly labeled `0xC1C1` as `smelterOn`. Parser proves it is `smeltRecipeSelectedBool`.
- The "companion" hypothesis is disproven — both offsets are real distinct fields that co-flip on toggle.
- Crafter experiment observed `0xC419` changing (`02 → 00`), now identified as `craftRecipeNumber[0]`.

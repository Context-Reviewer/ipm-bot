# DummyDll PlayerData Anchor

## Provenance

This note captures grounded findings from an externally generated Il2CppDumper `DummyDll.zip` artifact.

Artifact examined:

- `c:\Users\lwpar\Downloads\Il2CppDumper-master-src\Il2CppDumper-master\Il2CppDumper\bin\Release\net8.0\DummyDll.zip`

Important boundary:

- the repo does **not** run Il2CppDumper itself
- this artifact was produced outside the repo boundary
- the repo may safely consume the resulting metadata as an external input

## Strongest Confirmed Type Relationships

From `DummyDll/Assembly-CSharp.dll` metadata:

- `SaveLoad` exists as a top-level game type
- `SaveLoad` exposes `ReadData`
- `ReadData` is the clearest save-deserialization entrypoint currently identified
- `PlayerData` exists as the save-state payload type used by `SaveLoad`
- `Ads` exists as a separate runtime/controller type

This matters because it cleanly separates:

- persisted save schema work, which belongs under `SaveLoad.PlayerData`
- runtime rewarded-ad control flow, which belongs under `Ads`

## Why This Is A Better Anchor Than The Loose Ads Snippet

The earlier decompiled `Ads` snippet was useful for runtime semantics, but it could not by itself prove what belonged to the persisted save object.

The DummyDll metadata closes that gap:

- `PlayerData` directly contains persisted ad/reward fields such as `adBoostActive`, `lastAdWatchedDate`, `adsWatched`, `arksClaimed`, `pendingRewardType`, `rewardIsDarkMatterBool`, `gdprConsentAcquired`, `arkRewardReadyToClaim`, `dailyGiftReadyBool`, and `dailyGiftAdWatchedBool`
- `Ads` separately contains runtime UI/controller members such as `adPanel`, `adWaitingPanel`, `adAvailableBool`, `adFailedBool`, and `topRightAdIcon2`

That split is exactly the distinction the repo needs.

## Confirmed Persisted Ad/Reward Fields In `PlayerData`

The externally generated metadata confirms the following `PlayerData` members exist:

- `adBoostActive`
- `adBoostStartDate`
- `lastAdWatchedDate`
- `adsWatched`
- `arksClaimed`
- `pendingRewardType`
- `rewardIsDarkMatterBool`
- `gdprConsentAcquired`
- `arkRewardReadyToClaim`
- `dailyGiftReadyBool`
- `dailyGiftAdWatchedBool`
- `disableAdsUnlockedBool`

This strengthens confidence that the repo is correct to treat these names as save-backed schema candidates.

## Confirmed Runtime-Only Ad Controller Signals In `Ads`

The `Ads` type contains members that look like controller/UI state rather than persisted save state, including:

- `adPanel`
- `adPanelOpenBool`
- `adPanel2`
- `adPanel2OpenBool`
- `adWaitingPanel`
- `adWaitingCancelButtonObject`
- `adAvailableBool`
- `adFailedBool`
- `adStartedFromBoost`
- `nextAdSeconds`
- `AdsConsecutiveClick`

These should remain runtime/controller evidence unless save-delta experiments prove otherwise.

## Practical Repo Implications

The highest-leverage use of this artifact is:

1. treat `PlayerData` as the authoritative name anchor for persisted schema work
2. treat `SaveLoad.ReadData` as the best current entrypoint for understanding the save decode path
3. treat `Ads` as runtime flow evidence for actuator behavior, not as the persisted schema root

In other words:

- parser additions should be justified from `PlayerData`
- actuator assumptions should be justified from runtime/controller types like `Ads`
- verifier expectations should remain tied to save-backed transitions, not controller booleans

## Current Repo Alignment

This artifact supports the current direction of:

- `src/ipm_bot/save/schema.py`
- `src/ipm_bot/save/parser.py`
- `docs/save_schema/player_data_offset_notebook.md`
- `docs/experiments/ads_class_runtime_notes.md`

It does not, by itself, establish byte offsets or persistence timing. Those still require `playerInfo.dat` structure analysis and save-delta validation.

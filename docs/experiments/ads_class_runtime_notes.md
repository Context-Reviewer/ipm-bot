# Ads Class Runtime Notes

## Provenance

This note distills a decompiled `Ads` class snippet captured outside the repo and later pasted into the project workflow. The snippet includes:

- ad lifecycle methods such as `AdPanelOpen`, `ShowRewardedAd`, `RewardedVideoAdCompleted`, `ClaimReward`, and `StoreOpenFromAdPanelChange`
- runtime/UI fields such as `adPanel`, `adWaitingPanel`, `adAvailableBool`, `adFailedBool`, and `topRightAdIcon2`
- several fields whose names overlap with persisted save fields already used by `ipm-bot`

The pasted artifact is useful as semantic evidence about the game's rewarded-ad controller, but it is not itself a `SaveLoad.PlayerData` field map.

## What This Artifact Reliably Tells Us

The class strongly suggests the rewarded-ad flow has explicit runtime branches for:

- opening the ad panel
- starting a rewarded watch
- handling completion callbacks
- claiming the reward after completion
- dealing with store redirects from the ad flow

That aligns with the existing `activate_ad_boost` actuator work in `src/ipm_bot/actuator/adb.py`, especially the logic that treats ad exit and store redirect handling as bounded runtime concerns rather than save-schema concerns.

## Overlap With Save-Backed Fields

The following names appear in the decompiled `Ads` class and also make sense as persisted state already tracked by the repo:

- `lastAdWatchedDate`
- `adsWatched`
- `arksClaimed`
- `pendingRewardType`
- `rewardIsDarkMatterBool`
- `arkRewardReadyToClaim`

This overlap is useful because it reinforces the naming and intent of the save-backed fields already parsed in:

- `src/ipm_bot/save/schema.py`
- `src/ipm_bot/save/parser.py`

It does **not** prove file offsets, serialization order, or persistence semantics by itself. Persistence still has to be established from `playerInfo.dat` structure or save-delta experiments.

## What We Should *Not* Infer From It

This artifact should **not** be used as direct evidence for:

- save-file byte offsets
- `BinaryFormatter` member order
- planner contracts
- verifier expectations
- tap coordinates
- provider-specific UI layouts

The `RVA` / `VA` / `Offset` values in the snippet are code addresses for the game binary, not `playerInfo.dat` offsets.

Likewise, fields such as the following are best treated as runtime/controller state until separately proven persistent:

- `adAvailableBool`
- `adFailedBool`
- `adPanelOpenBool`
- `adPanel2OpenBool`
- `adStartedFromBoost`
- `gdprConsentAcquired`
- `nextAdSeconds`
- `AdsAllowed`

UI object references such as `adPanel`, `adWaitingPanel`, `claimObject`, `disableAdsButtonObject`, and `topRightAdIcon2` are clearly runtime scene/controller members and do not belong in the save parser.

## Correct Way To Leverage This In `ipm-bot`

The highest-value use of this artifact is:

1. as a semantic cross-check for names already recovered from `SaveLoad.PlayerData`
2. as evidence that rewarded-ad execution has runtime-only branches the actuator must handle safely
3. as justification for treating post-watch claim/store behavior as actuation concerns, not parser assumptions

In practice, that means:

- keep save parsing grounded in `playerInfo.dat` and proven field mappings
- keep actuator logic grounded in observable runtime behavior
- only promote new ad-related fields into the parser after persistence is demonstrated in real saves

## Immediate Repo Implication

This artifact supports the current project split:

- save parser: persisted truth only
- actuator: runtime ad-flow handling
- verifier: save-backed proof of outcome

It is helpful context, but it does not by itself justify adding new parser fields or changing planner/verifier contracts.

# Ad/Reward Automation

## Objective

`ipm-bot` should automate ad-related actions in Idle Planet Miner while remaining deterministic, unattended-safe, and epistemically honest.

For this project, durable save state is the only production truth boundary. Android/UI/runtime behavior exists to let the bot act, not to let it pretend it knows more than it does.

## Core Model

The bot follows these rules:

1. save state is authoritative truth
2. UI and Android runtime are actuation surfaces plus transient observation only
3. any action outcome not proven by save-backed evidence must not be treated as success
4. unknown or unresolved transitions must collapse to `FAIL` or `AMBIGUOUS`, never silent `PASS`

That model drives the closed-loop system:

`ADB/UI actuation -> save pull -> save parse -> planner decision -> actuator execution -> save repull/watcher -> verifier -> receipt`

## Production Boundary

Production logic for ad automation must remain:

- deterministic
- bounded
- save-grounded
- fail-closed

Production logic is explicitly **not** trying to:

- identify UI elements via OCR
- parse UI text or use fuzzy strings
- infer success from actuation completion
- classify ad families probabilistically
- replace save-backed truth with memory inspection or runtime heuristics

The actuator may branch across known runtime families, but those branches are execution tactics only. They are never truth-bearing on their own.

## `activate_ad_boost` Success Criteria

For action `activate_ad_boost`, success means the save-backed required contract post-state is proven:

- `ad_boost_active == true`

Supporting changes such as the following are useful corroboration but are insufficient by themselves:

- `save_timestamp` changed
- `ads_watched` changed

This is why the verifier must continue to treat:

- supporting-field-only transitions as `AMBIGUOUS`
- no-save-change outcomes as `FAIL`
- reward-followup taps without save proof as non-success

## Runtime Branching Model

The actuator should be able to survive heterogeneous rewarded-ad flows, including:

- standard rewarded ads that return directly to the game
- rewarded ads that return into a reward-selection panel
- stubborn fullscreen ad families that ignore bounded `KEYCODE_BACK`
- store redirect / market deep-link excursions during the ad flow

The current architecture allows bounded handling for these branches:

- explicit allowlists for known focused activities
- bounded back/return policy for normal ad flows
- bounded deterministic exit override for stubborn fullscreen families
- bounded claim tap sequence after return to the game
- optional bounded reward-selection branch taps after return

All of those are non-truth-bearing. PASS still requires save proof.

## Research Boundary

Reverse engineering and live memory inspection can still be useful, but only as research instrumentation.

Research-side work may include:

- identifying candidate runtime fields in `Ads` or nearby objects
- observing field timing around ad open, reward callback, ad close, game return, and claim resolution
- correlating runtime field transitions with receipt stage events, Android focus/activity changes, and save diffs

That research is intended to answer questions like:

- when `adsWatched` increments relative to reward and close callbacks
- when `arkRewardReadyToClaim` flips relative to return-to-game timing
- whether `pendingRewardType` is set before reward-choice UI appears
- whether any runtime signal corresponds to watch completion or close-gate availability

Even if such signals exist, production truth remains save-backed unless a discovered signal is extraordinarily stable, attributable, and intentionally promoted through a separate design decision.

## Architectural Consequences

This objective implies the following repo-level design choices:

- parser work should stay anchored to persisted `SaveLoad.PlayerData` fields
- planner decisions should depend on parsed durable state, not UI observations
- actuator logic may use explicit bounded runtime handling, but must not infer truth from it
- verifier outcomes should remain save-backed and fail-closed
- receipts should keep recording actuator metadata so runtime branches can be studied without making them authoritative

## Current Intent

The near-term goal is not to semantically understand every ad family. The goal is to build a bot that can act deterministically in a hostile ad environment and know exactly when it does not actually know.

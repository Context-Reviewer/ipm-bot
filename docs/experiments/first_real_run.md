# First Real Run

## Purpose

This procedure runs the first real emulator-backed experiment through the governed one-shot harness:

- one save preparation step
- one control tick
- one receipt
- one experiment manifest
- one deterministic exit code

Use this to validate the full path:

1. save acquisition
2. parsing and planning
3. actuation
4. save-based verification
5. receipt and manifest persistence

This is a controlled experiment, not autonomous automation.

## Canonical Command

Replace the operator-supplied values before running:

```powershell
python -m ipm_bot.experiment `
  --save-source adb-pull `
  --actuator adb `
  --adb-path adb `
  --adb-serial 127.0.0.1:5555 `
  --prepared-save-path C:\dev\ipm-bot\data\runs\current\playerInfo.dat `
  --timeout-seconds 30 `
  --poll-interval-seconds 2 `
  --app-package com.TironiumTech.IdlePlanetMiner `
  --app-activity com.unity3d.player.UnityPlayerActivity `
  --activate-ad-boost-tap X,Y `
  --claim-ark-reward-tap X,Y `
  /sdcard/Android/data/com.TironiumTech.IdlePlanetMiner/files/playerInfo.dat
```

## Required Operator-Supplied Values

`--adb-serial`

- The emulator or device serial visible in `adb devices`
- Example: `127.0.0.1:5555`

Remote save path

- The final positional argument
- This is the device-side `playerInfo.dat` path used by `--save-source adb-pull`
- Example:
  `/sdcard/Android/data/com.TironiumTech.IdlePlanetMiner/files/playerInfo.dat`

`--app-package`

- Android package name for Idle Planet Miner
- Used by the ADB actuator when foregrounding the app

`--app-activity`

- Android activity name paired with `--app-package`
- Used when the ADB actuator launches the app explicitly

`--activate-ad-boost-tap`

- Screen coordinates for the ad boost UI interaction
- Format: `X,Y`
- Example: `540,960`

`--claim-ark-reward-tap`

- Screen coordinates for the Ark reward UI interaction
- Format: `X,Y`
- Example: `540,780`

## Pre-Run Checklist

Before the first real run, confirm all of the following:

1. ADB can see the emulator or device.

```powershell
adb devices
```

2. Idle Planet Miner is installed on the emulator or device.
3. The remote save path exists and is readable.
4. The local prepared-save directory is writable.
5. The package and activity values are correct.
6. The tap coordinates are known and intentional.
7. The game is in a calm, known state before the run.
8. You understand which planner outcome you are expecting:
   `idle`, `claim_ark_reward`, or `activate_ad_boost`.

## Recommended First-Run Order

Use this order to reduce uncertainty:

1. Validate a state that should produce `idle`.
2. Validate a state that should produce `claim_ark_reward`.
3. Validate a state that should produce `activate_ad_boost`.

This isolates problems in:

- save acquisition
- planner choice
- tap coordinates
- verification timing

## Run Procedure

1. Open the emulator and confirm the game is installed.
2. Confirm ADB connectivity with `adb devices`.
3. Put the game into the state you want to test.
4. Run the experiment command once.
5. Record the console output:
   `Experiment ID`, `Receipt path`, `Manifest path`, `Exit code`
6. Check the PowerShell exit code immediately after the run:

```powershell
$LASTEXITCODE
```

## Post-Run Checklist

After the command completes, verify all of the following:

1. Exactly one receipt was produced.
2. Exactly one experiment manifest was produced.
3. The manifest points to the receipt path printed by the CLI.
4. The receipt shows the expected selected action.
5. The receipt shows the expected save-source provenance.
6. The receipt shows the expected actuator execution metadata.
7. The final status and failure reason are classified, not implied.

## Inspecting the Receipt

Open the receipt JSON from the printed `Receipt path`.

Confirm these sections:

- `planner_decision`
- `save_source`
- `actuator_execution`
- `contract_identity`
- `runtime_context`
- `final_status`
- `failure_reason`

Key fields to check:

- `planner_decision.selected_action`
- `planner_decision.decision_reason`
- `actuation_attempted`
- `save_source.save_source_type`
- `save_source.original_requested_path`
- `save_source.prepared_local_path`
- `actuator_execution.actuator_type`
- `actuator_execution.actuator_execution_status`
- `actuator_execution.actuator_command_summary`
- `final_status`
- `failure_reason`

## Inspecting the Manifest

Open the manifest JSON from the printed `Manifest path`.

Confirm these fields:

- `experiment_id`
- `started_at_utc`
- `completed_at_utc`
- `actuator_type`
- `save_source_type`
- `original_requested_save_path`
- `prepared_local_save_path`
- `receipt_path`
- `exit_code`
- `selected_action`
- `final_status`
- `failure_reason`

The manifest is only a run envelope. The receipt remains the detailed audit record.

## Interpreting Outcomes

`PASS`

- Exit code: `0`
- Meaning:
  the save-based verifier observed the required post-state
- Expected follow-up:
  confirm the selected action and the receipt fields match your intended scenario

`FAIL`

- Exit code: `1`
- Meaning:
  the run completed, but the required verified state transition did not occur
- Common causes:
  no qualifying save change, wrong tap coordinates, wrong app state, save not refreshed

`AMBIGUOUS`

- Exit code: `2`
- Meaning:
  some activity occurred, but the required save-based post-state was not satisfied cleanly
- Common causes:
  wrong UI target, partial UI interaction, supporting evidence changed without required state change

Runtime or configuration error

- Exit code: `3`
- Meaning:
  the experiment failed before a normal classified control outcome
- Common causes:
  bad CLI parameters, missing file, bad save-source configuration, actuator composition error

## PowerShell Exit Code Check

After the experiment command finishes, run:

```powershell
$LASTEXITCODE
```

Expected meanings:

- `0` = PASS
- `1` = FAIL
- `2` = AMBIGUOUS
- `3` = runtime or configuration error

## Operational Notes

- Do not loop the command.
- Do not add retries manually inside a single run.
- Do not treat actuator command completion as success.
- Save verification remains the only truth source for action success.

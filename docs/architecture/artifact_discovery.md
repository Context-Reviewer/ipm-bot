# Artifact Discovery Workflow

This workflow adds a safe, repeatable, package-focused artifact discovery pipeline for Idle Planet Miner on Windows + BlueStacks.

## Safety stance

- Default path is package-scoped ADB enumeration plus host-side BlueStacks metadata.
- No raw disk mounting.
- No read-write disk access.
- No mutation of app data.
- If package-private access is blocked, the workflow records that limitation explicitly in `manifest.json` and `reports/summary.txt`.
- APK pull is optional and read-only.

## What it collects

The workflow targets `com.TironiumTech.IdlePlanetMiner` and attempts:

- Package-private candidates via `adb shell run-as`
  - `/data/data/com.TironiumTech.IdlePlanetMiner`
  - `/data/user/0/com.TironiumTech.IdlePlanetMiner`
- External/shared storage candidates via ADB shell enumeration
  - `/sdcard/Android/data/com.TironiumTech.IdlePlanetMiner`
  - `/storage/emulated/0/Android/data/com.TironiumTech.IdlePlanetMiner`
- BlueStacks host metadata
  - `C:\ProgramData\BlueStacks_nxt\Engine\Pie64\AppCache\AppCache.json`
  - `C:\ProgramData\BlueStacks_nxt\Logs\Player.log`
  - `C:\ProgramData\BlueStacks_nxt\bluestacks.conf`
- Package metadata command receipts
  - `adb version`
  - `adb devices -l`
  - `adb get-state`
  - `adb shell pm path com.TironiumTech.IdlePlanetMiner`
  - `adb shell dumpsys package com.TironiumTech.IdlePlanetMiner`
- Optional installed APK copy and ZIP member inventory

## Output structure

`census` writes to:

```text
data/artifacts/census/<timestamp>_census_com.TironiumTech.IdlePlanetMiner/
```

`snapshot` writes to:

```text
data/artifacts/snapshots/<timestamp>_snapshot_com.TironiumTech.IdlePlanetMiner/
```

Each run contains:

- `manifest.json`
- `inventory.json`
- `inventory.csv`
- `tree.txt`
- `events.jsonl`
- `reports/summary.txt`
- `receipts/commands/*.json`
- `receipts/commands/*.stdout.txt|.bin`
- `receipts/commands/*.stderr.txt|.bin`
- `context/`
- `extracted/` for raw copied files in snapshot mode when below size limits
- `reports/apk_inventory.json` and `reports/apk_interesting_members.json` when `--pull-apk` succeeds
- separate `apk-report` output when you want a deeper read-only APK inventory/extraction pass

## Inventory fields

The inventory tracks:

- relative path
- source path
- source root
- source kind
- file size
- modified time
- SHA-256 when file size is within hash threshold
- extension
- guessed class
- text-like vs binary
- copy status
- priority and score
- notes and errors

## Diff output

`diff` writes to:

```text
data/artifacts/diffs/<timestamp>_artifact_diff/
```

It produces:

- `changes.json`
- `changes.csv`
- `summary.json`
- `summary.txt`
- `text_diffs/*.diff` for small text-like files with copied payloads in both snapshots

Diff classification covers:

- new files
- deleted files
- modified files
- size changes
- mtime changes
- hash changes
- classification changes

## Exact commands

From `C:\dev\ipm-bot`:

```powershell
.\.venv\Scripts\python.exe -m ipm_bot.artifacts census --adb-path C:\dev\platform-tools\adb.exe --adb-serial emulator-5554
```

```powershell
.\.venv\Scripts\python.exe -m ipm_bot.artifacts snapshot --adb-path C:\dev\platform-tools\adb.exe --adb-serial emulator-5554
```

```powershell
.\.venv\Scripts\python.exe -m ipm_bot.artifacts snapshot --adb-path C:\dev\platform-tools\adb.exe --adb-serial emulator-5554 --pull-apk
```

```powershell
.\scripts\run_artifact_discovery.ps1 -Command census -AdbPath C:\dev\platform-tools\adb.exe -AdbSerial emulator-5554
```

```powershell
.\scripts\run_artifact_discovery.ps1 -Command snapshot -AdbPath C:\dev\platform-tools\adb.exe -AdbSerial emulator-5554 -PullApk
```

```powershell
.\.venv\Scripts\python.exe -m ipm_bot.artifacts diff "C:\dev\ipm-bot\data\artifacts\snapshots\<before>" "C:\dev\ipm-bot\data\artifacts\snapshots\<after>"
```

```powershell
.\scripts\run_artifact_discovery.ps1 -Command diff -BeforeSnapshotDir "C:\dev\ipm-bot\data\artifacts\snapshots\<before>" -AfterSnapshotDir "C:\dev\ipm-bot\data\artifacts\snapshots\<after>"
```

```powershell
.\.venv\Scripts\python.exe -m ipm_bot.artifacts apk-report "C:\dev\ipm-bot\data\artifacts\snapshots\<snapshot_with_base_apk>"
```

```powershell
.\.venv\Scripts\python.exe -m ipm_bot.artifacts apk-report "C:\dev\ipm-bot\data\artifacts\snapshots\<snapshot_with_base_apk>\context\installed_package\base.apk"
```

`apk-report` writes to:

```text
data/artifacts/apk_reports/<timestamp>_apk_report_base/
```

It produces:

- `manifest.json`
- `summary.txt`
- `apk_inventory.json`
- `apk_inventory.csv`
- `interesting_members.json`
- `extracted_members/` for `libil2cpp.so`, `global-metadata.dat`, `Assembly-CSharp.dll`, managed support assemblies, and `AndroidManifest.xml` when present

This is the preferred bridge from a pulled `base.apk` into IL2CPP reconstruction tooling such as Cpp2IL or Il2CppDumper.

## IL2CPP workspace staging

When you already have a snapshot with pulled APK splits, use `il2cpp-workspace` to stage the exact IL2CPP inputs without running any reverse-engineering tool:

```powershell
.\.venv\Scripts\python.exe -m ipm_bot.artifacts il2cpp-workspace --snapshot "C:\dev\ipm-bot\data\artifacts\snapshots\<snapshot_with_apks>"
```

```powershell
.\scripts\run_artifact_discovery.ps1 -Command il2cpp-workspace -SnapshotDir "C:\dev\ipm-bot\data\artifacts\snapshots\<snapshot_with_apks>"
```

It writes to:

```text
data/artifacts/il2cpp_workspaces/<timestamp>_il2cpp_workspace_<snapshot>/
```

Each workspace contains exactly:

- `workspace/global-metadata.dat`
- `workspace/libil2cpp.so`
- `manifest.json`
- `summary.txt`

The command is read-only. It stages:

- `assets/bin/Data/Managed/Metadata/global-metadata.dat` from `context/installed_package/base.apk`
- `lib/arm64-v8a/libil2cpp.so` from `context/installed_package/split_config.arm64_v8a.apk`

If prior `apk-report` extracted members exist for the exact same pulled APK paths, the command reuses those staged files. Otherwise it reads the ZIP members directly from the snapshot APKs. If either required member is missing, the command fails closed with a clear error.

`il2cpp-workspace` is the end of the repo-managed staging boundary. External tooling such as Cpp2IL or Il2CppDumper starts after this point and is intentionally not invoked by the artifact pipeline.

## IL2CPP input report

After handing a staged workspace to external tooling, use `il2cpp-input-report` to document which exact staged inputs were used without scanning outside that workspace and without validating semantic correctness of any external reconstruction output.

```powershell
.\.venv\Scripts\python.exe -m ipm_bot.artifacts il2cpp-input-report --workspace "C:\dev\ipm-bot\data\artifacts\il2cpp_workspaces\<workspace>"
```

```powershell
.\.venv\Scripts\python.exe -m ipm_bot.artifacts il2cpp-input-report --workspace "C:\dev\ipm-bot\data\artifacts\il2cpp_workspaces\<workspace>" --notes "Cpp2IL manual run on analyst workstation"
```

```powershell
.\scripts\run_artifact_discovery.ps1 -Command il2cpp-input-report -WorkspaceDir "C:\dev\ipm-bot\data\artifacts\il2cpp_workspaces\<workspace>" -Notes "Cpp2IL manual run on analyst workstation"
```

It writes to:

```text
data/artifacts/il2cpp_input_reports/<timestamp>_il2cpp_input_report_<workspace>/
```

Each report contains:

- `manifest.json`
- `summary.txt`

The report validates that the specified workspace contains:

- `workspace/global-metadata.dat`
- `workspace/libil2cpp.so`
- `manifest.json`
- `summary.txt`

This command remains read-only. It records hashes, sizes, and normalized references to the staged files. It can also persist optional operator notes about which external tool run consumed the workspace. It does not execute or validate any Cpp2IL or Il2CppDumper output.

## IL2CPP output catalog

After an external IL2CPP tool has produced files outside the repo pipeline, use `il2cpp-output-catalog` to inventory those outputs without interpreting or validating them.

End-to-end boundary chain:

```text
snapshot -> apk-report -> il2cpp-workspace -> il2cpp-input-report -> external tool run -> il2cpp-output-catalog
```

Examples:

```powershell
.\.venv\Scripts\python.exe -m ipm_bot.artifacts il2cpp-output-catalog --output-dir "C:\analysis\cpp2il-output" --input-report "C:\dev\ipm-bot\data\artifacts\il2cpp_input_reports\<input_report>"
```

```powershell
.\.venv\Scripts\python.exe -m ipm_bot.artifacts il2cpp-output-catalog --output-dir "C:\analysis\cpp2il-output" --workspace "C:\dev\ipm-bot\data\artifacts\il2cpp_workspaces\<workspace>" --tool-name "Cpp2IL" --tool-version "2026.3.24" --notes "manual analyst run"
```

```powershell
.\scripts\run_artifact_discovery.ps1 -Command il2cpp-output-catalog -OutputDir "C:\analysis\cpp2il-output" -InputReportDir "C:\dev\ipm-bot\data\artifacts\il2cpp_input_reports\<input_report>" -ToolName "Cpp2IL" -ToolVersion "2026.3.24" -Notes "manual analyst run"
```

It writes to:

```text
data/artifacts/il2cpp_output_catalogs/<timestamp>_il2cpp_output_catalog_<output_dir_name>/
```

Each catalog contains:

- `manifest.json`
- `summary.txt`

The catalog recursively inventories only within the provided `--output-dir` and records:

- relative path
- size
- SHA-256

It links the external output back to either an `il2cpp-input-report` or an `il2cpp-workspace`, propagates the source snapshot path when available, and can persist optional tool metadata and notes. This command is catalog-only and does not perform semantic validation of external reconstruction output.

## IL2CPP name hint report

When an external output tree is too large to inspect manually all at once, use `il2cpp-name-hint-report` to narrow the tree by filename/path metadata only. This command reads only the `il2cpp-output-catalog` manifest and does not open any cataloged files.

Examples:

```powershell
.\.venv\Scripts\python.exe -m ipm_bot.artifacts il2cpp-name-hint-report --catalog "C:\dev\ipm-bot\data\artifacts\il2cpp_output_catalogs\<catalog>" --term player --term reward
```

```powershell
.\.venv\Scripts\python.exe -m ipm_bot.artifacts il2cpp-name-hint-report --catalog "C:\dev\ipm-bot\data\artifacts\il2cpp_output_catalogs\<catalog>" --term Player --case-sensitive --notes "manual narrowing pass"
```

```powershell
.\scripts\run_artifact_discovery.ps1 -Command il2cpp-name-hint-report -CatalogDir "C:\dev\ipm-bot\data\artifacts\il2cpp_output_catalogs\<catalog>" -Term player,reward
```

It writes to:

```text
data/artifacts/il2cpp_name_hint_reports/<timestamp>_il2cpp_name_hint_report_<catalog>/
```

Each report contains:

- `manifest.json`
- `summary.txt`

The report records:

- searched terms
- case sensitivity
- matching catalog entries with `relative_path`, `matched_terms`, `size_bytes`, and `sha256`

This is a metadata-only narrowing aid for manual analyst inspection. It does not parse file contents and does not make semantic claims about external reconstruction output.

## Recommended first validation experiment

Use a low-noise settings change first.

Protocol:

1. Run a baseline snapshot.
2. In Idle Planet Miner, change exactly one setting such as music/sound or another obvious toggle.
3. Wait long enough for the game to persist the change.
   For current IPM behavior, assume autosave is roughly every 44.5 seconds and wait at least 50 seconds unless you have direct evidence of an immediate save.
4. Run a second snapshot.
5. Run `diff`.
6. Inspect `summary.txt`, then sort `changes.csv` by `triage_score`.

Why start here:

- It is deterministic.
- It avoids ad-network noise.
- It should preferentially surface prefs/config/state artifacts.
- It validates whether package-private prefs are reachable at all.

## Recommended follow-up experiments

After the settings toggle succeeds, move to higher-value action diffs:

1. Trigger manual save or obvious autosave.
2. Claim idle income.
3. Upgrade one miner once.
4. Open and close a menu.
5. Claim Ark reward.
6. Watch an ad / activate ad boost.
7. Sell galaxy.

Keep each experiment to one action between snapshots.
Also keep the post-action wait long enough to cross one autosave boundary when the action does not obviously force an immediate save.

## Important limitations

- `run-as` only works if the installed app is debuggable and the emulator permits it.
- Some external `Android/data` paths may be restricted depending on Android image behavior.
- The workflow does not claim package-private success unless enumeration actually succeeds.
- Raw VHDX browsing is intentionally not part of this pipeline.
- The existing offline VHDX save extraction path remains separate and should only be used for already-trusted known members with BlueStacks closed.

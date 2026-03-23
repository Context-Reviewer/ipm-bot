# BlueStacks Artifact Map

This project treats `playerInfo.dat` as the authoritative game-state source. The confirmed
BlueStacks artifacts that matter to that workflow are:

## Primary offline source

- `C:\ProgramData\BlueStacks_nxt\Engine\Pie64\Data.vhdx`
  - Read-only offline source when BlueStacks is closed.
  - Confirmed trusted save members inside the image:
    - `media\0\Android\data\com.TironiumTech.IdlePlanetMiner\files\playerInfo.dat`
    - `media\0\Android\data\com.TironiumTech.IdlePlanetMiner\files\playerInfoBackup.dat`

## Save files

- `playerInfo.dat`
  - Primary trusted save used by the parser and closed-loop control path.
- `playerInfoBackup.dat`
  - Explicit backup save candidate for offline extraction and diagnostics.
  - Not an automatic fallback.

## Supporting emulator metadata

- `C:\ProgramData\BlueStacks_nxt\Engine\Pie64\AppCache\AppCache.json`
  - Confirms app metadata such as package name, activity, version, and portrait orientation.
  - Useful for emulator sanity checks, not as a truth source.

- `C:\ProgramData\BlueStacks_nxt\Logs\Player.log`
  - Emulator telemetry and launch diagnostics.
  - Useful for confirming package/activity launches and BlueStacks-side integration behavior.
  - Not a substitute for save verification.

- `C:\ProgramData\BlueStacks_nxt\bluestacks.conf`
  - Confirms installed BlueStacks instances and instance metadata.
  - Relevant to this project because it identifies the active instance as `Pie64`.

## Scope note

These artifacts are useful for save acquisition and emulator context only. They do not replace:

1. `playerInfo.dat` as the game-state truth source
2. save-driven verification after actuation
3. the existing parser / planner / runner / verifier architecture

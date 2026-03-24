"""Timed validation: pull two saves via ADB, compare smelter/crafter deltas.

Start a smelter in-game, then run this script. It will:
1. Pull playerInfo.dat (T0)
2. Wait 60 seconds
3. Pull playerInfo.dat (T1)
4. Compare smelter/crafter state and print deltas

Usage:
  python scripts/timed_validation.py          # 60 second gap (default)
  python scripts/timed_validation.py 30       # 30 second gap
"""

import os
import subprocess
import sys
import time
from pathlib import Path

from ipm_bot.save.player_data import load_player_data

ADB_SAVE_PATH = "/sdcard/Android/data/com.TironiumTech.IdlePlanetMiner/files/playerInfo.dat"
ADB_EXE = os.environ.get(
    "ADB_EXE",
    r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
)
ADB_SERIAL = os.environ.get(
    "ADB_SERIAL",
    "emulator-5554",
)
OUT_DIR = Path(r"C:\dev\ipm-bot\data\timed_validation")


def adb_pull(dest: Path) -> bool:
    r = subprocess.run(
        [ADB_EXE, "-s", ADB_SERIAL, "pull", ADB_SAVE_PATH, str(dest)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print(f"adb pull failed: {r.stderr.strip()}")
        return False
    return True


def fmt_dt(dt):
    return dt.strftime("%H:%M:%S") if dt else "-"


def duration_estimate(slot) -> float:
    return slot.seconds_completed + slot.timespan_left.total_seconds()


def cycle_state(slot0, slot1) -> str:
    if slot0.recipe_number != slot1.recipe_number:
        return "recipe-changed"
    if slot0.start_date == slot1.start_date:
        return "same"
    return "restarted"


def main():
    wait_secs = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    t0_path = OUT_DIR / "t0_playerInfo.dat"
    t1_path = OUT_DIR / "t1_playerInfo.dat"

    # -- T0 --
    print(f"[T0] Pulling save...")
    if not adb_pull(t0_path):
        return
    print(f"[T0] Saved to {t0_path.name}")

    # -- Wait --
    print(f"Waiting {wait_secs}s (keep smelter running in-game)...")
    for remaining in range(wait_secs, 0, -1):
        print(f"  {remaining:3d}s remaining", end="\r")
        time.sleep(1)
    print(f"  Done.              ")

    # -- T1 --
    print(f"[T1] Pulling save...")
    if not adb_pull(t1_path):
        return
    print(f"[T1] Saved to {t1_path.name}")
    print()

    # -- Parse --
    pd0 = load_player_data(t0_path)
    pd1 = load_player_data(t1_path)

    # -- Smelters --
    print("--- SMELTERS ---")
    any_delta = False
    for i in range(len(pd0.smelters)):
        s0 = pd0.smelters[i]
        s1 = pd1.smelters[i]

        if not s0.on and not s1.on and s0.start_date is None:
            continue

        d_completed = s1.seconds_completed - s0.seconds_completed
        d_left = s1.timespan_left.total_seconds() - s0.timespan_left.total_seconds()
        duration0 = duration_estimate(s0)
        duration1 = duration_estimate(s1)
        cycle = cycle_state(s0, s1)
        on_change = "" if s0.on == s1.on else f" on:{s0.on}->{s1.on}"

        on0 = "ON " if s0.on else "OFF"
        on1 = "ON " if s1.on else "OFF"

        print(f"  slot {i}:")
        print(f"    T0: {on0}  recipe={s0.recipe_number:2d}  start={fmt_dt(s0.start_date)}  "
              f"left={s0.timespan_left.total_seconds():8.2f}s  completed={s0.seconds_completed:10.3f}s")
        print(f"    T1: {on1}  recipe={s1.recipe_number:2d}  start={fmt_dt(s1.start_date)}  "
              f"left={s1.timespan_left.total_seconds():8.2f}s  completed={s1.seconds_completed:10.3f}s")
        print(f"    duration~ T0={duration0:8.3f}s  T1={duration1:8.3f}s  cycle={cycle}")

        markers = []
        if d_completed != 0:
            markers.append(f"completed: {d_completed:+.3f}s")
            any_delta = True
        if d_left != 0:
            markers.append(f"left: {d_left:+.3f}s")
        if on_change:
            markers.append(on_change.strip())

        if markers:
            print(f"    >> {' | '.join(markers)}")
        else:
            print(f"    -- no change --")
        print()

    # -- Crafters --
    print("--- CRAFTERS ---")
    for i in range(len(pd0.crafters)):
        c0 = pd0.crafters[i]
        c1 = pd1.crafters[i]

        if not c0.on and not c1.on and c0.start_date is None:
            continue

        d_completed = c1.seconds_completed - c0.seconds_completed
        d_left = c1.timespan_left.total_seconds() - c0.timespan_left.total_seconds()
        duration0 = duration_estimate(c0)
        duration1 = duration_estimate(c1)
        cycle = cycle_state(c0, c1)

        on0 = "ON " if c0.on else "OFF"
        on1 = "ON " if c1.on else "OFF"

        print(f"  slot {i}:")
        print(f"    T0: {on0}  recipe={c0.recipe_number:2d}  start={fmt_dt(c0.start_date)}  "
              f"left={c0.timespan_left.total_seconds():8.2f}s  completed={c0.seconds_completed:10.3f}s")
        print(f"    T1: {on1}  recipe={c1.recipe_number:2d}  start={fmt_dt(c1.start_date)}  "
              f"left={c1.timespan_left.total_seconds():8.2f}s  completed={c1.seconds_completed:10.3f}s")
        print(f"    duration~ T0={duration0:8.3f}s  T1={duration1:8.3f}s  cycle={cycle}")

        markers = []
        if d_completed != 0:
            markers.append(f"completed: {d_completed:+.3f}s")
            any_delta = True
        if d_left != 0:
            markers.append(f"left: {d_left:+.3f}s")
        if markers:
            print(f"    >> {' | '.join(markers)}")
        else:
            print(f"    -- no change --")
        print()

    # -- Verdict --
    print("=" * 50)
    if any_delta:
        print("PASS: Dynamic field changes detected across snapshots.")
        print("Semantic mapping is validated.")
    else:
        print("WARN: No dynamic changes detected.")
        print("Ensure a smelter/crafter was actively running during the test.")


if __name__ == "__main__":
    main()

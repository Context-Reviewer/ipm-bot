"""Compare smelter/crafter state across two snapshots for timed validation.

Usage:
  python scripts/compare_snapshots.py                    # auto-pick latest two
  python scripts/compare_snapshots.py <snap1> <snap2>    # explicit paths
"""

import sys
from pathlib import Path
from ipm_bot.save.player_data import load_player_data, SmelterSlot, CrafterSlot


def find_save(snap_dir: Path) -> Path:
    """Locate playerInfo.dat within a snapshot directory (any depth)."""
    for p in snap_dir.rglob("playerInfo.dat"):
        return p
    raise FileNotFoundError(f"No playerInfo.dat in {snap_dir}")



def fmt_dt_short(dt):
    if dt is None:
        return "-"
    return dt.strftime("%H:%M:%S")


def print_smelter_row(label, slot: SmelterSlot):
    on = "ON " if slot.on else "OFF"
    left = slot.timespan_left.total_seconds()
    print(f"  {label} slot={slot.index} on={on} recipe={slot.recipe_number:2d} "
          f"start={fmt_dt_short(slot.start_date)} end={fmt_dt_short(slot.end_date)} "
          f"left={left:8.2f}s completed={slot.seconds_completed:10.3f}s")


def print_crafter_row(label, slot: CrafterSlot):
    on = "ON " if slot.on else "OFF"
    left = slot.timespan_left.total_seconds()
    print(f"  {label} slot={slot.index} on={on} recipe={slot.recipe_number:2d} "
          f"start={fmt_dt_short(slot.start_date)} end={fmt_dt_short(slot.end_date)} "
          f"left={left:8.2f}s completed={slot.seconds_completed:10.3f}s")


def main():
    snapshots_dir = Path(r"C:\dev\ipm-bot\data\artifacts\snapshots")

    if len(sys.argv) == 3:
        snap1 = Path(sys.argv[1])
        snap2 = Path(sys.argv[2])
    else:
        snap_dirs = sorted(snapshots_dir.iterdir(), key=lambda p: p.name)
        if len(snap_dirs) < 2:
            print("Need at least 2 snapshots. Take two with ~60s gap.")
            return
        snap1 = snap_dirs[-2]
        snap2 = snap_dirs[-1]

    save1 = find_save(snap1)
    save2 = find_save(snap2)

    print(f"T0: {snap1.name}")
    print(f"T1: {snap2.name}")
    print()

    pd1 = load_player_data(save1)
    pd2 = load_player_data(save2)

    # -- Smelters --
    print("--- SMELTERS ---")
    for i in range(len(pd1.smelters)):
        s1 = pd1.smelters[i]
        s2 = pd2.smelters[i]

        # Skip if both snapshots show no activity
        if (not s1.on and not s2.on
                and s1.start_date is None and s2.start_date is None):
            continue

        print_smelter_row("T0", s1)
        print_smelter_row("T1", s2)

        # Deltas
        d_completed = s2.seconds_completed - s1.seconds_completed
        d_left = s2.timespan_left.total_seconds() - s1.timespan_left.total_seconds()
        on_changed = s1.on != s2.on
        markers = []
        if d_completed != 0:
            markers.append(f"completed delta={d_completed:+.3f}s")
        if d_left != 0:
            markers.append(f"left delta={d_left:+.3f}s")
        if on_changed:
            markers.append(f"on: {s1.on} -> {s2.on}")
        if markers:
            print(f"  ** {' | '.join(markers)}")
        else:
            print(f"  -- no change --")
        print()

    # -- Crafters --
    print("--- CRAFTERS ---")
    for i in range(len(pd1.crafters)):
        c1 = pd1.crafters[i]
        c2 = pd2.crafters[i]

        if (not c1.on and not c2.on
                and c1.start_date is None and c2.start_date is None):
            continue

        print_crafter_row("T0", c1)
        print_crafter_row("T1", c2)

        d_completed = c2.seconds_completed - c1.seconds_completed
        d_left = c2.timespan_left.total_seconds() - c1.timespan_left.total_seconds()
        on_changed = c1.on != c2.on
        markers = []
        if d_completed != 0:
            markers.append(f"completed delta={d_completed:+.3f}s")
        if d_left != 0:
            markers.append(f"left delta={d_left:+.3f}s")
        if on_changed:
            markers.append(f"on: {c1.on} -> {c2.on}")
        if markers:
            print(f"  ** {' | '.join(markers)}")
        else:
            print(f"  -- no change --")
        print()

    # -- Resource diffs --
    res_diffs = []
    for i in range(min(len(pd1.resources), len(pd2.resources))):
        r1 = pd1.resources[i]
        r2 = pd2.resources[i]
        if r1.count != r2.count:
            res_diffs.append((i, r1.count, r2.count, r2.count - r1.count))

    if res_diffs:
        print("--- RESOURCE CHANGES ---")
        for idx, old, new, delta in res_diffs:
            print(f"  [{idx:3d}] {old:>14,.0f} -> {new:>14,.0f}  delta={delta:+,.0f}")
        print()
    else:
        print("--- RESOURCES: no changes ---")
        print()


if __name__ == "__main__":
    main()

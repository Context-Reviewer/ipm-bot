"""Validation script: load playerInfo.dat and print smelter/crafter state."""

from pathlib import Path
from ipm_bot.save.player_data import load_player_data


def fmt_td(td):
    """Format timedelta as human-readable string."""
    total = td.total_seconds()
    if total == 0:
        return "0s"
    hours = int(total // 3600)
    mins = int((total % 3600) // 60)
    secs = total % 60
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    parts.append(f"{secs:.1f}s")
    return " ".join(parts)


def fmt_dt(dt):
    """Format datetime, returning '-' for None."""
    if dt is None:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def main():
    # Find the latest snapshot
    snapshots_dir = Path(r"C:\dev\ipm-bot\data\artifacts\snapshots")
    snap_dirs = sorted(snapshots_dir.iterdir(), key=lambda p: p.name)
    if not snap_dirs:
        print("No snapshots found.")
        return

    latest = snap_dirs[-1]
    save_path = latest / "extracted" / "external_sdcard" / "files" / "playerInfo.dat"
    if not save_path.exists():
        print(f"Save not found at {save_path}")
        return

    print(f"Loading: {save_path.name} from {latest.name}")
    print()

    pd = load_player_data(save_path)

    # -- Smelters --
    print(f"=== SMELTERS ({len(pd.smelters)} slots) ===")
    print()
    active_smelters = [s for s in pd.smelters if s.on or s.recipe_selected]
    if not active_smelters:
        active_smelters = pd.smelters[:4]  # show first 4 if none active

    for s in active_smelters:
        status = "[ON]" if s.on else "[OFF]"
        recipe = f"recipe={s.recipe_number}" if s.recipe_selected else "no recipe"
        alt = " (ALT)" if s.alternate_recipe_selected else ""
        print(f"  Smelter [{s.index}] {status}  {recipe}{alt}")
        if s.on or s.start_date is not None:
            print(f"    start:       {fmt_dt(s.start_date)}")
            print(f"    end:         {fmt_dt(s.end_date)}")
            print(f"    original:    {fmt_dt(s.original_end_date)}")
            print(f"    timeLeft:    {fmt_td(s.timespan_left)}")
            print(f"    completed:   {s.seconds_completed:.2f}s")
        print()

    # Count inactive
    inactive = sum(1 for s in pd.smelters if not s.on and not s.recipe_selected)
    if inactive > 0:
        print(f"  ({inactive} more slots inactive)")
    print()

    # -- Crafters --
    print(f"=== CRAFTERS ({len(pd.crafters)} slots) ===")
    print()
    active_crafters = [c for c in pd.crafters if c.on or c.recipe_selected]
    if not active_crafters:
        active_crafters = pd.crafters[:4]

    for c in active_crafters:
        status = "[ON]" if c.on else "[OFF]"
        recipe = f"recipe={c.recipe_number}" if c.recipe_selected else "no recipe"
        alt = " (ALT)" if c.alternate_recipe_selected else ""
        print(f"  Crafter [{c.index}] {status}  {recipe}{alt}")
        if c.on or c.start_date is not None:
            print(f"    start:       {fmt_dt(c.start_date)}")
            print(f"    end:         {fmt_dt(c.end_date)}")
            print(f"    original:    {fmt_dt(c.original_end_date)}")
            print(f"    timeLeft:    {fmt_td(c.timespan_left)}")
            print(f"    completed:   {c.seconds_completed:.2f}s")
        print()

    inactive = sum(1 for c in pd.crafters if not c.on and not c.recipe_selected)
    if inactive > 0:
        print(f"  ({inactive} more slots inactive)")
    print()

    # -- Resources summary --
    discovered = [r for r in pd.resources if r.discovered and r.count > 0]
    print(f"=== RESOURCES ({len(discovered)} with stock) ===")
    print()
    for r in discovered[:15]:
        print(f"  [{r.index:3d}] count={r.count:>14,.0f}  gathered={r.gathered_total:>14,.0f}  sold={r.sold_total:>14,.0f}")
    if len(discovered) > 15:
        print(f"  ... ({len(discovered) - 15} more)")
    print()

    # -- Planets summary --
    unlocked = [p for p in pd.planets if p.unlocked]
    print(f"=== PLANETS ({len(unlocked)} unlocked / {len(pd.planets)} total) ===")
    print()
    for p in unlocked[:10]:
        print(f"  [{p.index:2d}] mine={p.mining_speed_level:2d}  speed={p.speed_level:2d}  cargo={p.cargo_level:2d}")
    if len(unlocked) > 10:
        print(f"  ... ({len(unlocked) - 10} more)")

    # -- Parse coverage --
    print()
    r = pd.raw
    print(f"Parse: {len(r.sub_records)} records, "
          f"0x{r.parse_end_offset:04X}/0x{r.total_file_size:04X} "
          f"({r.parse_end_offset / r.total_file_size * 100:.1f}%) coverage")
    if r.warnings:
        print(f"Warnings: {len(r.warnings)}")


if __name__ == "__main__":
    main()


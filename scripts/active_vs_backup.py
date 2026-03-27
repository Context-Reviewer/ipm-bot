"""Compare active vs backup save: byte diff + DateTime/double classification near smelter offsets."""

import struct
import sys
from datetime import datetime, timedelta
from pathlib import Path

DOTNET_TICKS_MASK = 0x3FFFFFFFFFFFFFFF
DOTNET_BASE = datetime(1, 1, 1)

# Most recent snapshot with smelter-off baseline (pre-experiment)
SNAP_ROOT = Path(r"C:\dev\ipm-bot\data\artifacts\snapshots")

def find_latest_snapshot():
    dirs = sorted(SNAP_ROOT.iterdir(), reverse=True)
    for d in dirs:
        active = d / "extracted" / "external_sdcard" / "files" / "playerInfo.dat"
        backup = d / "extracted" / "external_sdcard" / "files" / "playerInfoBackup.dat"
        if active.exists() and backup.exists():
            return active, backup, d.name
    return None, None, None

def decode_datetime(raw_i64):
    ticks = raw_i64 & DOTNET_TICKS_MASK
    try:
        return DOTNET_BASE + timedelta(microseconds=ticks / 10)
    except (OverflowError, ValueError):
        return None

def classify_8byte(raw_bytes):
    """Classify 8 bytes as DateTime, double, or unknown."""
    i64 = struct.unpack_from('<q', raw_bytes)[0]
    u64 = struct.unpack_from('<Q', raw_bytes)[0]
    dbl = struct.unpack_from('<d', raw_bytes)[0]
    
    dt = decode_datetime(i64)
    
    results = []
    # DateTime check: ticks in 2010-2040 range
    ticks = u64 & DOTNET_TICKS_MASK
    if 0x08D0_0000_0000_0000 <= ticks <= 0x08F0_0000_0000_0000:
        results.append(("DateTime", dt))
    
    # Double check: reasonable game value
    if raw_bytes != b'\x00' * 8:  # skip all-zero
        if -1e18 < dbl < 1e18 and dbl == dbl:  # not NaN
            results.append(("double", dbl))
    else:
        results.append(("zero", 0))
    
    return results, i64, dbl

def main():
    active_path, backup_path, snap_name = find_latest_snapshot()
    if not active_path:
        print("ERROR: No snapshot found with both active and backup saves")
        sys.exit(1)
    
    print(f"Snapshot: {snap_name}")
    print(f"Active:   {active_path}")
    print(f"Backup:   {backup_path}")
    print()
    
    active = active_path.read_bytes()
    backup = backup_path.read_bytes()
    
    print(f"Active size:  {len(active):,} bytes")
    print(f"Backup size:  {len(backup):,} bytes")
    print(f"Same size:    {len(active) == len(backup)}")
    print(f"Identical:    {active == backup}")
    print()
    
    # ============================================
    # Part 1: Known smelter offsets - DateTime probe
    # ============================================
    print("=" * 80)
    print("PART 1: DateTime probe at user-specified offsets")
    print("=" * 80)
    offsets = [0xC21B, 0xC223, 0xC22B, 0xC233, 0xC275, 0xC27D]
    
    for path, label, data in [(active_path, "ACTIVE", active), (backup_path, "BACKUP", backup)]:
        print(f"\n  [{label}]")
        for off in offsets:
            if off + 8 > len(data):
                print(f"    0x{off:08X}: OUT OF BOUNDS")
                continue
            raw = data[off:off+8]
            i64 = struct.unpack_from('<q', raw)[0]
            dt = decode_datetime(i64)
            dbl = struct.unpack_from('<d', raw)[0]
            print(f"    0x{off:08X}: hex={raw.hex(' ')}  DateTime={dt}  double={dbl:.6f}")
    
    # ============================================
    # Part 2: Full byte diff
    # ============================================
    print()
    print("=" * 80)
    print("PART 2: Byte-level diff (active vs backup)")
    print("=" * 80)
    
    min_len = min(len(active), len(backup))
    diff_offsets = []
    for i in range(min_len):
        if active[i] != backup[i]:
            diff_offsets.append(i)
    
    if len(active) != len(backup):
        print(f"\n  SIZE DIFFERS: active={len(active)}, backup={len(backup)}")
        print(f"  Tail diff: {abs(len(active) - len(backup))} bytes")
    
    print(f"\n  Total differing bytes: {len(diff_offsets)}")
    
    if not diff_offsets:
        print("  Files are IDENTICAL — backup is a mirror copy (Case A)")
        return
    
    # Group into contiguous spans
    spans = []
    start = diff_offsets[0]
    end = diff_offsets[0]
    for off in diff_offsets[1:]:
        if off == end + 1:
            end = off
        else:
            spans.append((start, end))
            start = off
            end = off
    spans.append((start, end))
    
    print(f"  Contiguous changed spans: {len(spans)}")
    print()
    
    for span_start, span_end in spans[:60]:  # limit output
        length = span_end - span_start + 1
        a_bytes = active[span_start:span_end+1]
        b_bytes = backup[span_start:span_end+1]
        print(f"  0x{span_start:08X}-0x{span_end:08X} ({length:3d} bytes)")
        print(f"    active: {a_bytes[:24].hex(' ')}")
        print(f"    backup: {b_bytes[:24].hex(' ')}")
    
    if len(spans) > 60:
        print(f"  ... and {len(spans) - 60} more spans")
    
    # ============================================
    # Part 3: Sliding Int64 diff in smelter region
    # ============================================
    print()
    print("=" * 80)
    print("PART 3: Sliding Int64 delta scan (0xC180 - 0xC700)")
    print("=" * 80)
    print("  Looking for TimeSpan ticks (~10M/sec) and double drift")
    print()
    
    scan_start = 0xC180
    scan_end = min(0xC700, min_len - 8)
    
    hits = []
    for i in range(scan_start, scan_end):
        a_i64 = struct.unpack_from('<q', active, i)[0]
        b_i64 = struct.unpack_from('<q', backup, i)[0]
        if a_i64 != b_i64:
            delta = a_i64 - b_i64
            hits.append((i, delta, a_i64, b_i64))
    
    # Print unique delta patterns (deduplicate overlapping 8-byte windows)
    printed_offsets = set()
    for off, delta, a_val, b_val in hits:
        if off in printed_offsets:
            continue
        printed_offsets.add(off)
        
        # Classify delta
        abs_delta = abs(delta)
        if 1_000_000 < abs_delta < 1_000_000_000_000:
            # Possible TimeSpan ticks (10M ticks/sec, up to ~27 hours)
            seconds = abs_delta / 10_000_000
            tag = f"~{seconds:.1f}s (TimeSpan?)"
        elif abs_delta < 1000:
            tag = "small int delta"
        else:
            tag = ""
        
        # Also try DateTime interpretation
        a_dt = decode_datetime(a_val)
        b_dt = decode_datetime(b_val)
        dt_tag = ""
        if a_dt and b_dt and a_dt.year > 2020 and b_dt.year > 2020:
            dt_diff = a_dt - b_dt
            dt_tag = f"  DT_diff={dt_diff}"
        
        # Also try double
        a_dbl = struct.unpack_from('<d', active, off)[0]
        b_dbl = struct.unpack_from('<d', backup, off)[0]
        dbl_tag = ""
        if a_dbl == a_dbl and b_dbl == b_dbl:  # not NaN
            if abs(a_dbl) < 1e12 and abs(b_dbl) < 1e12:
                dbl_tag = f"  dbl: {b_dbl:.4f} → {a_dbl:.4f}"
        
        print(f"  0x{off:08X}  delta={delta:>20d}  {tag}{dt_tag}{dbl_tag}")

    # ============================================
    # Part 4: Known boolean anchors
    # ============================================
    print()
    print("=" * 80)
    print("PART 4: Known boolean anchors")
    print("=" * 80)
    anchors = {
        0xC1C1: "smelterOn[0]",
        0xC1C2: "smelterOn[1]",
        0xC3DD: "smelterOn[0] companion",
        0xC3DE: "smelterOn[1] companion",
        0xC3F1: "crafterOn[0]",
        0xC60D: "crafterOn[0] companion",
    }
    for off, label in anchors.items():
        if off < len(active) and off < len(backup):
            a_val = active[off]
            b_val = backup[off]
            match = "SAME" if a_val == b_val else "DIFF"
            print(f"  0x{off:08X} {label:30s}  active={a_val:02X}  backup={b_val:02X}  [{match}]")


if __name__ == "__main__":
    main()

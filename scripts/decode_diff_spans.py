"""Decode the diff spans as DateTime to understand what fields they belong to."""
import struct
from datetime import datetime, timedelta
from pathlib import Path

DOTNET_TICKS_MASK = 0x3FFFFFFFFFFFFFFF
DOTNET_BASE = datetime(1, 1, 1)

snap = Path(r"C:\dev\ipm-bot\data\artifacts\snapshots\2026-03-24T02-19-33-788532Z_snapshot_com.TironiumTech.IdlePlanetMiner\extracted\external_sdcard\files")
active = (snap / "playerInfo.dat").read_bytes()
backup = (snap / "playerInfoBackup.dat").read_bytes()

def dt(data, off):
    i64 = struct.unpack_from("<q", data, off)[0]
    ticks = i64 & DOTNET_TICKS_MASK
    try:
        return datetime(1, 1, 1) + timedelta(microseconds=ticks / 10)
    except:
        return None

# The diff bytes at 0x3648 are 3 bytes that differ.
# Context shows: ...09 51 00 00 00 [b0 40 16] 40 2a 89 de 88...
# The "40 2a 89 de 88" after the diff looks like the high bytes of a DateTime
# So 0x3648 thru 0x364F (8 bytes) could be a DateTime
# Let's try alignment at 0x3648 as the START of a DateTime

print("=== Span 1 context: trying every 8-byte alignment ===")
for start in range(0x3640, 0x3658):
    raw = active[start:start+8]
    i64 = struct.unpack_from("<q", raw)[0]
    ticks = i64 & DOTNET_TICKS_MASK
    d = dt(active, start)
    dbl = struct.unpack_from("<d", raw)[0]
    is_plausible_dt = d is not None and 2020 < d.year < 2030
    marker = " <<<" if is_plausible_dt else ""
    print(f"  0x{start:04X}: hex={raw.hex(' ')}  dt={d}  dbl={dbl:.6g}{marker}")

print()
print("=== Span 2 context: trying every 8-byte alignment ===")
for start in range(0x3D4D, 0x3D65):
    raw = active[start:start+8]
    i64 = struct.unpack_from("<q", raw)[0]
    ticks = i64 & DOTNET_TICKS_MASK
    d = dt(active, start)
    dbl = struct.unpack_from("<d", raw)[0]
    is_plausible_dt = d is not None and 2020 < d.year < 2030
    marker = " <<<" if is_plausible_dt else ""
    print(f"  0x{start:04X}: hex={raw.hex(' ')}  dt={d}  dbl={dbl:.6g}{marker}")

# Now the key question: compare the 8-byte value containing the diff between active and backup
print()
print("=== The actual changed DateTimes ===")
for off_label, off in [("Span 1", 0x3648), ("Span 2", 0x3D55)]:
    # The diff bytes are at off, off+1, off+2.
    # Try 8-byte windows that include all 3 diff bytes
    for align in range(off - 5, off + 1):
        a_raw = active[align:align+8]
        b_raw = backup[align:align+8]
        if a_raw != b_raw:
            a_dt = dt(active, align)
            b_dt = dt(backup, align)
            a_plausible = a_dt is not None and 2020 < a_dt.year < 2030
            b_plausible = b_dt is not None and 2020 < b_dt.year < 2030
            if a_plausible and b_plausible:
                diff = a_dt - b_dt
                print(f"  {off_label} @0x{align:04X}: active_dt={a_dt}  backup_dt={b_dt}  delta={diff}")

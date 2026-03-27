"""Investigate the 2 differing spans between active and backup."""
import struct
from pathlib import Path

snap = Path(r"C:\dev\ipm-bot\data\artifacts\snapshots\2026-03-24T02-19-33-788532Z_snapshot_com.TironiumTech.IdlePlanetMiner\extracted\external_sdcard\files")
active = (snap / "playerInfo.dat").read_bytes()
backup = (snap / "playerInfoBackup.dat").read_bytes()

for off, name in [(0x3648, "Span 1"), (0x3D55, "Span 2")]:
    print(f"=== {name} at 0x{off:04X} ===")
    ctx_start = max(0, off - 16)
    ctx_end = min(len(active), off + 16)
    print(f"Active ctx:  {active[ctx_start:ctx_end].hex(' ')}")
    print(f"Backup ctx:  {backup[ctx_start:ctx_end].hex(' ')}")
    for align in [off - 1, off, off + 1]:
        if align >= 0 and align + 4 <= len(active):
            a32 = struct.unpack_from("<i", active, align)[0]
            b32 = struct.unpack_from("<i", backup, align)[0]
            if a32 != b32:
                print(f"  Int32 @0x{align:04X}: active={a32}, backup={b32}, delta={a32 - b32}")
    print()

# Cross-snapshot comparison
print("=== Cross-snapshot comparison ===")
snap_root = Path(r"C:\dev\ipm-bot\data\artifacts\snapshots")
snaps = sorted(snap_root.iterdir())[-5:]
for s in snaps:
    f = s / "extracted" / "external_sdcard" / "files" / "playerInfo.dat"
    if f.exists():
        data = f.read_bytes()
        v1 = struct.unpack_from("<i", data, 0x3647)[0]
        v2 = struct.unpack_from("<i", data, 0x3D54)[0]
        print(f"  {s.name[:25]}  @0x3647={v1:>10d}  @0x3D54={v2:>10d}")

# Also compare active vs backup across multiple snapshots
print()
print("=== Active vs Backup diff byte count across snapshots ===")
for s in sorted(snap_root.iterdir())[-8:]:
    af = s / "extracted" / "external_sdcard" / "files" / "playerInfo.dat"
    bf = s / "extracted" / "external_sdcard" / "files" / "playerInfoBackup.dat"
    if af.exists() and bf.exists():
        a = af.read_bytes()
        b = bf.read_bytes()
        diffs = sum(1 for i in range(min(len(a), len(b))) if a[i] != b[i])
        size_match = "same" if len(a) == len(b) else f"DIFF({len(a)} vs {len(b)})"
        print(f"  {s.name[:25]}  size={size_match}  diff_bytes={diffs}")

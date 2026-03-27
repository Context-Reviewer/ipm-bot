"""Run sub-record parser on the latest snapshot and output the report."""
from pathlib import Path
from ipm_bot.save.sub_records import parse_sub_records, render_sub_record_report

DATA_PATH = Path(r"C:\dev\ipm-bot\data\artifacts\snapshots\2026-03-24T02-19-33-788532Z_snapshot_com.TironiumTech.IdlePlanetMiner\extracted\external_sdcard\files\playerInfo.dat")

result = parse_sub_records(DATA_PATH)
print(render_sub_record_report(result))

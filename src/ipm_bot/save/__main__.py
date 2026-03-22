"""CLI helpers for save summary and diff inspection."""

from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any

from .diff import diff_snapshots, render_snapshot_diff
from .parser import parse_player_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect raw Idle Planet Miner saves through the normalized v1 snapshot layer."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary_parser = subparsers.add_parser(
        "summary", help="Read one save and print its normalized summary."
    )
    summary_parser.add_argument("save_path", type=Path)
    summary_parser.add_argument("--json", action="store_true", dest="as_json")

    diff_parser = subparsers.add_parser(
        "diff", help="Read two saves and print their normalized field diff."
    )
    diff_parser.add_argument("before_path", type=Path)
    diff_parser.add_argument("after_path", type=Path)
    diff_parser.add_argument("--json", action="store_true", dest="as_json")

    args = parser.parse_args()

    if args.command == "summary":
        snapshot = parse_player_snapshot(args.save_path)
        payload = _snapshot_payload(snapshot)
        if args.as_json:
            print(json.dumps(payload, indent=2, default=_json_default))
        else:
            print(_render_summary(payload))
        return 0

    before = parse_player_snapshot(args.before_path)
    after = parse_player_snapshot(args.after_path)
    changes = diff_snapshots(before, after)
    if args.as_json:
        print(
            json.dumps(
                {
                    "before_path": str(args.before_path.resolve()),
                    "after_path": str(args.after_path.resolve()),
                    "changes": [
                        {
                            "field": change.field,
                            "before": change.before,
                            "after": change.after,
                        }
                        for change in changes
                    ],
                },
                indent=2,
                default=_json_default,
            )
        )
    else:
        print(render_snapshot_diff(changes))
    return 0


def _snapshot_payload(snapshot: Any) -> dict[str, Any]:
    payload = {}
    for section_name in ("currencies", "ad", "event", "metadata", "player"):
        section = getattr(snapshot, section_name)
        payload[section_name] = _convert_dataclass(section)
    payload["unresolved_references"] = snapshot.unresolved_references
    return payload


def _convert_dataclass(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value


def _render_summary(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    for section_name in ("metadata", "currencies", "ad", "event", "player"):
        section = payload[section_name]
        for field_name, value in section.items():
            lines.append(f"{field_name}: {_format_value(value)}")

    unresolved_count = len(payload["unresolved_references"])
    lines.append(f"unresolved_reference_count: {unresolved_count}")

    return "\n".join(lines)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, timedelta):
        return str(value)
    return value


def _format_value(value: Any) -> str:
    value = _json_default(value)
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return "null"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())

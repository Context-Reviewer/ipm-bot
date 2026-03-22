"""Persistent storage for one-shot experiment manifests."""

from __future__ import annotations

from dataclasses import dataclass
import json
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_EXPERIMENT_DIRECTORY = Path(__file__).resolve().parents[3] / "logs" / "experiments"


@dataclass(frozen=True, slots=True)
class ExperimentManifest:
    started_at_utc: str
    completed_at_utc: str
    actuator_type: str
    save_source_type: str
    original_requested_save_path: str
    prepared_local_save_path: str
    receipt_path: str
    exit_code: int
    final_status: str
    failure_reason: str
    selected_action: str

    def __post_init__(self) -> None:
        for field_name in (
            "started_at_utc",
            "completed_at_utc",
            "actuator_type",
            "save_source_type",
            "original_requested_save_path",
            "prepared_local_save_path",
            "receipt_path",
            "final_status",
            "failure_reason",
            "selected_action",
        ):
            if not getattr(self, field_name):
                raise ValueError(f"Experiment manifest field '{field_name}' must not be empty.")
        if self.exit_code < 0:
            raise ValueError("Experiment manifest exit_code must be non-negative.")


def write_experiment_manifest(
    manifest: ExperimentManifest,
    output_dir: Path | None = None,
) -> tuple[str, Path]:
    """Persist one experiment manifest and return its experiment id and path."""

    directory = DEFAULT_EXPERIMENT_DIRECTORY if output_dir is None else output_dir
    directory.mkdir(parents=True, exist_ok=True)

    experiment_id, manifest_path = _next_available_path(
        directory=directory,
        timestamp=manifest.started_at_utc,
    )
    manifest_path.write_text(
        json.dumps(
            {
                "experiment_id": experiment_id,
                "started_at_utc": manifest.started_at_utc,
                "completed_at_utc": manifest.completed_at_utc,
                "actuator_type": manifest.actuator_type,
                "save_source_type": manifest.save_source_type,
                "original_requested_save_path": manifest.original_requested_save_path,
                "prepared_local_save_path": manifest.prepared_local_save_path,
                "receipt_path": manifest.receipt_path,
                "exit_code": manifest.exit_code,
                "final_status": manifest.final_status,
                "failure_reason": manifest.failure_reason,
                "selected_action": manifest.selected_action,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return experiment_id, manifest_path


def normalize_utc_timestamp(value: datetime) -> str:
    """Normalize a datetime into a sortable UTC timestamp string."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H-%M-%SZ")


def _next_available_path(directory: Path, timestamp: str) -> tuple[str, Path]:
    experiment_id = timestamp
    candidate = directory / f"{experiment_id}.json"
    suffix = 1
    while candidate.exists():
        experiment_id = f"{timestamp}_{suffix:02d}"
        candidate = directory / f"{experiment_id}.json"
        suffix += 1
    return experiment_id, candidate

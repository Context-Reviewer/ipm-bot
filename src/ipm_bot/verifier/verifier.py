"""Verification helpers for closed-loop save-state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from ipm_bot.save.models import PlayerSnapshot, ScalarValue


VerificationStatus = Literal["PASS", "FAIL", "AMBIGUOUS"]


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: VerificationStatus
    success: bool
    messages: list[str]


def verify_transition(
    before: PlayerSnapshot,
    after: PlayerSnapshot,
    expectations: dict[str, Any],
) -> VerificationResult:
    """Verify that a save transition matches a small set of explicit expectations."""

    must_change = _read_field_list(expectations, "must_change")
    must_not_change = _read_field_list(expectations, "must_not_change")
    expected_values = _read_expected_values(expectations)

    before_fields = before.flat_fields()
    after_fields = after.flat_fields()

    messages: list[str] = []
    failures: list[str] = []

    if not must_change and not must_not_change and not expected_values:
        return VerificationResult(
            status="PASS",
            success=True,
            messages=["No verification expectations defined for this action."],
        )

    for field_name in must_change:
        before_value, after_value = _resolve_field(before_fields, after_fields, field_name)
        if before_value == after_value:
            failures.append(
                f"Field '{field_name}' was expected to change but did not: "
                f"before={before_value!r}, after={after_value!r}."
            )
            continue
        messages.append(
            f"Field '{field_name}' changed as expected: "
            f"before={before_value!r}, after={after_value!r}."
        )

    for field_name in must_not_change:
        before_value, after_value = _resolve_field(before_fields, after_fields, field_name)
        if before_value != after_value:
            failures.append(
                f"Field '{field_name}' was expected to remain unchanged but changed: "
                f"before={before_value!r}, after={after_value!r}."
            )
            continue
        messages.append(
            f"Field '{field_name}' remained unchanged as expected: value={after_value!r}."
        )

    for field_name, expected_value in expected_values.items():
        _validate_known_field(after_fields, field_name)
        actual_value = _require_present_value("after", field_name, after_fields[field_name])
        if actual_value != expected_value:
            failures.append(
                f"Field '{field_name}' did not match the expected value: "
                f"expected={expected_value!r}, actual={actual_value!r}."
            )
            continue
        messages.append(
            f"Field '{field_name}' matched the expected value: value={actual_value!r}."
        )

    return VerificationResult(
        status="FAIL" if failures else "PASS",
        success=not failures,
        messages=failures + messages,
    )


def _read_field_list(expectations: Mapping[str, Any], key: str) -> list[str]:
    raw_value = expectations.get(key, [])
    if not isinstance(raw_value, Sequence) or isinstance(raw_value, str):
        raise TypeError(f"Expectation '{key}' must be a sequence of field names.")

    field_names: list[str] = []
    for field_name in raw_value:
        if not isinstance(field_name, str):
            raise TypeError(f"Expectation '{key}' contains a non-string field name.")
        field_names.append(field_name)
    return field_names


def _read_expected_values(expectations: Mapping[str, Any]) -> Mapping[str, ScalarValue]:
    raw_value = expectations.get("expected_values", {})
    if not isinstance(raw_value, Mapping):
        raise TypeError("Expectation 'expected_values' must be a mapping of field names to values.")

    normalized: dict[str, ScalarValue] = {}
    for field_name, expected_value in raw_value.items():
        if not isinstance(field_name, str):
            raise TypeError("Expectation 'expected_values' contains a non-string field name.")
        normalized[field_name] = expected_value
    return normalized


def _resolve_field(
    before_fields: Mapping[str, ScalarValue],
    after_fields: Mapping[str, ScalarValue],
    field_name: str,
) -> tuple[ScalarValue, ScalarValue]:
    _validate_known_field(before_fields, field_name)
    _validate_known_field(after_fields, field_name)
    before_value = _require_present_value("before", field_name, before_fields[field_name])
    after_value = _require_present_value("after", field_name, after_fields[field_name])
    return before_value, after_value


def _validate_known_field(fields: Mapping[str, ScalarValue], field_name: str) -> None:
    if field_name not in fields:
        raise ValueError(f"Unknown snapshot field in verification expectations: '{field_name}'.")


def _require_present_value(
    snapshot_name: str,
    field_name: str,
    value: ScalarValue,
) -> ScalarValue:
    if value is None:
        raise ValueError(
            f"Cannot verify field '{field_name}': value is missing in the {snapshot_name} snapshot."
        )
    return value

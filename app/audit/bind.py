"""Bind contract `FieldValue`s to the states an audit rule may reason about.

Design D7 — the mapping that keeps the gate usable:

| `FieldValue`                                   | audit state   |
|------------------------------------------------|---------------|
| `status="missing"` or `value is None`          | `absent`      |
| `status="extracted"` with a `source`           | `confirmed`   |
| `status="inferred"`                            | `unconfirmed` |
| `status="extracted"` without a `source`        | `violation`   |

`extracted` counts as confirmed because `agent-contract` promises the value is locatable in its own
file and "MAY 免人工核对"; `inferred` does not, and must reach a human before it can pass a rule.
Treating every `confirmed=false` value as unconfirmed would block the gate before HITL forever.
"""

from __future__ import annotations

from dataclasses import dataclass

ABSENT = "absent"
CONFIRMED = "confirmed"
UNCONFIRMED = "unconfirmed"
VIOLATION = "violation"

VALUE_STATES = (ABSENT, CONFIRMED, UNCONFIRMED, VIOLATION)


@dataclass(frozen=True)
class AuditValue:
    field_id: str
    state: str
    value: str | None = None
    source: dict | None = None
    notes: tuple[str, ...] = ()

    @property
    def is_known(self) -> bool:
        """True when a rule may compare this value at all."""
        return self.state == CONFIRMED and bool(self.value)


def bind_field(field_id: str, field_value: dict | None) -> AuditValue:
    if not field_value:
        return AuditValue(field_id=field_id, state=ABSENT)

    status = field_value.get("status")
    value = field_value.get("value")
    source = field_value.get("source")
    notes = tuple(field_value.get("notes") or ())

    if value is None or status == "missing":
        return AuditValue(field_id=field_id, state=ABSENT, value=None, notes=notes)
    if status == "extracted":
        state = CONFIRMED if source else VIOLATION
        return AuditValue(field_id=field_id, state=state, value=value, source=source, notes=notes)
    if status == "inferred":
        # Design D7: a human confirmation converts an inferred value into a usable one. Without this
        # branch HITL can never clear `needs_input`, and approval loops forever.
        state = CONFIRMED if field_value.get("confirmed") is True else UNCONFIRMED
        return AuditValue(field_id=field_id, state=state, value=value, source=source, notes=notes)

    # Unknown status: never guess that it is fine.
    return AuditValue(field_id=field_id, state=VIOLATION, value=value, source=source, notes=notes)


def bind_fields(fields: dict[str, dict] | None) -> dict[str, AuditValue]:
    return {key: bind_field(key, value) for key, value in (fields or {}).items()}
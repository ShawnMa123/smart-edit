"""Shared contracts used by more than one capability.

The assistant and the document host both need a principal, an access context, a clock, ids and an
audit sink. Keeping those here stops automation from importing the assistant module and lets each
capability swap its adapters independently.
"""

from app.shared.ports import AccessContext, AuditPort, ClockPort, IdsPort, Principal

__all__ = ["AccessContext", "AuditPort", "ClockPort", "IdsPort", "Principal"]
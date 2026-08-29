"""Connector driver contract.

A *driver* is a module that knows how to talk to one external system. Every
driver exposes the same surface so the API, the GUI and the UAPF capability
layer can treat them uniformly:

    KIND            str   — matches connections.kind
    DISPLAY_NAME    str
    IMPLEMENTED     bool  — False for placeholder drivers
    SUMMARY         str   — one line, shown in the GUI
    CONFIG_FIELDS   tuple[Field, ...]  — non-secret, stored in connections.config
    SECRET_FIELDS   tuple[Field, ...]  — stored encrypted, never returned by the API
    OPERATIONS      tuple[Operation, ...] — what the driver can do
    SPEC            tuple[str, ...] — for placeholders: what we still need from
                    the counterparty before this can be implemented

    async test(config, secret) -> Result
    async invoke(operation, config, secret, inputs, ctx) -> Result

FAILURE CONVENTION — important, and deliberately not exceptions. A driver never
raises because the remote system misbehaved. It returns Result(ok=False,
reason=...). A UAPF process step that calls a dead connector must still complete
so the operator can see *what* is missing in the audit trail; a raised exception
would abort the session and lose that. Genuine programming errors still raise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Field:
    """One configuration input, rendered by the GUI and validated by the API."""

    key: str
    label: str
    required: bool = True
    placeholder: str = ""
    help: str = ""
    kind: str = "text"  # text | password | number | bool | select
    choices: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        d = {
            "key": self.key,
            "label": self.label,
            "required": self.required,
            "placeholder": self.placeholder,
            "help": self.help,
            "kind": self.kind,
        }
        if self.choices:
            d["choices"] = list(self.choices)
        return d


@dataclass(frozen=True)
class Operation:
    """One thing a driver can be asked to do.

    `capability` is the UAPF capability that routes here, in namespace/operation
    form. Keeping it on the Operation means the UAPF manifest is derived from
    the drivers rather than maintained separately and drifting.
    """

    name: str
    capability: str
    summary: str
    direction: str = "outbound"  # outbound | inbound

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "capability": self.capability,
            "summary": self.summary,
            "direction": self.direction,
        }


@dataclass
class Result:
    """Uniform driver return value."""

    ok: bool
    reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"ok": self.ok}
        if self.reason:
            d["reason"] = self.reason
        if self.data:
            d.update(self.data)
        return d

    @classmethod
    def fail(cls, reason: str, **data: Any) -> "Result":
        return cls(ok=False, reason=reason, data=data)

    @classmethod
    def good(cls, **data: Any) -> "Result":
        return cls(ok=True, data=data)


def missing_fields(fields: tuple[Field, ...], values: dict[str, Any]) -> list[str]:
    """Return the keys of required fields that are absent or blank."""
    return [
        f.key
        for f in fields
        if f.required and not str(values.get(f.key) or "").strip()
    ]


class PlaceholderDriver:
    """Shared behaviour for connectors that are declared but not implemented.

    A placeholder is not dead weight: it registers the connection kind, renders
    in the GUI as "Not implemented", and — critically — carries SPEC, the list of
    things we need from the counterparty before it can be built. That list is
    the integration questionnaire, kept next to the code it describes so it
    cannot drift away from it.
    """

    IMPLEMENTED = False

    @staticmethod
    def _refuse(kind: str, spec: tuple[str, ...]) -> Result:
        return Result.fail(
            f"{kind} connector is not implemented — awaiting interface specification",
            not_implemented=True,
            required_from_counterparty=list(spec),
        )

"""Connector registry.

Adding a connector means writing one driver module and adding it to _MODULES.
Everything else — the CRUD API, the GUI field rendering, the UAPF capability
manifest and the dispatcher — is derived from what the drivers declare, so
there is no second list to keep in step.
"""

from __future__ import annotations

from types import ModuleType
from typing import Any, Optional

from opendms.connectors import email_box, jira_cloud, medus_dvs, sap
from opendms.connectors.base import Field, Operation, Result

_MODULES: tuple[ModuleType, ...] = (jira_cloud, email_box, sap, medus_dvs)

DRIVERS: dict[str, ModuleType] = {m.KIND: m for m in _MODULES}
KINDS: tuple[str, ...] = tuple(DRIVERS)


def get_driver(kind: str) -> Optional[ModuleType]:
    return DRIVERS.get(kind)


def describe_driver(module: ModuleType) -> dict[str, Any]:
    return {
        "kind": module.KIND,
        "display_name": module.DISPLAY_NAME,
        "implemented": module.IMPLEMENTED,
        "summary": module.SUMMARY,
        "config_fields": [f.as_dict() for f in module.CONFIG_FIELDS],
        "secret_fields": [f.as_dict() for f in module.SECRET_FIELDS],
        "operations": [o.as_dict() for o in module.OPERATIONS],
        "required_from_counterparty": list(module.SPEC),
    }


def describe_all() -> list[dict[str, Any]]:
    """Driver catalogue for the GUI, implemented ones first."""
    return [
        describe_driver(m)
        for m in sorted(_MODULES, key=lambda m: (not m.IMPLEMENTED, m.DISPLAY_NAME))
    ]


def capability_index() -> dict[str, tuple[str, str]]:
    """UAPF capability ref -> (connection kind, driver operation name).

    Keyed as "namespace/operation" to match the engine's host-callback path
    (POST /uapf/host/capability/{namespace}/{operation}).
    """
    index: dict[str, tuple[str, str]] = {}
    for module in _MODULES:
        for op in module.OPERATIONS:
            index[op.capability] = (module.KIND, op.name)
    return index


def advertised_capabilities() -> list[dict[str, Any]]:
    """Capability descriptors for the UAPF host manifest.

    Placeholder drivers are advertised too, on purpose. A process author needs
    to see that connector/sap.lookup-partner is part of the contract and will
    currently answer with a structured refusal — hiding it would make the
    process look complete when the integration behind it is not.
    """
    out: list[dict[str, Any]] = []
    for module in _MODULES:
        for op in module.OPERATIONS:
            namespace, _, operation = op.capability.partition("/")
            out.append({
                "namespace": namespace,
                "operation": operation,
                "version": 1,
                "summary": op.summary,
                "implemented": module.IMPLEMENTED,
            })
    return out


__all__ = [
    "DRIVERS", "KINDS", "Field", "Operation", "Result",
    "advertised_capabilities", "capability_index",
    "describe_all", "describe_driver", "get_driver",
]

"""
UAPF integration bridge.

Embeds OpenDMS as a host in the UAPF Integration Protocol (UAPF-IP) ecosystem:
  - Outbound: calls a UAPF runtime to start algorithmated processes triggered
    by document lifecycle events (DocumentReceived, DocumentCreated, etc.)
  - Inbound: serves the host-side endpoints the runtime calls back into for
    capabilities (document.fetch, ai.redact, ai.extract, data.write, event.emit)

See:
  - UAPF-IP spec: https://github.com/UAPFormat/UAPF-IP
  - Reference runtime: https://github.com/UAPFormat/uapf-engine
  - Tiesibsargs worked example: https://processgit.org/AI_Sandbox/iesnieguma-izskatisana
"""

from .client import UapfClient
from .host_router import router as uapf_host_router
from .bridge import on_document_event

__all__ = ["UapfClient", "uapf_host_router", "on_document_event"]

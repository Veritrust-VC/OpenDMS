"""
Build the HostManifest payload that goes in start-session calls.
"""

from opendms.config import get_settings
from opendms.uapf.handlers import ADVERTISED_CAPABILITIES


def build_host_manifest() -> dict:
    s = get_settings()
    return {
        "hostDid": s.opendms_host_did,
        "hostBaseUrl": s.opendms_host_base_url,
        "profiles": ["uapf-ip-orchestrated"],
        "capabilities": ADVERTISED_CAPABILITIES,
    }

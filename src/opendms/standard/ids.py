"""
Identifiers of the Dokumentu metadatu standarts v2.0.

    {PREFIX}:{ORG}:{YEAR}:{UUIDv7}

    PREFIX  LV-DOK | LV-LIETA | LV-DATNE | LV-NOT
    ORG     authoritative organisation code:
              VPK ID       NN-NNNN      state administration institution
              ATVK code    NNNNNNN      municipality
              UR reg. no.  NNNNNNNNNNN  any other legal person
    YEAR    creation year in Europe/Riga
    UUIDv7  RFC 9562, lowercase, time component = creation instant

An identifier is assigned once, by the organisation that creates the object,
and never changes or is reused.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

RIGA = ZoneInfo("Europe/Riga")

PREFIX_DOCUMENT = "LV-DOK"
PREFIX_CASE = "LV-LIETA"
PREFIX_FILE = "LV-DATNE"
PREFIX_EVENT = "LV-NOT"
PREFIXES = (PREFIX_DOCUMENT, PREFIX_CASE, PREFIX_FILE, PREFIX_EVENT)

ORG_CODE_RE = re.compile(r"^[0-9]{2}(-[0-9]{4}|[0-9]{5}|[0-9]{9})$")
UUID7_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
ID_RE = re.compile(
    r"^(LV-DOK|LV-LIETA|LV-DATNE|LV-NOT):"
    r"([0-9]{2}(?:-[0-9]{4}|[0-9]{5}|[0-9]{9})):([0-9]{4}):(" + UUID7_RE + r")$"
)
ORG_DID_RE = re.compile(r"^did:web:[a-z0-9-]+\.pac\.kis\.gov\.lv$")


def org_code_kind(code: str) -> str:
    """Return 'vpk', 'atvk' or 'ur' for a valid organisation code."""
    if not code or not ORG_CODE_RE.match(code):
        raise ValueError(f"Not a valid organisation code: {code!r}")
    if "-" in code:
        return "vpk"
    return "atvk" if len(code) == 7 else "ur"


def uuid7(at: datetime | None = None) -> str:
    """RFC 9562 UUIDv7 whose timestamp is `at` (default: now)."""
    at = at or datetime.now(timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    ms = int(at.timestamp() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")
    value = (
        (ms & ((1 << 48) - 1)) << 80
        | 0x7 << 76
        | ((rand >> 64) & 0xFFF) << 64
        | 0b10 << 62
        | (rand & ((1 << 62) - 1))
    )
    return str(uuid.UUID(int=value))


def make_id(prefix: str, org_code: str, at: datetime | None = None) -> str:
    """Build a new identifier for an object created at `at` by `org_code`."""
    if prefix not in PREFIXES:
        raise ValueError(f"Unknown identifier prefix: {prefix!r}")
    org_code_kind(org_code)
    at = at or datetime.now(timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    year = at.astimezone(RIGA).year
    return f"{prefix}:{org_code}:{year}:{uuid7(at)}"


def parse_id(value: str) -> dict:
    """Split an identifier into its parts; raises ValueError if malformed."""
    m = ID_RE.match(value or "")
    if not m:
        raise ValueError(f"Not a valid identifier: {value!r}")
    prefix, org, year, u = m.groups()
    ms = int(u.replace("-", "")[:12], 16)
    created = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return {
        "prefix": prefix,
        "org": org,
        "orgKind": org_code_kind(org),
        "year": int(year),
        "uuid": u,
        "createdAt": created,
        "yearMatches": created.astimezone(RIGA).year == int(year),
    }


def document_did(org_did: str | None, document_id: str) -> str | None:
    """did:web form of a document identifier, hosted by the creating organisation."""
    if not org_did or not ORG_DID_RE.match(org_did):
        return None
    parts = parse_id(document_id)
    return f"{org_did}:doc:{parts['org']}:{parts['year']}:{parts['uuid']}"


def package_folder(document_id: str) -> str:
    """Package folder name: the main document identifier with ':' replaced by '_'."""
    parse_id(document_id)
    return document_id.replace(":", "_")

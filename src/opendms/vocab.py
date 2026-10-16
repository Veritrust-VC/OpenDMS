"""Lietvedības vārdnīcas from ProcessGit — status names and the registration number format.

The organisation keeps them in its own ProcessGit repository (setting
OPENDMS_LIETVEDIBA_VARDNICAS = "processgit:<org>/<repo>"):

  statusi.json   {"versija": "...", "statusi": {"registered": "Reģistrēts", ...}}
  numurs.json    {"versija": "...", "formats": "{gads}/{kartas}", "kartasGarums": 4,
                  "skaititajs": "gads"}          # restart the sequence every year ("gads") or never ("visi")

Tokens in the format: {gads} {kartas} {iestade} (organisation code) {registrs} (register code).
Without the setting, or when ProcessGit cannot be read, the DVS keeps working with
built-in Latvian names and the old number format (<org id>-00001).
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_STATUS = {"draft": "Projekts", "registered": "Reģistrēts", "received": "Saņemts",
                  "assigned": "Nodots izpildei", "decided": "Izlemts", "sent": "Nosūtīts", "archived": "Arhivēts"}
_cache: dict = {"at": 0.0, "data": None}
TTL = 300


def _ref() -> str:
    from opendms.config import get_settings
    r = (getattr(get_settings(), "lietvediba_vardnicas", "") or "").strip()
    return r[len("processgit:"):] if r.startswith("processgit:") else r


async def load(force: bool = False) -> dict:
    """{statusi, numurs, avots, kluda?} — cached for five minutes."""
    if not force and _cache["data"] and time.time() - _cache["at"] < TTL:
        return _cache["data"]
    ref = _ref()
    out = {"statusi": dict(DEFAULT_STATUS), "numurs": None, "avots": None}
    if ref:
        from opendms.uapf.learning import fetch_file
        owner, repo = ref.split("/", 1)
        try:
            st = json.loads(await fetch_file(f"{owner}/{repo}/statusi.json"))
            out["statusi"].update({k: v for k, v in (st.get("statusi") or {}).items() if isinstance(v, str)})
            out["statusiVersija"] = st.get("versija")
            out["avots"] = f"processgit:{owner}/{repo}"
        except Exception as e:
            out["kluda"] = f"statusi.json: {e}"[:300]
        try:
            nr = json.loads(await fetch_file(f"{owner}/{repo}/numurs.json"))
            if isinstance(nr.get("formats"), str) and "{kartas}" in nr["formats"]:
                out["numurs"] = nr
                out["avots"] = f"processgit:{owner}/{repo}"
        except Exception as e:
            out["kluda"] = (out.get("kluda", "") + f" numurs.json: {e}")[:300]
    _cache.update(at=time.time(), data=out)
    return out


def format_number(fmt: str, seq: int, *, length: int = 5, year: int, org_code: str = "", register_code: str = "") -> str:
    vals = {"gads": str(year), "kartas": str(seq).zfill(max(1, int(length))), "iestade": org_code or "",
            "registrs": register_code or ""}
    out = re.sub(r"\{(\w+)\}", lambda m: vals.get(m.group(1), m.group(0)), fmt)
    return re.sub(r"([/\-.])\1+", r"\1", out).strip("/-. ")   # an empty token leaves no double separator


async def next_number(conn, org_id: int, register_id: Optional[int] = None) -> str:
    """The next registration number. With a ProcessGit format: an atomic counter per
    organisation (and year, if the format restarts yearly). Otherwise the old form."""
    voc = await load()
    nr = voc.get("numurs")
    if not nr:
        count = await conn.fetchval("SELECT COUNT(*) FROM documents WHERE org_id = $1", org_id)
        return f"{org_id}-{count + 1:05d}"
    year = datetime.now(timezone.utc).year
    scope = str(year) if (nr.get("skaititajs") or "gads") == "gads" else "visi"
    await conn.execute("""CREATE TABLE IF NOT EXISTS registration_counters (
                              org_id BIGINT NOT NULL, scope TEXT NOT NULL, value BIGINT NOT NULL,
                              PRIMARY KEY (org_id, scope))""")
    start = 1
    if scope != "visi":
        # first number of the year continues after documents already registered this year
        start = 1 + await conn.fetchval(
            "SELECT COUNT(*) FROM documents WHERE org_id = $1 AND date_part('year', created_at) = $2", org_id, year)
    seq = await conn.fetchval(
        """INSERT INTO registration_counters (org_id, scope, value) VALUES ($1, $2, $3)
           ON CONFLICT (org_id, scope) DO UPDATE SET value = registration_counters.value + 1
           RETURNING value""", org_id, scope, start)
    org_code = await conn.fetchval("SELECT COALESCE(std_code, code) FROM organizations WHERE id = $1", org_id) or ""
    reg_code = (await conn.fetchval("SELECT code FROM registers WHERE id = $1", register_id) if register_id else "") or ""
    return format_number(nr["formats"], seq, length=nr.get("kartasGarums", 5), year=year,
                         org_code=org_code, register_code=reg_code)

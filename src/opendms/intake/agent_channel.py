"""Jauns dokuments — a document entered by a person in the Lietvedības aģents.

Two steps, as in the concept (Aģents → "Jauns dokuments"):

  propose()  the file or text → AI proposal of the registration metadata
             (temats, sūtītājs, dokumenta datums, veids, kopsavilkums). Nothing is stored.
  submit()   the person's confirmed values + the file → a DVS document through the
             same intake path as every other channel (ingest), so the installed
             processes start exactly as for e-mail or the web form.

The text goes to the language model only after personal-data redaction, as in
the processes; the sender's name is therefore filled in by the person.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

CHANNEL = {"id": "agents", "veids": "agents", "nosaukums": "Lietvedības aģents",
           # no acknowledgement e-mail: the person entering the document decides about replies
           "apstiprinajums": {"ieslegts": False}}
MAX_BYTES = 15 * 1024 * 1024
DOC_TYPES = ["iesniegums", "sūdzība", "vēstule", "informācija", "pieprasījums", "lēmums", "cits"]

PROPOSE_PROMPT = """Tu palīdzi {org} lietvedim reģistrēt saņemtu dokumentu. No dokumenta teksta piedāvā
reģistrācijas metadatus. Personas dati tekstā ir aizklāti — neizdomā vārdus.
Atbildi TIKAI ar JSON:
{{"temats": "īss dokumenta temats latviski (līdz 120 zīmēm)",
  "sutitajaOrganizacija": "sūtītāja iestāde vai uzņēmums, ja tāds minēts, citādi tukšs",
  "dokumentaDatums": "GGGG-MM-DD, ja dokumentā norādīts, citādi tukšs",
  "dokumentaVeids": "viens no: {types}",
  "kopsavilkums": "1–2 teikumi: ko sūtītājs lūdz vai paziņo",
  "prasaAtbildi": true/false}}"""


def _decode(file_b64: Optional[str]) -> bytes:
    if not file_b64:
        return b""
    try:
        data = base64.b64decode(file_b64, validate=False)
    except Exception:
        raise ValueError("Datne nav nolasāma (base64)")
    if len(data) > MAX_BYTES:
        raise ValueError(f"Datne pārsniedz {MAX_BYTES // (1024 * 1024)} MB")
    return data


def text_of(file_name: Optional[str], mime_type: Optional[str], data: bytes, text: Optional[str]) -> str:
    from opendms.routers.documents import _extract_text
    parts = []
    if data:
        parts.append(_extract_text(data, mime_type or "application/octet-stream", file_name or "") or "")
    if text:
        parts.append(text)
    return "\n\n".join(p for p in parts if p).strip()


async def propose(*, file_name: Optional[str] = None, mime_type: Optional[str] = None,
                  file_b64: Optional[str] = None, text: Optional[str] = None) -> dict:
    from opendms.ai import _complete_json
    from opendms.org_context import org_label
    from opendms.uapf.handlers import handle_ai_redact
    data = _decode(file_b64)
    content = text_of(file_name, mime_type, data, text)
    if not content:
        return {"teksts": False, "priekslikums": {}, "piezime": "No datnes neizdevās nolasīt tekstu — aizpildiet laukus paši."}
    red = (await handle_ai_redact({"input": {"content": content[:15000]}}))["output"]
    redacted = red.get("redactedContent") or content[:15000]
    org = await org_label()
    out = await _complete_json(PROPOSE_PROMPT.format(org=org, types=", ".join(DOC_TYPES)),
                               f"--- DOKUMENTA TEKSTS ---\n{redacted[:12000]}\n--- BEIGAS ---", max_tokens=600)
    p = {k: (out or {}).get(k) for k in ("temats", "sutitajaOrganizacija", "dokumentaDatums", "dokumentaVeids",
                                         "kopsavilkums", "prasaAtbildi")}
    if p.get("dokumentaVeids") not in DOC_TYPES:
        p["dokumentaVeids"] = None
    return {"teksts": True, "garums": len(content), "priekslikums": p,
            "piezime": None if out else "Valodas modelis neatbildēja — aizpildiet laukus paši."}


async def submit(*, fields: dict, person: str, file_name: Optional[str] = None, mime_type: Optional[str] = None,
                 file_b64: Optional[str] = None, text: Optional[str] = None) -> dict:
    from opendms.intake.service import ingest
    temats = str(fields.get("temats") or "").strip()
    if not temats:
        raise ValueError("Norādiet dokumenta tematu")
    data = _decode(file_b64)
    if not data and not (text or "").strip():
        raise ValueError("Pievienojiet datni vai ielīmējiet tekstu")
    sender = {"name": (fields.get("sutitajs") or fields.get("sutitajaOrganizacija") or "").strip() or None,
              "email": (fields.get("sutitajaEpasts") or "").strip() or None,
              "organization": (fields.get("sutitajaOrganizacija") or "").strip() or None}
    atts = [{"file_name": file_name or "dokuments", "mime_type": mime_type or "application/octet-stream",
             "data": data}] if data else []
    extra = {"ievadija": person, "ievadesVeids": "Lietvedības aģents",
             **{k: fields.get(k) for k in ("dokumentaDatums", "dokumentaVeids", "kopsavilkums")
                if fields.get(k) not in (None, "")}}
    r = await ingest(CHANNEL, external_ref=f"agents-{uuid.uuid4().hex[:16]}", sender=sender, subject=temats,
                     body=(text or "").strip(), attachments=atts, extra=extra)
    if fields.get("kopsavilkums"):
        from opendms.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE documents SET content_summary = COALESCE(content_summary, $1) WHERE id = $2",
                               str(fields["kopsavilkums"])[:2000], r["documentId"])
    logger.info("agent intake by %s -> document %s", person, r.get("documentId"))
    return {"documentId": r["documentId"], "registrationNumber": r.get("registrationNumber"), "datnes": r.get("datnes")}

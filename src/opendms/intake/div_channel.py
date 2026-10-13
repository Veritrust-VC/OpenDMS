"""E-adreses (DIV) ievades kanāls — saņem citu iestāžu sūtījumus.

    GetMessageHeaders -> GetMessage -> aploksne + pielikumi
      -> pielikumu kontrolsummas pret aploksni
      -> centrālajā reģistrā DocumentReceived uz TO PAŠU reģistra dokumentu
         (dokuments saglabā identitāti; mainās turētājs)
      -> intake.ingest() -> DVS dokuments -> procesi
      -> ConfirmMessage (sūtītājs saņem paziņojumu Confirmed)

ievade.yaml:
    - id: e-adrese
      veids: e-adrese
      ieslegts: true
      intervals_s: 30
"""

from __future__ import annotations

import base64
import hashlib
import logging

from opendms import div
from opendms.intake import service

logger = logging.getLogger(__name__)


def _structured_submitter(files: list[dict]):
    from lxml import etree
    NS = "urn:lv:tiesibsargs:iesniegums:1.0"
    for f in files:
        if not (f.get("mime_type") or "").endswith("xml") or f["file_name"] == "metadati.xml":
            continue
        try:
            root = etree.fromstring(f["data"], parser=etree.XMLParser(resolve_entities=False, no_network=True))
        except Exception:
            continue
        if root.tag != f"{{{NS}}}Iesniegums":
            continue
        t = lambda p: root.findtext(p, namespaces={"i": NS})  # noqa: E731
        typ = t("i:Iesniedzejs/i:PusesTips")
        name = t("i:Iesniedzejs/i:Nosaukums") if typ == "JuridiskaPersona" else " ".join(
            x for x in (t("i:Iesniedzejs/i:Vards"), t("i:Iesniedzejs/i:Uzvards")) if x)
        return {k: v for k, v in {"name": name, "type": typ, "email": t("i:Iesniedzejs/i:Kontakti/i:Epasts")}.items() if v}
    return None


async def _keep_file_ids(doc_id, env_files: list[dict]) -> None:
    """Files keep their LV-DATNE identifiers from the sender (ContentReference)."""
    if not doc_id:
        return
    from opendms.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        for f in env_files:
            cid = f.get("content_id") or ""
            if cid.startswith("LV-DATNE:"):
                await conn.execute(
                    """UPDATE document_files SET std_id = $1 WHERE document_id = $2 AND file_name = $3 AND std_id IS NULL
                       AND NOT EXISTS (SELECT 1 FROM document_files WHERE std_id = $1)""", cid, doc_id, f["name"])


async def poll_once(ch: dict) -> dict:
    out = {"registreti": [], "kludas": []}
    for h in await div.headers():
        mid = h["MessageId"]
        try:
            msg = await div.get(mid)
            env = div.parse_envelope(msg["Envelope"])
            blobs = {a["ContentId"]: base64.b64decode(a["Contents"]) for a in msg.get("Attachments", [])}
            files = []
            for f in env["files"]:
                data = blobs.get(f["content_id"])
                if data is None or base64.b64encode(hashlib.sha256(data).digest()).decode() != f["sha256_b64"]:
                    raise ValueError(f"pielikums {f['name']} neatbilst aploksnei")
                files.append({"file_name": f["name"], "mime_type": f["mime_type"], "data": data})
            ident = env["identity"]
            sender_name = h.get("SenderName") or env["sender"]

            # Register: same document, new holder.
            vc = False
            reg_did = ident.get("RegistraDID")
            if reg_did:
                from opendms import sdk_client
                from opendms.config import get_settings
                if get_settings().sdk_enabled:
                    res = await sdk_client.receive_document(reg_did, sender_did=ident.get("SutitajaDID") or "",
                                                            local_reg=env.get("serverRef") or "")
                    vc = bool(res)

            # A structured iesniegums carries the original submitter: the receiving
            # institution answers that person, not the forwarding institution.
            sender = {"name": sender_name, "type": "Iestade", "eAddress": env["sender"]}
            submitter = _structured_submitter(files)
            if submitter:
                sender = submitter

            # metadati.xml of the sender stays as evidence of origin, not as the document
            main = [f for f in files if f["file_name"] != "metadati.xml"]
            origin = [f for f in files if f["file_name"] == "metadati.xml"]
            r = await service.ingest(
                ch, external_ref=f"div:{mid}",
                sender=sender, doc_uid=ident.get("DokumentaID"),
                subject=env["title"] or "", body=env.get("description") or "",
                attachments=main[1:] + [{**o, "file_name": "sutitaja-metadati.xml"} for o in origin],
                primary={**main[0], "avots": f"e-adrese {env['sender']}"} if main else None,
                register_did=reg_did, received_vc=vc,
                extra={"div": {"messageId": mid, "sutitajs": env["sender"], "sutitajaNosaukums": sender_name,
                               "serverRefNumber": env.get("serverRef"), "sutitajaAtsauce": env.get("senderRef"),
                               "sutijumaVeids": env.get("kind"), "izcelsme": ident}})
            await _keep_file_ids(r.get("documentId"), env["files"])
            await div.confirm(mid)
            out["registreti"].append(r.get("documentId"))
        except Exception as exc:
            logger.exception("e-adrese: message %s failed", mid)
            out["kludas"].append(f"{mid}: {type(exc).__name__}: {exc}")
    return out

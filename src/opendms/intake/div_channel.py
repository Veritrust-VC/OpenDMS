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

            # metadati.xml of the sender stays as evidence of origin, not as the document
            main = [f for f in files if f["file_name"] != "metadati.xml"]
            origin = [f for f in files if f["file_name"] == "metadati.xml"]
            r = await service.ingest(
                ch, external_ref=f"div:{mid}",
                sender={"name": sender_name, "type": "Iestade", "eAddress": env["sender"]},
                subject=env["title"] or "", body=env.get("description") or "",
                attachments=main[1:] + [{**o, "file_name": "sutitaja-metadati.xml"} for o in origin],
                primary={**main[0], "avots": f"e-adrese {env['sender']}"} if main else None,
                register_did=reg_did, received_vc=vc,
                extra={"div": {"messageId": mid, "sutitajs": env["sender"], "sutitajaNosaukums": sender_name,
                               "serverRefNumber": env.get("serverRef"), "sutitajaAtsauce": env.get("senderRef"),
                               "sutijumaVeids": env.get("kind"), "izcelsme": ident}})
            await div.confirm(mid)
            out["registreti"].append(r.get("documentId"))
        except Exception as exc:
            logger.exception("e-adrese: message %s failed", mid)
            out["kludas"].append(f"{mid}: {type(exc).__name__}: {exc}")
    return out

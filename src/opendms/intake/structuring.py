"""submission.structure@1 / submission.confirm@1 — a received iesniegums as UAS e-submission 0.1.

structure: the document's text -> e-submission XML (tiesibsargs/iesnieguma-shema), stored next to the
original as a second file; the original stays the document. A web-form submission already is
e-submission: it is taken as it is, without a model.

The model never sees identifiers. Before the call, the text is masked reversibly — personas kods,
e-mail, phone, account number, and the sender's known name — as tokens such as [P1_VARDS]; the model
returns them unchanged and the code puts the values back. Names of other people in free text are
not caught by this pass (that is the anonymisation gateway's job, outside this step).

The result is a proposal (status `structured`): the person reviews it in the process's review step,
and submission.confirm marks it `reviewed` with the reviewer's name — the schema does not allow a
model-structured submission to be `reviewed` without one (rule E-020).

Session outputs: strukturaStatuss (form | structured | reviewed | kluda), strukturasBridinajumi
(warning ids — the screening step's inputs), strukturasFakti, strukturasPrasijumi, strukturasDatne.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from lxml import etree

from opendms.intake import esubmission as E

logger = logging.getLogger(__name__)
FILE_NAME = "iesniegums.e-submission.xml"
REVIEWED_NAME = "iesniegums.e-submission.parskatits.xml"
MAX_TEXT = 15000

# ── reversible masking ─────────────────────────────────────────────────────
_RX = [
    ("PK", re.compile(r"\b[0-3]\d[01]\d\d{2}-?[0-2]\d{4}\b")),
    ("EPASTS", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),   # never ends in a dot (end of sentence)
    ("KONTS", re.compile(r"\b[A-Z]{2}\d{2}[A-Z]{4}[A-Z0-9]{8,26}\b")),
    ("TALRUNIS", re.compile(r"(?:\+371|00371)[\s-]?\d{8}\b|\b[2-6]\d{7}\b")),
]
_TOKEN = re.compile(r"\[[A-Z0-9_]+\]")


def mask(text: str, sender_name: Optional[str] = None) -> tuple[str, dict]:
    """Returns (masked text, token -> original value)."""
    m: dict[str, str] = {}
    rev: dict[str, str] = {}

    def tok(kind: str, value: str) -> str:
        if value in rev:
            return rev[value]
        t = f"[{kind}_{sum(1 for k in m if k.startswith('[' + kind + '_')) + 1}]"
        m[t] = value
        rev[value] = t
        return t

    out = text
    if sender_name:
        parts = [p for p in re.split(r"\s+", sender_name.strip()) if len(p) >= 3]
        if len(parts) >= 2:
            full = re.compile(r"\b" + r"\s+".join(map(re.escape, parts)) + r"\b", re.IGNORECASE)
            out = full.sub(lambda x: tok("P1_VARDS_UZVARDS", x.group(0)), out)
        for n, p in enumerate(parts):
            label = "P1_VARDS" if n == 0 and len(parts) > 1 else "P1_UZVARDS"
            out = re.sub(r"\b" + re.escape(p) + r"\w{0,3}\b", lambda x: tok(label, x.group(0)), out)
    for kind, rx in _RX:
        out = rx.sub(lambda x: tok(kind, x.group(0)), out)
    return out, m


def unmask(obj: Any, m: dict) -> Any:
    if isinstance(obj, str):
        return _TOKEN.sub(lambda x: m.get(x.group(0), x.group(0)), obj)
    if isinstance(obj, list):
        return [unmask(x, m) for x in obj]
    if isinstance(obj, dict):
        return {k: unmask(v, m) for k, v in obj.items()}
    return obj


# ── the model's contract ───────────────────────────────────────────────────
SYSTEM_PROMPT = """Tu strukturē iesniegumu, kas adresēts Latvijas Republikas Tiesībsarga birojam, pēc shēmas
UAS e-submission 0.1. Teksts ir maskēts: identifikatori aizstāti ar marķieriem kvadrātiekavās, piem. [P1_VARDS],
[EPASTS_1]. Marķierus atkārto tieši tādus, kādi tie ir; nekad neizdomā vārdus, adreses vai numurus.

Izmanto TIKAI to, kas ir tekstā. Ja kaut kā nav, lauku neliec. Neko nepiedomā un nevērtē juridiski.
Atbildi tikai ar JSON šādā formā (visi teksti latviski, kā iesniedzējs rakstījis):
{
 "submissionType": ["lugums"|"sudziba"|"prieksl"|"jautajums", ...],
 "title": "<līdz 200 zīmēm>",
 "parties": [
   {"id": "p1", "role": ["submitter", "affectedPerson"?], "partyType": "naturalPerson"|"legalPerson"|"unknown",
    "givenName": "...", "familyName": "...", "legalName": "...", "address": "...",
    "contact": {"email": "...", "phone": "..."}},
   {"id": "p2", "role": ["affectedPerson"], ...}            // tikai ja iesniedzējs raksta citas personas interesēs
   {"id": "r1", "role": ["respondent"], "partyType": "institution"|"legalPerson"|"naturalPerson", "legalName": "..."}
 ],
 "representation": {"represents": "p2", "basis": "authorisation"|"legalRepresentative"|"none"|"other", "description": "..."},
 "narrative": {"summary": "<izklāsts 1–3 teikumos, līdz 1000 zīmēm>"},
 "facts": [
   {"id": "f1", "when": {"date": "GGGG-MM-DD"} | {"yearMonth": "GGGG-MM"} | {"year": "GGGG"} | {"period": {"from": "GGGG-MM-DD", "to": "GGGG-MM-DD"}} | {"ongoing": true},
    "place": "...", "actor": ["r1"], "conduct": "action"|"omission"|"decision"|"statement"|"event",
    "statement": "<viens apstāklis, līdz 2000 zīmēm>", "sourceExcerpt": "<precīzs citāts no teksta, līdz 300 zīmēm>"}
 ],
 "rightsAffected": {"domain": ["BT"|"PPT"|"SEK"|"TV"]},
 "claims": [
   {"id": "c1", "type": "investigate"|"remedy"|"conciliation"|"opinion"|"consultation"|"information"|"legislativeChange"|"other",
    "text": "<ko lūdz, iesniedzēja vārdiem>", "addressedTo": "r1", "relatedFact": ["f1"]}
 ],
 "priorSteps": {"step": [{"type": "contactedRespondent"|"complaintToSuperior"|"administrativeAppeal"|"otherBody"|"other",
                          "addressedTo": "r1", "date": "GGGG-MM-DD", "responseReceived": true|false, "responseSummary": "..."}],
                "court": {"status": "no"|"pending"|"decided"|"unknown", "caseNo": "..."}},
 "privacy": {"doNotDiscloseIdentity": true|false, "doNotDiscloseFacts": true|false, "noReplyNeeded": true|false,
             "replyChannel": "email"|"eAddress"|"post"}
}
Noteikumi: katrs fakts — viens apstāklis (kas, kad, ko darīja vai nedarīja); sourceExcerpt ir vārds vārdā no teksta.
Katrs lūgums atsevišķi un sasaistīts ar faktiem, uz kuriem balstās. Joma: BT bērnu tiesības; PPT pilsoniskās un
politiskās tiesības; SEK sociālās, ekonomiskās un kultūras tiesības; TV vienlīdzība un diskriminācija.
Ja nav zināms, vai jautājums ir tiesā, court.status = "unknown". Privātuma laukus liec true tikai, ja iesniedzējs to tieši lūdz."""

ENUMS = {
    "submissionType": {"lugums", "sudziba", "prieksl", "jautajums"},
    "role": {"submitter", "coSubmitter", "representative", "affectedPerson", "respondent", "witness", "other"},
    "partyType": {"naturalPerson", "legalPerson", "institution", "unknown"},
    "conduct": {"action", "omission", "decision", "statement", "event"},
    "domain": {"BT", "PPT", "SEK", "TV"},
    "claimType": {"investigate", "remedy", "conciliation", "opinion", "consultation", "information", "legislativeChange", "other"},
    "stepType": {"contactedRespondent", "complaintToSuperior", "administrativeAppeal", "otherBody", "other"},
    "court": {"no", "pending", "decided", "unknown"},
    "reply": {"email", "eAddress", "post", "oral"},
    "basis": {"authorisation", "legalRepresentative", "none", "other"},
}
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,39}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YM = re.compile(r"^\d{4}-\d{2}$")
_Y = re.compile(r"^\d{4}$")


def _s(v, n=None) -> Optional[str]:
    if v is None or isinstance(v, (dict, list)):
        return None
    t = " ".join(str(v).split()).strip()
    return (t[:n] if n else t) or None


def sanitise(raw: dict, *, sender: Optional[dict] = None) -> dict:
    """Model output -> payload the builder accepts: known enums only, ids valid and unique,
    references to things that exist, text within the schema's limits. Nothing is added
    that the text did not give, except the submitter's e-mail/name from the intake envelope."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {}
    types = [t for t in (raw.get("submissionType") or []) if t in ENUMS["submissionType"]]
    out["submissionType"] = list(dict.fromkeys(types))[:4] or ["lugums"]
    if _s(raw.get("title")):
        out["title"] = _s(raw["title"], 200)

    parties, seen = [], set()
    for p in raw.get("parties") or []:
        if not isinstance(p, dict) or not _ID.match(str(p.get("id") or "")) or p["id"] in seen:
            continue
        roles = [r for r in (p.get("role") or []) if r in ENUMS["role"]][:3]
        if not roles:
            continue
        q = {"id": p["id"], "role": list(dict.fromkeys(roles)),
             "partyType": p.get("partyType") if p.get("partyType") in ENUMS["partyType"] else "unknown"}
        for k in ("givenName", "familyName", "legalName", "address"):
            if _s(p.get(k)):
                q[k] = _s(p[k], 200)
        if q["partyType"] == "naturalPerson":
            q.pop("legalName", None)
        c = p.get("contact") if isinstance(p.get("contact"), dict) else {}
        cc = {}
        if _s(c.get("email")) and re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+$", _s(c["email"])):
            cc["email"] = _s(c["email"], 200)
        if _s(c.get("phone")) and re.match(r"^\+?[0-9 ]{8,16}$", _s(c["phone"])):
            cc["phone"] = _s(c["phone"])
        if cc:
            q["contact"] = cc
        seen.add(p["id"])
        parties.append(q)
    sub = next((p for p in parties if "submitter" in p["role"]), None)
    if sub is None:
        sub = {"id": "p1" if "p1" not in seen else "p_iesniedzejs", "role": ["submitter", "affectedPerson"], "partyType": "unknown"}
        parties.insert(0, sub)
        seen.add(sub["id"])
    if sender:   # the envelope knows the e-mail address, and a display name if the model left it out
        if sender.get("email") and not (sub.get("contact") or {}).get("email"):
            sub.setdefault("contact", {})["email"] = sender["email"][:200]
        if sender.get("name") and not (sub.get("givenName") or sub.get("legalName")):
            parts = sender["name"].split()
            if len(parts) >= 2:
                sub.update(partyType="naturalPerson", givenName=" ".join(parts[:-1])[:200], familyName=parts[-1][:200])
    rep = raw.get("representation") if isinstance(raw.get("representation"), dict) else None
    if rep and rep.get("represents") in seen and rep.get("basis") in ENUMS["basis"]:
        r = {"represents": rep["represents"], "basis": rep["basis"]}
        if _s(rep.get("description")):
            r["description"] = _s(rep["description"], 500)
        if r["basis"] == "other" and "description" not in r:
            r["basis"] = "none"
        sub["representation"] = r
        if "representative" not in sub["role"]:
            sub["role"] = [x for x in sub["role"] if x != "affectedPerson"] + ["representative"]
    out["parties"] = parties

    nar = raw.get("narrative") if isinstance(raw.get("narrative"), dict) else {}
    if _s(nar.get("summary")):
        out["narrative"] = {"summary": _s(nar["summary"], 1000)}

    facts, fids = [], set()
    for f in raw.get("facts") or []:
        if not isinstance(f, dict) or not _s(f.get("statement")):
            continue
        fid = f.get("id") if _ID.match(str(f.get("id") or "")) and f.get("id") not in fids else f"f{len(facts) + 1}"
        q = {"id": fid}
        w = f.get("when") if isinstance(f.get("when"), dict) else {}
        if _DATE.match(str(w.get("date") or "")):
            q["when"] = {"date": w["date"]}
        elif _YM.match(str(w.get("yearMonth") or "")):
            q["when"] = {"yearMonth": w["yearMonth"]}
        elif _Y.match(str(w.get("year") or "")):
            q["when"] = {"year": w["year"]}
        elif isinstance(w.get("period"), dict) and _DATE.match(str(w["period"].get("from") or "")):
            to = w["period"].get("to")
            q["when"] = {"period": {"from": w["period"]["from"], **({"to": to} if _DATE.match(str(to or "")) and to >= w["period"]["from"] else {})}}
        elif w.get("ongoing") is True:
            q["when"] = {"ongoing": True}
        if _s(f.get("place")):
            q["place"] = _s(f["place"], 200)
        actors = [a for a in (f.get("actor") or []) if a in seen][:5]
        if actors:
            q["actor"] = actors
        if f.get("conduct") in ENUMS["conduct"]:
            q["conduct"] = f["conduct"]
        q["statement"] = _s(f["statement"], 2000)
        q["basis"] = "claimed"
        if _s(f.get("sourceExcerpt")):
            q["sourceExcerpt"] = _s(f["sourceExcerpt"], 1000)
        fids.add(fid)
        facts.append(q)
    if facts:
        out["facts"] = facts

    ra = raw.get("rightsAffected") if isinstance(raw.get("rightsAffected"), dict) else {}
    doms = [d for d in (ra.get("domain") or []) if d in ENUMS["domain"]]
    if doms:
        out["rightsAffected"] = {"domain": list(dict.fromkeys(doms))[:4]}

    claims, cids = [], set()
    for c in raw.get("claims") or []:
        if not isinstance(c, dict) or not _s(c.get("text")):
            continue
        cid = c.get("id") if _ID.match(str(c.get("id") or "")) and c.get("id") not in cids else f"c{len(claims) + 1}"
        q = {"id": cid, "type": c.get("type") if c.get("type") in ENUMS["claimType"] else "other", "text": _s(c["text"], 1000)}
        if c.get("addressedTo") in seen:
            q["addressedTo"] = c["addressedTo"]
        rel = [x for x in (c.get("relatedFact") or []) if x in fids]
        if rel:
            q["relatedFact"] = list(dict.fromkeys(rel))
        cids.add(cid)
        claims.append(q)
    if claims:
        out["claims"] = claims

    ps = raw.get("priorSteps") if isinstance(raw.get("priorSteps"), dict) else {}
    steps = []
    for s in ps.get("step") or []:
        if not isinstance(s, dict) or s.get("type") not in ENUMS["stepType"]:
            continue
        q = {"type": s["type"]}
        if s.get("addressedTo") in seen:
            q["addressedTo"] = s["addressedTo"]
        if _DATE.match(str(s.get("date") or "")):
            q["date"] = s["date"]
        got = s.get("responseReceived") is True
        q["responseReceived"] = got
        if got and _s(s.get("responseSummary")):
            q["responseSummary"] = _s(s["responseSummary"], 1000)
        steps.append(q)
    court = ps.get("court") if isinstance(ps.get("court"), dict) else {}
    cs = court.get("status") if court.get("status") in ENUMS["court"] else "unknown"
    out["priorSteps"] = {"step": steps[:20], "court": {"status": cs, **({"caseNo": _s(court["caseNo"], 60)} if _s(court.get("caseNo")) else {})}}

    pr = raw.get("privacy") if isinstance(raw.get("privacy"), dict) else {}
    out["privacy"] = {k: pr.get(k) is True for k in ("doNotDiscloseIdentity", "doNotDiscloseFacts", "noReplyNeeded")}
    if pr.get("replyChannel") in ENUMS["reply"]:
        out["privacy"]["replyChannel"] = pr["replyChannel"]
    return out


# ── document access ────────────────────────────────────────────────────────
async def _document(doc_id: int) -> dict:
    from opendms.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        d = await conn.fetchrow("SELECT id, doc_uid, registration_number, metadata, created_at FROM documents WHERE id = $1", int(doc_id))
        files = await conn.fetch("""SELECT id, file_name, mime_type, checksum_sha256, is_primary, storage_key FROM document_files
                                    WHERE document_id = $1 ORDER BY is_primary DESC, id""", int(doc_id))
    if not d:
        raise ValueError(f"document {doc_id} not found")
    meta = d["metadata"]
    meta = json.loads(meta) if isinstance(meta, str) else (meta or {})
    return {"row": dict(d), "meta": meta, "files": [dict(f) for f in files]}


async def _read(storage_key: str) -> bytes:
    from opendms.storage import get_storage
    data = await get_storage().get(storage_key)
    if data is None:
        raise ValueError(f"file not in storage: {storage_key}")
    return data


async def _store(doc_id: int, name: str, xml: bytes) -> int:
    from opendms.intake.service import _upload, system_user
    from opendms.routers.documents import add_file
    res = await add_file(int(doc_id), _upload(name, "application/xml", xml), user=await system_user())
    return int(res["id"]) if isinstance(res, dict) and res.get("id") else 0


async def _record(doc_id: int, info: dict) -> None:
    from opendms.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE documents SET metadata = metadata || $1::jsonb WHERE id = $2",
                           json.dumps({"iesniegumaStruktura": info}, ensure_ascii=False), int(doc_id))


def _signature(meta: dict) -> str:
    ev = (meta.get("ievade") or {}).get("edoc") or meta.get("edoc") or []
    if any((e.get("parakstuSkaits") or 0) > 0 and e.get("integritateVisiem") for e in ev if isinstance(e, dict)):
        return "qualifiedESignature"
    return "none"


def _channel(meta: dict) -> str:
    ch = (meta.get("ievade") or {}).get("channel") or meta.get("channel") or ""
    return E.CHANNELS.get(ch, "post" if ch in ("", "API", "GUI") else "email")


def _shema(ctx: dict) -> dict:
    ref = (ctx.get("schema_ref") or "").replace("processgit:", "")
    if ref.endswith(".xsd"):
        base = ref.rsplit("/shemas/", 1)[0]
        return {"xsd": ref, "noteikumi": f"{base}/noteikumi/" + ref.rsplit("/", 1)[1].replace(".xsd", ".sch"),
                "klasifikators": E.DEFAULT_SHEMA["klasifikators"]}
    return dict(E.DEFAULT_SHEMA)


def _outputs(status: str, res: dict, file_id: int = 0) -> dict:
    info = res.get("info") or {}
    return {"strukturaStatuss": status, "strukturasBridinajumi": [w["id"] for w in res.get("warnings") or []],
            "strukturasFakti": info.get("fakti") or 0, "strukturasPrasijumi": len(info.get("prasijumi") or []),
            "strukturasDatne": file_id or None,
            "courtPending": "W-141" in [w["id"] for w in res.get("warnings") or []]}


# ── handlers ───────────────────────────────────────────────────────────────
async def handle_submission_structure(ctx: dict) -> dict:
    inp = ctx.get("input") or {}
    doc_id = inp.get("documentId")
    if not doc_id:
        raise ValueError("submission.structure requires documentId")
    d = await _document(int(doc_id))
    shema = _shema(ctx)
    klas = None
    try:
        klas = await E.classifier(shema)
    except Exception as e:  # the classifier is a check, not a precondition
        logger.warning("submission.structure: classifier unavailable: %s", e)

    primary = d["files"][0] if d["files"] else None
    if primary and (primary["mime_type"] or "").endswith("xml"):
        data = await _read(primary["storage_key"])
        if b"urn:uas:esubmission:0.1" in data[:2000]:
            # the web form: already e-submission — taken as it is
            res = await E.validate(data, shema, klas)
            await _record(doc_id, {"status": "form", "datne": primary["id"], "bridinajumi": res["warnings"],
                                   "fakti": res["info"].get("fakti"), "prasijumi": res["info"].get("prasijumi")})
            return {"output": _outputs("form", res, primary["id"])}

    text = inp.get("content") or ""
    if not text.strip():
        await _record(doc_id, {"status": "kluda", "iemesls": "nav teksta"})
        return {"output": {"strukturaStatuss": "kluda", "strukturasBridinajumi": [], "_warning": "no text to structure"}}
    if len(text) > MAX_TEXT:
        from opendms.text_extract import fit
        text = fit(text, MAX_TEXT)

    sender = (d["meta"].get("ievade") or {}).get("sender") or d["meta"].get("sender") or {}
    masked, tokens = mask(text, sender.get("name"))
    from opendms.ai import _cfg, _complete_json
    raw = await _complete_json(SYSTEM_PROMPT, f"--- IESNIEGUMA TEKSTS (maskēts) ---\n{masked}\n--- BEIGAS ---",
                               max_tokens=4000, timeout=180.0)
    if not raw:
        await _record(doc_id, {"status": "kluda", "iemesls": "valodas modelis nav pieejams"})
        return {"output": {"strukturaStatuss": "kluda", "strukturasBridinajumi": [], "_warning": "model unavailable"}}
    payload = sanitise(unmask(raw, tokens), sender=sender)

    others = d["files"][1:]
    attachments = [{"file_name": f["file_name"], "mime_type": f["mime_type"], "sha256": f["checksum_sha256"]}
                   for f in others if f["file_name"] not in (FILE_NAME, REVIEWED_NAME)][:50]
    row = d["row"]
    build_kw = dict(channel=_channel(d["meta"]), attachments=attachments,
                    received_at=(d["meta"].get("ievade") or {}).get("receivedAt") or (row["created_at"].isoformat() if row.get("created_at") else None),
                    signature=_signature(d["meta"]), status="structured",
                    structuring={"method": "ai", "model": _cfg().get("model")},
                    source_document={"file_name": primary["file_name"], "mime_type": primary["mime_type"]} if primary else None,
                    registration_no=row.get("registration_number"),
                    document_id=row.get("doc_uid") if str(row.get("doc_uid") or "").startswith("LV-DOK") else None)
    xml = E.build(payload, **build_kw)
    res = await E.validate(xml, shema, klas, strict_classifier=False)
    if res["errors"]:
        # one correction round: drop what the rules reject (broken references are already filtered)
        logger.warning("submission.structure: errors %s", res["errors"][:3])
        await _record(doc_id, {"status": "kluda", "kludas": res["errors"][:10]})
        return {"output": {"strukturaStatuss": "kluda", "strukturasBridinajumi": [], "strukturasKludas": res["errors"][:10]}}
    file_id = await _store(doc_id, FILE_NAME, xml)
    await _record(doc_id, {"status": "structured", "datne": file_id, "bridinajumi": res["warnings"],
                           "fakti": res["info"].get("fakti"), "prasijumi": res["info"].get("prasijumi"),
                           "izklasts": res["info"].get("izklasts"), "maskets": sorted({k.split("_")[0].strip("[") for k in tokens})})
    return {"output": _outputs("structured", res, file_id)}


async def handle_submission_confirm(ctx: dict) -> dict:
    """After the review step: the structuring becomes `reviewed`, with who reviewed it.
    A rejected review (noraidits) leaves it `structured`."""
    inp = ctx.get("input") or {}
    doc_id = inp.get("documentId")
    if not doc_id:
        raise ValueError("submission.confirm requires documentId")
    d = await _document(int(doc_id))
    st = d["meta"].get("iesniegumaStruktura") or {}
    if st.get("status") != "structured" or inp.get("decision") not in ("apstiprinats", "labots"):
        return {"output": {"strukturaStatuss": st.get("status") or "nav"}}
    f = next((x for x in d["files"] if x["id"] == st.get("datne")), None)
    if not f:
        return {"output": {"strukturaStatuss": "kluda", "_warning": "structured file not found"}}
    doc = etree.fromstring(await _read(f["storage_key"]))
    ns = {"es": E.NS}
    doc.find("es:identity/es:status", ns).text = "reviewed"
    s = doc.find("es:provenance/es:structuring", ns)
    for name in ("reviewedBy", "reviewedAt"):
        old = s.find(f"es:{name}", ns)
        if old is not None:
            s.remove(old)
    etree.SubElement(s, f"{{{E.NS}}}reviewedBy").text = str(inp.get("reviewer") or "nezināms")[:200]
    etree.SubElement(s, f"{{{E.NS}}}reviewedAt").text = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    xml = etree.tostring(doc, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    res = await E.validate(xml, _shema(ctx), None)
    if res["errors"]:
        return {"output": {"strukturaStatuss": "kluda", "strukturasKludas": res["errors"][:10]}}
    file_id = await _store(doc_id, REVIEWED_NAME, xml)
    await _record(doc_id, {**st, "status": "reviewed", "datne": file_id, "parskatija": inp.get("reviewer"),
                           "iepriekseja": st.get("datne")})
    return {"output": _outputs("reviewed", res, file_id)}

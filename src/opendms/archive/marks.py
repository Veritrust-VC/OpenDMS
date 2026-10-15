"""Vīzas, iepazīšanās atzīmes, rezolūcijas — standarts 08, 8.2.; EAD3 odd/table t1–t3.

Katra ir nemaināms dokumenta notikums (document_events) ar personu un laiku. Labojums ir jauns ieraksts
ar atsauci uz iepriekšējo (`aizstaj`), nevis izmaiņa.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Optional

from lxml import etree

from opendms.archive.scheme import ARK, SchemeError
from opendms.database import get_pool

EV_VISA, EV_ACK, EV_RES = "Vizets", "IepazinasAtzime", "Rezolucija"
KINDS = {EV_VISA: "vizas", EV_ACK: "iepazisanas", EV_RES: "rezolucijas"}
VISA_RESULTS = {"Saskanots": "Saskaņots", "SaskanotsArIebildumiem": "Saskaņots ar iebildumiem", "Nesaskanots": "Nesaskaņots"}


class MarkError(SchemeError):
    pass


async def _person(conn, user_id: int, position: Optional[str] = None) -> dict:
    u = await conn.fetchrow("SELECT id, full_name, email, department, position FROM users WHERE id = $1 AND is_active", user_id)
    if not u:
        raise MarkError(f"Lietotājs {user_id} nav atrasts vai nav aktīvs")
    return {"lietotajaId": u["email"], "vardsUzvards": u["full_name"], "amats": position or u["position"],
            "strukturvieniba": u["department"], "id": u["id"]}


async def _add(doc_id: int, event: str, actor_id: int, details: dict) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if not await conn.fetchval("SELECT 1 FROM documents WHERE id = $1", doc_id):
            raise MarkError("Dokuments nav atrasts")
        if details.get("aizstaj") and not await conn.fetchval(
                "SELECT 1 FROM document_events WHERE id = $1 AND document_id = $2 AND event_type = $3",
                details["aizstaj"], doc_id, event):
            raise MarkError("Aizstājamais ieraksts nav šī dokumenta tāda paša veida ieraksts")
        details = {**details, "persona": details.get("persona") or await _person(conn, actor_id, details.pop("amats", None))}
        details.pop("amats", None)
        row = await conn.fetchrow(
            """INSERT INTO document_events (document_id, event_type, actor_id, details) VALUES ($1, $2, $3, $4)
               RETURNING id, created_at""", doc_id, event, actor_id, json.dumps(details, ensure_ascii=False, default=str))
    return {"id": row["id"], "veids": event, "datums": row["created_at"], **details}


async def add_visa(doc_id: int, actor_id: int, result: str, notes: Optional[str], position: Optional[str] = None,
                   replaces: Optional[int] = None) -> dict:
    if result not in VISA_RESULTS:
        raise MarkError(f"Vīzas rezultāts: {', '.join(VISA_RESULTS)}")
    if result != "Saskanots" and not (notes or "").strip():
        raise MarkError("Iebildumus vai nesaskaņošanas iemeslu ieraksta piezīmēs")
    return await _add(doc_id, EV_VISA, actor_id, {"rezultats": result, "piezimes": notes, "amats": position, "aizstaj": replaces})


async def add_acknowledgement(doc_id: int, actor_id: int, notes: Optional[str], position: Optional[str] = None) -> dict:
    return await _add(doc_id, EV_ACK, actor_id, {"piezimes": notes, "amats": position})


async def add_resolution(doc_id: int, actor_id: int, tasks: list[dict], notes: Optional[str],
                         position: Optional[str] = None, replaces: Optional[int] = None) -> dict:
    """tasks: [{atbildigie: [user_id…], apraksts, termins: YYYY-MM-DD?}]"""
    if not tasks:
        raise MarkError("Rezolūcijā jābūt vismaz vienam uzdevumam")
    pool = await get_pool()
    out = []
    async with pool.acquire() as conn:
        for t in tasks:
            if not (t.get("apraksts") or "").strip():
                raise MarkError("Uzdevumam jābūt aprakstam")
            if not t.get("atbildigie"):
                raise MarkError("Uzdevumam jābūt atbildīgajam")
            term = t.get("termins")
            if term:
                date.fromisoformat(str(term))
            out.append({"atbildigie": [await _person(conn, int(u)) for u in t["atbildigie"]],
                        "apraksts": t["apraksts"].strip(), "termins": str(term) if term else None})
    return await _add(doc_id, EV_RES, actor_id, {"uzdevumi": out, "piezimes": notes, "amats": position, "aizstaj": replaces})


async def list_marks(doc_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, event_type, details, created_at FROM document_events WHERE document_id = $1 AND event_type = ANY($2::text[]) ORDER BY id",
            doc_id, list(KINDS))
    items = []
    for r in rows:
        d = r["details"]
        d = json.loads(d) if isinstance(d, str) else (d or {})
        items.append({"id": r["id"], "veids": r["event_type"], "datums": r["created_at"], **d})
    replaced = {i["aizstaj"] for i in items if i.get("aizstaj")}
    out = {v: [] for v in KINDS.values()}
    for i in items:
        i["aizstats"] = i["id"] in replaced
        out[KINDS[i["veids"]]].append(i)
    return out


# ── ark:DokumentaArhivaMetadati daļa (t1–t3); pilno elementu 4e solī papildina pakotnes veidotājs ──

def _persona(parent, tag: str, p: dict):
    A = lambda t: f"{{{ARK}}}{t}"
    el = etree.SubElement(parent, A(tag))
    if p.get("lietotajaId"):
        etree.SubElement(el, A("LietotajaID")).text = str(p["lietotajaId"])
    etree.SubElement(el, A("VardsUzvards")).text = p.get("vardsUzvards") or "—"
    if p.get("amats"):
        etree.SubElement(el, A("Amats")).text = p["amats"]
    if p.get("strukturvieniba"):
        etree.SubElement(el, A("Strukturvieniba")).text = p["strukturvieniba"]
    return el


def _dt(v) -> str:
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).isoformat()
    return str(v)


def append_marks(root, marks: dict) -> None:
    """Pievieno Vizas, IepazisanasAtzimes, Rezolucijas elementam ark:DokumentaArhivaMetadati (secība pēc XSD).
    Aizstātie ieraksti netiek iekļauti; to vēsture paliek notikumos."""
    A = lambda t: f"{{{ARK}}}{t}"
    live = {k: [i for i in v if not i.get("aizstats")] for k, v in marks.items()}
    if live["vizas"]:
        g = etree.SubElement(root, A("Vizas"))
        for v in live["vizas"]:
            x = etree.SubElement(g, A("Viza"))
            _persona(x, "Persona", v["persona"])
            etree.SubElement(x, A("Datums")).text = _dt(v["datums"])
            note = VISA_RESULTS.get(v.get("rezultats"), v.get("rezultats") or "")
            etree.SubElement(x, A("Piezimes")).text = note + (f": {v['piezimes']}" if v.get("piezimes") else "")
    if live["iepazisanas"]:
        g = etree.SubElement(root, A("IepazisanasAtzimes"))
        for v in live["iepazisanas"]:
            x = etree.SubElement(g, A("Atzime"))
            _persona(x, "Persona", v["persona"])
            etree.SubElement(x, A("Datums")).text = _dt(v["datums"])
            if v.get("piezimes"):
                etree.SubElement(x, A("Piezimes")).text = v["piezimes"]
    if live["rezolucijas"]:
        g = etree.SubElement(root, A("Rezolucijas"))
        for v in live["rezolucijas"]:
            x = etree.SubElement(g, A("Rezolucija"))
            _persona(x, "Autors", v["persona"])
            etree.SubElement(x, A("Datums")).text = _dt(v["datums"])
            for t in v["uzdevumi"]:
                u = etree.SubElement(x, A("Uzdevums"))
                for p in t["atbildigie"]:
                    _persona(u, "Atbildigais", p)
                etree.SubElement(u, A("Apraksts")).text = t["apraksts"]
                if t.get("termins"):
                    etree.SubElement(u, A("IzpildesTermins")).text = t["termins"]
            if v.get("piezimes"):
                etree.SubElement(x, A("Piezimes")).text = v["piezimes"]

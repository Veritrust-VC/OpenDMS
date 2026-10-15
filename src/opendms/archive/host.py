"""DVS spējas arhivēšanas procesiem (resources/mappings.yaml → host.dvs). Izsauc UAPF dzinējs.

P2: case.resolve, case.attach, files.check, archive.assign-id   (document.fetch ir jau esošā spēja)
P3: case.fetch, case.check-completeness, files.normalize, case.close, case.carry-over
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from opendms.archive import cases as cs
from opendms.archive import registration as rg
from opendms.archive import scheme as sch
from opendms.archive.engine import as_bool
from opendms.database import get_pool
from opendms.org_context import get_default_org_required

WHO = "uapf:lv.kisc.dokumentu-arhivesana"


def _inp(ctx) -> dict:
    return ctx.get("input") or {}


def _int(v, name) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} nav norādīts vai nav skaitlis")


async def _org() -> dict:
    return dict(await get_default_org_required())


# ── P2 ──

async def case_resolve(ctx):
    doc_id = _int(_inp(ctx).get("documentId"), "documentId")
    org = await _org()
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc, case, _e, _f = await rg._load(conn, doc_id)
        if case and case["status"] == "Atverta" and case.get("scheme_entry_id"):
            return {"output": {"atrasts": True, "lietasId": case["id"], "kandidati": []}}
        s = await rg.suggest_cases(conn, org["id"], doc)
    return {"output": {"atrasts": s["ieteikta"] is not None, "lietasId": s["ieteikta"],
                       "kandidati": [{"id": c["id"], "indekss": c["case_index"], "nosaukums": c["case_name"]} for c in s["iespejas"]]}}


async def case_attach(ctx):
    i = _inp(ctx)
    doc_id = _int(i.get("documentId"), "documentId")
    org = await _org()
    if i.get("lietasId"):
        await cs.attach_document(org, _int(i["lietasId"], "lietasId"), doc_id, WHO, None)
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc, case, entry, files = await rg._load(conn, doc_id)
    v, _checked = rg.inputs(doc, case, entry, files)
    return {"output": {k: v[k] for k in ("irLieta", "lietaAtverta", "irTermins", "irStatuss", "statuss", "irPamatojums", "irDatums", "irVeids")}}


async def files_check(ctx):
    from opendms.archive.engine import decide
    doc_id = _int(_inp(ctx).get("documentId"), "documentId")
    pool = await get_pool()
    async with pool.acquire() as conn:
        _doc, _case, _e, files = await rg._load(conn, doc_id)
    out = []
    for f in files:
        name = f.get("file_name") or ""
        local = rg.file_action(f.get("mime_type"), name, name.lower().endswith((".edoc", ".asice", ".asics")))
        d = await decide("datnu-formati", {"mimeVeids": local["mime"] or "", "irParakstits": name.lower().endswith((".edoc", ".asice", ".asics"))})
        o = d["outputs"] if d else {"derigsGlabasanai": local["derigs"], "darbiba": local["riciba"], "piezime": local["piezime"]}
        out.append({"datne": name, **o})
    return {"output": {"datnuFormatiDerigi": all(as_bool(x.get("derigsGlabasanai")) for x in out), "datnes": out}}


async def archive_assign_id(ctx):
    doc_id = _int(_inp(ctx).get("documentId"), "documentId")
    r = await rg.prepare(await _org(), doc_id, WHO)
    return {"output": {"arhivaId": r["arhivaId"], "trukumi": r["trukumi"]}}


# ── P3 ──

async def _case(ctx) -> tuple[dict, dict]:
    org = await _org()
    pk = _int(_inp(ctx).get("lietasId"), "lietasId")
    return org, await cs.get_case(org["id"], pk)


async def case_fetch(ctx):
    _org_, c = await _case(ctx)
    today = date.today()
    retention_over = bool(c.get("retention_end") and c["retention_end"] <= today)
    return {"output": {
        "ilgstosa": bool(c.get("long_running")),
        "jautajumsIzbeigts": as_bool(_inp(ctx).get("jautajumsIzbeigts", False)),
        "periodsBeidzies": today.year > c["case_year"],
        "glabasanasVeids": c.get("retention_kind") or "",
        "riciba": c.get("disposition") or "",
        "terminsBeidzies": retention_over,
        "juridiskaisAizliegums": bool(c.get("legal_hold")),
        "lietasStatuss": c["status"],
    }}


async def case_check_completeness(ctx):
    _org_, c = await _case(ctx)
    return {"output": {"nepabeigtiDokumenti": c["nepabeigti"],
                       "nepabeigtie": [d["registration_number"] or f"#{d['id']}" for d in c["dokumenti"] if d["nepabeigts"]][:50]}}


async def files_normalize(ctx):
    """Konvertēšana uz PDF/A šajā DVS vēl nav ieviesta: datnes paliek oriģinālā, un tiek uzskaitītas
    tās, kurām konvertēšana vajadzīga (izpildīs 6. solī pirms nodošanas)."""
    _org_, c = await _case(ctx)
    pool = await get_pool()
    async with pool.acquire() as conn:
        files = await conn.fetch(
            "SELECT f.file_name, f.mime_type FROM document_files f JOIN documents d ON d.id = f.document_id WHERE d.case_id = $1", c["id"])
    need, bad = [], []
    for f in files:
        a = rg.file_action(f["mime_type"], f["file_name"], f["file_name"].lower().endswith((".edoc", ".asice", ".asics")))
        if a["riciba"] == "KonvertetPDFA":
            need.append(f["file_name"])
        elif not a["derigs"]:
            bad.append(f["file_name"])
    return {"output": {"konvertetas": 0, "jakonverte": need, "nederigas": len(bad), "nederigasDatnes": bad[:50]}}


async def case_close(ctx):
    from opendms.storage import get_storage
    org, c = await _case(ctx)
    closed = await cs.close_case(org, await sch.get_settings(org), c["id"], WHO, get_storage())
    return {"output": {"slegtaUz": closed["closed_at"].isoformat(),
                       "glabasanasBeigas": closed["retention_end"].isoformat() if closed.get("retention_end") else None,
                       "registraKontrolsumma": closed["register_sha256"]}}


async def case_carry_over(ctx):
    org, c = await _case(ctx)
    await cs.mark_long_running(org, c["id"], WHO)
    nxt: Optional[int] = None
    s = await sch.active_scheme(org["id"], date(c["case_year"] + 1, 6, 30))
    if s and c.get("shemas_ieraksts"):
        pool = await get_pool()
        async with pool.acquire() as conn:
            e = await conn.fetchval("SELECT id FROM scheme_entries WHERE scheme_id = $1 AND idx = $2 AND kind = 'lieta'",
                                    s["id"], c["case_index"])
        if e:
            nxt = (await cs.open_case(org, e, c["case_year"] + 1, WHO))["id"]
    return {"output": {"jaunaLietasId": nxt}}


async def case_task(ctx):
    """Lietotāja uzdevums lietai (piem., P3 ResolveUnfinished): ieraksts lietas vēsturē un sesijā."""
    import json
    org, c = await _case(ctx)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE standard_cases SET history = history || $2::jsonb WHERE id = $1", c["id"],
                           cs._hist("UzdevumsGaida", WHO, sesija=ctx.get("session_id"), solis=ctx.get("step_id"),
                                    nepabeigti=c["nepabeigti"]))
        await conn.execute("UPDATE uapf_sessions SET waiting_for = $2 WHERE session_id = $1", ctx.get("session_id"), ctx.get("step_id"))
    return {"output": {"status": "pending", "reviewTaskId": f"{ctx.get('session_id')}:{ctx.get('step_id')}"}}


def _ref(ns, op, summary):
    return {"namespace": ns, "operation": op, "version": 1, "summary": summary}


HANDLERS = {
    "case/resolve": (case_resolve, _ref("case", "resolve", "Propose the open case of the scheme for a document (archiving P2).")),
    "case/attach": (case_attach, _ref("case", "attach", "Put the document in a case; returns the registration-minimum inputs.")),
    "files/check": (files_check, _ref("files", "check", "Check each file's format with decision datnu-formati.")),
    "archive/assign-id": (archive_assign_id, _ref("archive", "assign-id", "Assign the 40-hex LNA archive ID when the minimum is met.")),
    "case/fetch": (case_fetch, _ref("case", "fetch", "Read a case: long-running, period over, retention, disposition, legal hold.")),
    "case/check-completeness": (case_check_completeness, _ref("case", "check-completeness", "Count unfinished documents in a case.")),
    "files/normalize": (files_normalize, _ref("files", "normalize", "List files that need PDF/A conversion before transfer (conversion not yet implemented).")),
    "case/close": (case_close, _ref("case", "close", "Close a case: date range, volume, retention end, document register with SHA-256.")),
    "case/carry-over": (case_carry_over, _ref("case", "carry-over", "Mark a long-running case and open it in the next period's scheme.")),
}

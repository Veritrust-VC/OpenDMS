"""Arhīvs: iestatījumi un lietu klasifikācijas shēma (kisc/dokumentu-arhivesanas-standarts 02, 04).

    GET  /api/archive/settings                   arhīva iestatījumi (arhīva kods, fonds, reģ. Nr., P2 slēdzis)
    PUT  /api/archive/settings
    GET  /api/archive/schemes                    shēmas pa periodiem
    POST /api/archive/schemes                    jauna shēma (tukša vai kopija no iepriekšējās)
    GET  /api/archive/schemes/active?on=YYYY-MM-DD
    GET  /api/archive/schemes/{id}               shēma ar ierakstiem
    DELETE /api/archive/schemes/{id}             tikai projektu
    POST /api/archive/schemes/{id}/import        .xlsx | .csv | .xml; ?izmeginajums=1 — tikai priekšskatījums
    POST /api/archive/schemes/{id}/status        {statuss, datums, atsauce, piezimes}
    GET  /api/archive/schemes/{id}/problems      kas neļauj apstiprināt
    GET  /api/archive/schemes/{id}/export.xml    ark:KlasifikacijasShema (pārbaudīts pret XSD)
    PATCH /api/archive/schemes/{id}/entries/{eid}
"""

from __future__ import annotations

import json
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from opendms.archive import scheme as sch
from opendms.audit import log_integration_event
from opendms.middleware.auth import get_current_user, require_role
from opendms.org_context import get_default_org_required

router = APIRouter(prefix="/api/archive", tags=["Archive"])
ADMIN = require_role("superadmin", "admin")


def _err(e: Exception):
    raise HTTPException(400, str(e))


async def _org() -> dict:
    return dict(await get_default_org_required())


async def _audit(user: dict, org: dict, action: str, entity_id: str, summary: dict):
    try:
        await log_integration_event(actor_user_id=user.get("id"), actor_email=user.get("email"), actor_role=user.get("role"),
                                    organization_id=org["id"], entity_type="classification_scheme", entity_id=entity_id,
                                    action=action, target_system="opendms", success=True,
                                    response_summary=json.dumps(summary, ensure_ascii=False, default=str)[:2000])
    except Exception:
        pass


class SettingsIn(BaseModel):
    archive_code: Optional[str] = None
    archive_name: Optional[str] = None
    fonds_number: Optional[str] = None
    fonds_name: Optional[str] = None
    registration_number: Optional[str] = None
    enforce_registration_minimum: Optional[bool] = None


@router.get("/settings")
async def get_settings(user=Depends(get_current_user)):
    return await sch.get_settings(await _org())


@router.put("/settings")
async def put_settings(body: SettingsIn, user=Depends(ADMIN)):
    org = await _org()
    try:
        out = await sch.put_settings(org, body.model_dump(exclude_unset=True), user.get("email"))
    except sch.SchemeError as e:
        _err(e)
    await _audit(user, org, "opendms.archive.settings.update", str(org["id"]), body.model_dump(exclude_unset=True))
    return out


class SchemeIn(BaseModel):
    period_from: date
    period_to: date
    title: Optional[str] = None
    sector: bool = False
    copy_from: Optional[int] = None


@router.get("/schemes")
async def list_schemes(user=Depends(get_current_user)):
    return await sch.list_schemes((await _org())["id"])


@router.post("/schemes", status_code=201)
async def create_scheme(body: SchemeIn, user=Depends(ADMIN)):
    org = await _org()
    try:
        s = await sch.create_scheme(org["id"], body.period_from, body.period_to, body.title, body.sector, body.copy_from, user.get("email"))
    except sch.SchemeError as e:
        _err(e)
    await _audit(user, org, "opendms.archive.scheme.create", str(s["id"]), body.model_dump(mode="json"))
    return s


@router.get("/schemes/active")
async def active(on: Optional[date] = None, user=Depends(get_current_user)):
    s = await sch.active_scheme((await _org())["id"], on or date.today())
    if not s:
        raise HTTPException(404, "Šim datumam nav apstiprinātas klasifikācijas shēmas")
    return s


@router.get("/schemes/{scheme_id}")
async def get_scheme(scheme_id: int, user=Depends(get_current_user)):
    try:
        s, entries = await sch.get_scheme((await _org())["id"], scheme_id)
    except sch.SchemeError as e:
        raise HTTPException(404, str(e))
    return {**s, "entries": entries}


@router.delete("/schemes/{scheme_id}", status_code=204)
async def delete_scheme(scheme_id: int, user=Depends(ADMIN)):
    org = await _org()
    try:
        await sch.delete_scheme(org["id"], scheme_id)
    except sch.SchemeError as e:
        _err(e)
    await _audit(user, org, "opendms.archive.scheme.delete", str(scheme_id), {})


@router.post("/schemes/{scheme_id}/import")
async def import_scheme(scheme_id: int, file: UploadFile = File(...), izmeginajums: bool = Query(False), user=Depends(ADMIN)):
    org = await _org()
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Datne lielāka par 10 MB")
    name = file.filename or "datne"
    try:
        parsed = sch.parse_ark_xml(data) if name.lower().endswith(".xml") else sch.rows_to_entries(sch.read_table(name, data))
    except sch.SchemeError as e:
        _err(e)
    except Exception as e:
        raise HTTPException(400, f"Datni nevar nolasīt: {type(e).__name__}: {e}")
    preview = {"datne": name, "kopsavilkums": parsed["summary"], "bridinajumi": parsed["warnings"],
               "ailes": parsed.get("columns"), "ieraksti": parsed["entries"][:400]}
    if izmeginajums:
        return {"izmeginajums": True, **preview}
    try:
        prob = await sch.replace_entries(org["id"], scheme_id, parsed, {"veids": "imports", "datne": name,
                                                                        "kas": user.get("email"), "kad": date.today().isoformat(),
                                                                        "bridinajumi": len(parsed["warnings"])})
    except sch.SchemeError as e:
        _err(e)
    await _audit(user, org, "opendms.archive.scheme.import", str(scheme_id), {"datne": name, **parsed["summary"]})
    return {"izmeginajums": False, **preview, "problemas": prob}


class StatusIn(BaseModel):
    statuss: str
    datums: Optional[date] = None
    atsauce: Optional[str] = None
    piezimes: Optional[str] = None


@router.post("/schemes/{scheme_id}/status")
async def set_status(scheme_id: int, body: StatusIn, user=Depends(ADMIN)):
    org = await _org()
    try:
        s = await sch.set_status(org["id"], scheme_id, body.statuss, body.datums.isoformat() if body.datums else None,
                                 body.atsauce, body.piezimes, user.get("email"))
    except sch.SchemeError as e:
        _err(e)
    await _audit(user, org, "opendms.archive.scheme.status", str(scheme_id), body.model_dump(mode="json"))
    return s


@router.get("/schemes/{scheme_id}/problems")
async def problems(scheme_id: int, user=Depends(get_current_user)):
    try:
        return await sch.problems((await _org())["id"], scheme_id)
    except sch.SchemeError as e:
        raise HTTPException(404, str(e))


@router.get("/schemes/{scheme_id}/export.xml")
async def export_xml(scheme_id: int, user=Depends(get_current_user)):
    org = await _org()
    try:
        s, entries = await sch.get_scheme(org["id"], scheme_id)
        data = sch.to_ark_xml(s, entries, org, await sch.get_settings(org))
    except sch.SchemeError as e:
        _err(e)
    fname = f"klasifikacijas-shema-{s['period_from']}-{s['period_to']}.xml"
    return Response(data, media_type="application/xml", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


class EntryIn(BaseModel):
    name: Optional[str] = None
    retention_kind: Optional[str] = None
    retention_years: Optional[int] = None
    retention_marks: Optional[list[str]] = None
    retention_legal_basis: Optional[str] = None
    retention_trigger: Optional[str] = None
    disposition: Optional[str] = None
    responsible_unit: Optional[str] = None
    responsible_person: Optional[str] = None
    medium: Optional[str] = None
    information_system: Optional[str] = None
    default_info_status: Optional[str] = None
    access_basis: Optional[str] = None
    access_until: Optional[date] = None
    long_running: Optional[bool] = None
    notes: Optional[str] = None


@router.patch("/schemes/{scheme_id}/entries/{entry_id}")
async def patch_entry(scheme_id: int, entry_id: int, body: EntryIn, user=Depends(ADMIN)):
    from opendms.database import get_pool
    org = await _org()
    try:
        s, _ = await sch.get_scheme(org["id"], scheme_id)
    except sch.SchemeError as e:
        raise HTTPException(404, str(e))
    if not s["editable"]:
        raise HTTPException(400, f"Shēmu statusā '{s['status_lv']}' mainīt nevar")
    vals = body.model_dump(exclude_unset=True)
    if not vals:
        return {"ok": True}
    pool = await get_pool()
    async with pool.acquire() as conn:
        sets = ", ".join(f"{k} = ${i + 3}" for i, k in enumerate(vals))
        try:
            row = await conn.fetchrow(f"UPDATE scheme_entries SET {sets} WHERE id = $1 AND scheme_id = $2 RETURNING *",
                                      entry_id, scheme_id, *vals.values())
        except Exception as e:
            raise HTTPException(400, f"Nederīga vērtība: {e}")
    if not row:
        raise HTTPException(404, "Ieraksts nav atrasts")
    await _audit(user, org, "opendms.archive.scheme.entry.update", str(entry_id), {k: str(v) for k, v in vals.items()})
    return dict(row)


# ───────────────────────── Lietas (standarts 03; UAPF P3) ─────────────────────────
#   GET  /api/archive/cases?gads=&statuss=        lietas ar dokumentu skaitu un nepabeigtajiem
#   POST /api/archive/cases                       {entry_id, gads} — atvērt no apstiprinātas shēmas
#   POST /api/archive/cases/open-period           {gads} — atvērt visas shēmas lietas gadam
#   GET  /api/archive/cases/{id}                  lieta ar dokumentiem, sējumiem, vēsturi
#   POST /api/archive/cases/{id}/documents        {document_id} — piesaistīt dokumentu atvērtai lietai
#   POST /api/archive/cases/{id}/close            case.close@1
#   POST /api/archive/cases/{id}/carry-over       case.carry-over@1 (ilgstoša lieta)
#   POST /api/archive/cases/{id}/volumes          papīra / hibrīda sējums
#   GET  /api/archive/cases/{id}/lieta.xml        ark:Lieta
#   GET  /api/archive/cases/{id}/register.xml     slēgtas lietas dokumentu reģistrs
#   POST /api/archive/documents/{id}/finish       atzīmēt dokumentu kā pabeigtu

from opendms.archive import cases as cs  # noqa: E402
from opendms.storage import get_storage  # noqa: E402

LIETVEDIS = require_role("superadmin", "admin", "operator")


async def _case_audit(user, org, action, entity_id, summary):
    try:
        await log_integration_event(actor_user_id=user.get("id"), actor_email=user.get("email"), actor_role=user.get("role"),
                                    organization_id=org["id"], entity_type="case", entity_id=entity_id,
                                    action=action, target_system="opendms", success=True,
                                    response_summary=json.dumps(summary, ensure_ascii=False, default=str)[:2000])
    except Exception:
        pass


@router.get("/cases")
async def list_cases(gads: Optional[int] = None, statuss: Optional[str] = None, user=Depends(get_current_user)):
    return await cs.list_cases((await _org())["id"], gads, statuss)


class CaseOpenIn(BaseModel):
    entry_id: int
    gads: int


@router.post("/cases", status_code=201)
async def open_case(body: CaseOpenIn, user=Depends(LIETVEDIS)):
    org = await _org()
    try:
        c = await cs.open_case(org, body.entry_id, body.gads, user.get("email"))
    except cs.CaseError as e:
        _err(e)
    await _case_audit(user, org, "opendms.archive.case.open", c["case_id"], body.model_dump())
    return c


class PeriodIn(BaseModel):
    gads: int


@router.post("/cases/open-period")
async def open_period(body: PeriodIn, user=Depends(ADMIN)):
    org = await _org()
    try:
        r = await cs.open_period(org, body.gads, user.get("email"))
    except cs.CaseError as e:
        _err(e)
    await _case_audit(user, org, "opendms.archive.case.open-period", str(body.gads), r)
    return r


@router.get("/cases/{case_pk}")
async def get_case(case_pk: int, user=Depends(get_current_user)):
    try:
        return await cs.get_case((await _org())["id"], case_pk)
    except cs.CaseError as e:
        raise HTTPException(404, str(e))


class AttachIn(BaseModel):
    document_id: int


@router.post("/cases/{case_pk}/documents")
async def attach(case_pk: int, body: AttachIn, user=Depends(LIETVEDIS)):
    org = await _org()
    try:
        r = await cs.attach_document(org, case_pk, body.document_id, user.get("email"), user.get("id"))
    except cs.CaseError as e:
        _err(e)
    await _case_audit(user, org, "opendms.archive.case.attach", str(case_pk), body.model_dump())
    return r


@router.post("/cases/{case_pk}/close")
async def close_case(case_pk: int, user=Depends(ADMIN)):
    org = await _org()
    try:
        c = await cs.close_case(org, await sch.get_settings(org), case_pk, user.get("email"), get_storage())
    except cs.CaseError as e:
        _err(e)
    await _case_audit(user, org, "opendms.archive.case.close", c["case_id"],
                      {"dokumenti": c["document_count"], "registraSha256": c["register_sha256"]})
    return c


@router.post("/cases/{case_pk}/carry-over")
async def carry_over(case_pk: int, user=Depends(ADMIN)):
    org = await _org()
    try:
        c = await cs.mark_long_running(org, case_pk, user.get("email"))
    except cs.CaseError as e:
        _err(e)
    await _case_audit(user, org, "opendms.archive.case.carry-over", c["case_id"], {})
    return c


class VolumeIn(BaseModel):
    medium: str = "P"
    content_type: str = "Teksts"
    document_count: Optional[int] = None
    page_count: Optional[int] = None
    notes: Optional[str] = None


@router.post("/cases/{case_pk}/volumes")
async def add_volume(case_pk: int, body: VolumeIn, user=Depends(ADMIN)):
    org = await _org()
    try:
        c = await cs.add_volume(org, case_pk, body.medium, body.content_type, body.document_count,
                                body.page_count, body.notes, user.get("email"))
    except cs.CaseError as e:
        _err(e)
    except Exception as e:
        raise HTTPException(400, f"Nederīga vērtība: {e}")
    await _case_audit(user, org, "opendms.archive.case.volume", c["case_id"], body.model_dump())
    return c


@router.get("/cases/{case_pk}/lieta.xml")
async def case_xml(case_pk: int, user=Depends(get_current_user)):
    org = await _org()
    try:
        data = cs.case_xml(org, await cs.get_case(org["id"], case_pk))
    except cs.CaseError as e:
        _err(e)
    return Response(data, media_type="application/xml", headers={"Content-Disposition": f'attachment; filename="lieta-{case_pk}.xml"'})


@router.get("/cases/{case_pk}/register.xml")
async def register_xml(case_pk: int, user=Depends(get_current_user)):
    org = await _org()
    try:
        c = await cs.get_case(org["id"], case_pk)
    except cs.CaseError as e:
        raise HTTPException(404, str(e))
    if not c.get("register_key"):
        raise HTTPException(404, "Reģistrs tiek izveidots, slēdzot lietu")
    data = await get_storage().get(c["register_key"])
    if data is None:
        raise HTTPException(404, "Reģistrs nav atrodams konteinerā")
    return Response(data, media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="lietas-registrs-{case_pk}.xml"',
                             "X-Sha256-Atbilst": str(__import__("hashlib").sha256(data).hexdigest() == c["register_sha256"]).lower()})


class FinishIn(BaseModel):
    piezime: Optional[str] = None


@router.post("/documents/{doc_id}/finish")
async def finish(doc_id: int, body: FinishIn, user=Depends(LIETVEDIS)):
    return await cs.finish_document(doc_id, user.get("email"), user.get("id"), body.piezime)


# ───────────────────────── P2: sagatavošana arhivēšanai reģistrācijā ─────────────────────────
#   GET  /api/archive/documents/{id}/readiness   minimums, datņu formāti, lietas ieteikums
#   POST /api/archive/documents/{id}/prepare     {case_id?, info_status?, access_basis?} → arhīva ID
#   GET  /api/archive/unfiled?gads=              dokumenti bez lietas vai arhīva ID

from opendms.archive import registration as rg  # noqa: E402


@router.get("/documents/{doc_id}/readiness")
async def readiness(doc_id: int, user=Depends(get_current_user)):
    try:
        return await rg.readiness((await _org())["id"], doc_id)
    except cs.CaseError as e:
        raise HTTPException(404, str(e))


class PrepareIn(BaseModel):
    case_id: Optional[int] = None
    info_status: Optional[str] = None
    access_basis: Optional[str] = None


@router.post("/documents/{doc_id}/prepare")
async def prepare(doc_id: int, body: PrepareIn, user=Depends(LIETVEDIS)):
    org = await _org()
    try:
        r = await rg.prepare(org, doc_id, user.get("email"), user.get("id"), body.case_id, body.info_status, body.access_basis)
    except cs.CaseError as e:
        _err(e)
    await _case_audit(user, org, "opendms.archive.document.prepare", str(doc_id),
                      {"gatavs": r["gatavs"], "trukumi": r["trukumi"], "arhivaId": r["arhivaId"]})
    if r["gatavs"]:
        from opendms.standard.service import refresh_package
        r["pakotneAtjaunota"] = await refresh_package(doc_id)
    return r


@router.get("/unfiled")
async def unfiled(gads: Optional[int] = None, user=Depends(get_current_user)):
    return await rg.unfiled((await _org())["id"], gads)


# ───────────────────────── Vīzas, iepazīšanās atzīmes, rezolūcijas (standarts 08, 8.2.) ─────────────────────────
#   GET  /api/archive/documents/{id}/marks
#   POST /api/archive/documents/{id}/visa            {rezultats, piezimes?, amats?, aizstaj?}
#   POST /api/archive/documents/{id}/acknowledge     {piezimes?, amats?}
#   POST /api/archive/documents/{id}/resolution      {uzdevumi:[{atbildigie:[user_id], apraksts, termins?}], piezimes?, amats?, aizstaj?}
#   GET  /api/archive/people                         aktīvie lietotāji atbildīgā izvēlei

from opendms.archive import marks as mk  # noqa: E402

DARBINIEKS = require_role("superadmin", "admin", "operator")


class VisaIn(BaseModel):
    rezultats: str = "Saskanots"
    piezimes: Optional[str] = None
    amats: Optional[str] = None
    aizstaj: Optional[int] = None


class AckIn(BaseModel):
    piezimes: Optional[str] = None
    amats: Optional[str] = None


class TaskIn(BaseModel):
    atbildigie: list[int]
    apraksts: str
    termins: Optional[date] = None


class ResolutionIn(BaseModel):
    uzdevumi: list[TaskIn]
    piezimes: Optional[str] = None
    amats: Optional[str] = None
    aizstaj: Optional[int] = None


async def _mark(user, doc_id, action, coro):
    org = await _org()
    try:
        r = await coro
    except mk.MarkError as e:
        _err(e)
    except ValueError as e:
        raise HTTPException(400, f"Nederīga vērtība: {e}")
    await _case_audit(user, org, f"opendms.archive.document.{action}", str(doc_id), {"ieraksts": r["id"]})
    from opendms.standard.service import refresh_package
    r["pakotneAtjaunota"] = await refresh_package(doc_id)
    return r


@router.get("/documents/{doc_id}/marks")
async def marks(doc_id: int, user=Depends(get_current_user)):
    from opendms.database import get_pool
    out = await mk.list_marks(doc_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, details, created_at FROM document_events WHERE document_id = $1 AND event_type = 'ParakstitsDVS' ORDER BY id", doc_id)
    out["paraksti"] = [{"id": r["id"], "datums": r["created_at"],
                        **(json.loads(r["details"]) if isinstance(r["details"], str) else r["details"])} for r in rows]
    return out


@router.post("/documents/{doc_id}/visa")
async def visa(doc_id: int, body: VisaIn, user=Depends(DARBINIEKS)):
    return await _mark(user, doc_id, "visa", mk.add_visa(doc_id, user["id"], body.rezultats, body.piezimes, body.amats, body.aizstaj))


@router.post("/documents/{doc_id}/acknowledge")
async def acknowledge(doc_id: int, body: AckIn, user=Depends(DARBINIEKS)):
    return await _mark(user, doc_id, "acknowledge", mk.add_acknowledgement(doc_id, user["id"], body.piezimes, body.amats))


@router.post("/documents/{doc_id}/resolution")
async def resolution(doc_id: int, body: ResolutionIn, user=Depends(DARBINIEKS)):
    tasks = [{**t.model_dump(), "termins": t.termins.isoformat() if t.termins else None} for t in body.uzdevumi]
    return await _mark(user, doc_id, "resolution", mk.add_resolution(doc_id, user["id"], tasks, body.piezimes, body.amats, body.aizstaj))


@router.get("/people")
async def people(user=Depends(get_current_user)):
    from opendms.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""SELECT id, full_name, department, position FROM users
                                    WHERE is_active AND role <> 'viewer' ORDER BY full_name""")
    return [dict(r) for r in rows]


# ───────────────────────── Parakstīšana DVS (MK 282 30. p.) ─────────────────────────
#   POST /api/archive/documents/{id}/sign     {amats?, piezimes?} — parakstītājs, laiks, datņu SHA-256
#   GET  /api/archive/documents/{id}/signing.xml

from opendms.archive import docmeta as dm  # noqa: E402


class SignIn(BaseModel):
    amats: Optional[str] = None
    piezimes: Optional[str] = None


@router.post("/documents/{doc_id}/sign")
async def sign(doc_id: int, body: SignIn, user=Depends(DARBINIEKS)):
    org = await _org()
    try:
        r = await dm.sign(doc_id, user["id"], get_storage(), body.amats, body.piezimes)
    except dm.SignError as e:
        _err(e)
    await _case_audit(user, org, "opendms.archive.document.sign", str(doc_id), {"ieraksts": r["id"], "datnes": r["datnes"]})
    from opendms.standard.service import refresh_package
    r["pakotneAtjaunota"] = await refresh_package(doc_id)
    return r


@router.get("/documents/{doc_id}/signing.xml")
async def signing(doc_id: int, user=Depends(get_current_user)):
    from opendms.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        uid = await conn.fetchval("SELECT doc_uid FROM documents WHERE id = $1", doc_id)
        evs = [dict(r) for r in await conn.fetch(
            "SELECT * FROM document_events WHERE document_id = $1 AND event_type = $2 ORDER BY id", doc_id, dm.EV_SIGN)]
    if not evs:
        raise HTTPException(404, "Dokuments DVS nav parakstīts")
    if not uid:
        raise HTTPException(409, "Dokumentam vēl nav LV-DOK identifikatora")
    return Response(dm.signing_xml(uid, evs), media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="parakstisana-{doc_id}.xml"'})

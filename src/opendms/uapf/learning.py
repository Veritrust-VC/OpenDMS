"""
Classification and routing that learn from the reviewer's corrections.

Two things live here:

* Reference data the process names in its mappings (uapf:schemaRef), read
  from ProcessGit: the topic classifier (tēmu klasifikators) and the
  organisation register (struktūrvienības). Example schemaRef:
      processgit:tiesibsargs/temu-klasifikators/klasifikators.xml,
      processgit:tiesibsargs/organizacijas-registrs/strukturvienibas.xml

* Precedents: every correction a reviewer confirms is stored in this DVS
  (never sent out). The classifier is given the most similar precedents with
  each new document; a near-identical precedent is applied directly, so the
  same mistake is not repeated. Precedents can be switched off by a person.
"""

from __future__ import annotations

import io
import json
import logging
import re
import ssl
import time
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional

import httpx

from opendms.config import get_settings
from opendms.database import get_pool

logger = logging.getLogger(__name__)

# A precedent this similar to the new document is applied without asking the model.
PRECEDENT_APPLY = 0.6
# Precedents below this similarity are not shown to the model.
PRECEDENT_SHOW = 0.08
CACHE_SECONDS = 600



# ─────────────────────────── reference data ───────────────────────────

def parse_refs(schema_ref: Optional[str]) -> dict[str, str]:
    """'processgit:o/r/path.xml, processgit:o/r/other.xml' -> {'path.xml': 'o/r/path.xml', ...}"""
    out: dict[str, str] = {}
    for part in re.split(r"[,\s]+", schema_ref or ""):
        if part.startswith("processgit:"):
            ref = part[len("processgit:"):]
            out[ref.rsplit("/", 1)[-1]] = ref
    return out


_zip_cache: dict[str, tuple[float, bytes]] = {}


async def fetch_repo_zip(owner: str, repo: str) -> bytes:
    """The main branch of a ProcessGit repository as a zip (cached). The zip comment
    holds the commit id (git archive)."""
    key = f"{owner}/{repo}"
    hit = _zip_cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    s = get_settings()
    url = f"{s.processgit_url.rstrip('/')}/api/v1/repos/{owner}/{repo}/archive/main.zip"
    headers = {"Authorization": f"token {s.processgit_token}"} if s.processgit_token else {}
    try:
        verify: object = True
        if s.processgit_ca_file:
            verify = ssl.create_default_context()
            verify.load_verify_locations(s.processgit_ca_file)
        async with httpx.AsyncClient(timeout=60.0, verify=verify) as hc:
            r = await hc.get(url, headers=headers)
            r.raise_for_status()
        data = r.content
        zipfile.ZipFile(io.BytesIO(data)).testzip()
    except Exception as e:
        if hit:
            logger.warning("ProcessGit %s unavailable (%s); using the cached copy", key, e)
            return hit[1]
        raise LookupError(f"Cannot read {key} from ProcessGit: {e}") from e
    _zip_cache[key] = (time.time(), data)
    return data


async def fetch_file(ref: str) -> bytes:
    """'owner/repo/path/in/repo.xml' from ProcessGit (main branch), cached."""
    owner, repo, path = ref.split("/", 2)
    data = await fetch_repo_zip(owner, repo)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = next((n for n in z.namelist() if n.split("/", 1)[-1] == path), None)
        if not name:
            raise LookupError(f"{path} not found in {owner}/{repo}")
        return z.read(name)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _name(el) -> str:
    for c in el:
        if _local(c.tag) == "Nosaukums":
            return (c.text or "").strip()
    return ""


def parse_klasifikators(xml: bytes) -> dict:
    """Flat list of every code with its joma and top-level kategorija."""
    root = ET.fromstring(xml)
    codes = []
    for joma in root:
        if _local(joma.tag) != "Joma":
            continue
        jk, jn = joma.get("kods"), _name(joma)

        def walk(el, kat, katn, path):
            for c in el:
                t = _local(c.tag)
                if t not in ("Kategorija", "Apakskategorija", "Tema"):
                    continue
                k, n = c.get("kods"), _name(c)
                if t == "Kategorija":
                    kat, katn = k, n
                codes.append({
                    "kods": k, "nosaukums": n, "limenis": t,
                    "izvelams": c.get("izvelams") != "false",
                    "joma": jk, "jomasNosaukums": jn,
                    "kategorija": kat, "kategorijasNosaukums": katn,
                    "cels": " › ".join(path + [n]),
                })
                walk(c, kat, katn, path + [n])

        walk(joma, None, None, [])
    return {"versija": root.get("versija") or "", "kodi": codes}


def parse_strukturvienibas(xml: bytes) -> list[dict]:
    root = ET.fromstring(xml)
    return [{"id": v.get("id"), "nosaukums": _name(v), "veids": v.get("veids")}
            for v in root if _local(v.tag) == "Vieniba" and v.get("statuss") != "slegta"]


async def reference_data(schema_ref: Optional[str]) -> dict:
    refs = parse_refs(schema_ref)
    out: dict = {"klasifikators": None, "vienibas": None, "avoti": refs}
    for fname, ref in refs.items():
        if fname.startswith("klasifikators"):
            out["klasifikators"] = parse_klasifikators(await fetch_file(ref))
        elif fname.startswith("strukturvienibas"):
            out["vienibas"] = parse_strukturvienibas(await fetch_file(ref))
    return out


# ─────────────────────────── text similarity ───────────────────────────

_STOP = set("""
kas lai par pie bet vai jau arī tas tā tie tās šis šī man mani mūsu jūsu viņš viņa viņi
kur kad kā nav ir bija būs esmu esam var tiek tika tikai vēl ļoti vairs nekā tomēr
iesniegums iesniegumu lūdzu tiesībsargs tiesībsargu tiesībsarga sintētisks
""".split())


def stems(text: str, limit: int = 40) -> list[str]:
    """Crude Latvian stems: lowercase words of 4+ letters, cut to 6 letters."""
    counts: dict[str, int] = {}
    for w in re.findall(r"[a-zāčēģīķļņšūž]{4,}", (text or "").lower()):
        if w in _STOP:
            continue
        s = w[:6]
        counts[s] = counts.get(s, 0) + 1
    return [s for s, _ in sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:limit]]


def similarity(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


# ─────────────────────────── precedent store ───────────────────────────

async def similar_precedents(package_id: Optional[str], text: str, kind: Optional[str] = None,
                             limit: int = 5) -> list[dict]:
    mine = stems(text)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, kind, excerpt, stems, predicted, corrected, reason, created_at
                 FROM uapf_precedents
                WHERE active AND ($1::text IS NULL OR package_id = $1)
                  AND ($2::text IS NULL OR kind = $2)
                ORDER BY created_at DESC LIMIT 500""",
            package_id, kind)
    out = []
    for r in rows:
        score = similarity(mine, list(r["stems"] or []))
        if score >= PRECEDENT_SHOW:
            out.append({
                "id": r["id"], "kind": r["kind"], "score": round(score, 3),
                "excerpt": r["excerpt"], "reason": r["reason"],
                "predicted": _j(r["predicted"]), "corrected": _j(r["corrected"]),
            })
    out.sort(key=lambda p: -p["score"])
    return out[:limit]


def _j(v):
    return json.loads(v) if isinstance(v, str) else (v or {})


async def mark_applied(ids: list[int]) -> None:
    if not ids:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE uapf_precedents SET applied_count = applied_count + 1, last_applied_at = NOW() WHERE id = ANY($1::bigint[])",
            ids)


async def record_precedent(*, package_id, document_id, session_id, kind, text, predicted,
                           corrected, reason, reviewer) -> int:
    from opendms.uapf.handlers import scrub_identifiers

    excerpt = scrub_identifiers((text or "")[:800])
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO uapf_precedents
                   (package_id, document_id, session_id, kind, excerpt, stems,
                    predicted, corrected, reason, reviewer)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id""",
            package_id, document_id, session_id, kind, excerpt, stems(text),
            json.dumps(predicted, ensure_ascii=False), json.dumps(corrected, ensure_ascii=False),
            reason, reviewer)


# ─────────────────────────── ai.classify@1 ───────────────────────────

CLASSIFY_PROMPT = """You classify a document received by the Office of the Ombudsman of Latvia
(Tiesībsarga birojs) into the office's topic classifier (tēmu klasifikators).

You get: the classifier as a list of codes (code | name | path), earlier corrections made by
staff on similar documents (precedents), and the PII-redacted document text.

Rules:
- Choose the single most specific code that fits the main issue of the document.
- Precedents are binding experience: if the document matches a precedent's situation,
  follow the precedent's corrected code, not the code that was wrongly proposed.
- If nothing fits, answer "neskaidrs".

Respond ONLY with JSON:
{"kods": "<code or neskaidrs>", "parliecība": <0..1>, "pamatojums": "<one sentence in Latvian>",
 "precedents": <id of the precedent you followed, or null>}"""


def _code_lines(klas: dict) -> str:
    return "\n".join(f"{c['kods']} | {c['nosaukums']} | {c['jomasNosaukums']} › {c['cels']}"
                     for c in klas["kodi"] if c["izvelams"])


def _result_from_code(klas: dict, kods: str) -> Optional[dict]:
    c = next((x for x in klas["kodi"] if x["kods"] == kods), None)
    if not c:
        return None
    return {"joma": c["joma"], "kategorija": c["kategorija"],
            "kategorijasNosaukums": c["kategorijasNosaukums"],
            "kods": c["kods"], "kodaNosaukums": c["nosaukums"]}


async def _package_of(session_id: Optional[str]) -> Optional[str]:
    if not session_id:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        pkg = await conn.fetchval("SELECT package_id FROM uapf_sessions WHERE session_id = $1", session_id)
    return None if not pkg or pkg == "<pending>" else pkg


async def _structured_choice(doc_id, session_id) -> Optional[dict]:
    """metadata.ievade.strukturets of the session's document, if it came from a structured form."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if not doc_id and session_id:
            doc_id = await conn.fetchval("SELECT document_id FROM uapf_sessions WHERE session_id = $1", session_id)
        if not doc_id:
            return None
        meta = await conn.fetchval("SELECT metadata FROM documents WHERE id = $1", int(doc_id))
    meta = json.loads(meta) if isinstance(meta, str) else (meta or {})
    return (meta.get("ievade") or {}).get("strukturets")


async def handle_ai_classify(ctx: dict) -> dict:
    from opendms.ai import _complete_json

    inp = ctx.get("input") or {}
    text = (inp.get("redactedContent") or inp.get("content") or "")[:12000]
    ref = await reference_data(ctx.get("schema_ref"))
    klas = ref["klasifikators"]
    if not klas:
        raise ValueError("ai.classify needs uapf:schemaRef naming processgit:<owner>/<repo>/klasifikators.xml")
    package_id = await _package_of(ctx.get("session_id"))
    precedents = await similar_precedents(package_id, text, kind="klasifikacija")
    base = {"klasifikatorsVersija": klas["versija"], "precedenti": [p["id"] for p in precedents]}

    # 0) a structured iesniegums carries the submitter's own choice — validated
    #    against this classifier at intake. It is used as given, without a model.
    st = await _structured_choice(inp.get("documentId"), ctx.get("session_id"))
    if st and st.get("kods"):
        res = _result_from_code(klas, st["kods"])
        if res:
            return {"output": {**base, **res, "confidence": 1.0, "klasifikacijasAvots": "iesniedzejs",
                               "klasifikacijasPamatojums": "Tēmu iesniedzējs izvēlējās strukturētajā veidlapā "
                                                           f"({st.get('shema') or 'iesnieguma shēma'})."}}
    if st and st.get("joma"):
        # Only the joma was chosen: the model picks a code inside that joma.
        klas = {**klas, "kodi": [c for c in klas["kodi"] if c["joma"] == st["joma"]]}
        base["jomaNoIesniedzeja"] = st["joma"]

    # 1) a near-identical earlier correction is applied as it is
    top = precedents[0] if precedents else None
    if top and top["score"] >= PRECEDENT_APPLY:
        res = _result_from_code(klas, (top["corrected"] or {}).get("kods") or "")
        if res:
            await mark_applied([top["id"]])
            return {"output": {**base, **res, "confidence": 0.95, "klasifikacijasAvots": "precedents",
                               "piemerotsPrecedents": top["id"],
                               "klasifikacijasPamatojums": f"Piemērots darbinieka labojums Nr. {top['id']} "
                                                           f"(līdzība {top['score']:.2f}): {top['reason'] or ''}".strip()}}

    # 2) the model, with the classifier and the precedents
    if not text:
        return {"output": {**base, "klasifikacijasAvots": "noteikumi",
                           "klasifikacijasPamatojums": "Nav teksta; paliek noteikumu (DMN) klasifikācija."}}
    prec_txt = "\n\n".join(
        f"Precedent {p['id']} (similarity {p['score']}):\n  text: {p['excerpt'][:400]}\n"
        f"  wrongly proposed: {(p['predicted'] or {}).get('kods') or (p['predicted'] or {}).get('kategorija')}\n"
        f"  correct: {(p['corrected'] or {}).get('kods')}\n  why: {p['reason'] or '-'}"
        for p in precedents) or "(none)"
    ans = await _complete_json(
        CLASSIFY_PROMPT,
        f"--- CLASSIFIER ---\n{_code_lines(klas)}\n\n--- PRECEDENTS ---\n{prec_txt}\n\n"
        f"--- DOCUMENT ---\n{text}\n--- END ---")
    res = _result_from_code(klas, str((ans or {}).get("kods") or "").strip())
    if not res:
        return {"output": {**base, "klasifikacijasAvots": "noteikumi",
                           "klasifikacijasPamatojums": "Modelis neatgrieza derīgu kodu; paliek noteikumu (DMN) klasifikācija."}}
    used = (ans or {}).get("precedents")
    if isinstance(used, int) and used in base["precedenti"]:
        await mark_applied([used])
    try:
        conf = max(0.0, min(1.0, float((ans or {}).get("parliecība", (ans or {}).get("parlieciba", 0.7)))))
    except (TypeError, ValueError):
        conf = 0.7
    return {"output": {**base, **res, "confidence": round(conf, 2), "klasifikacijasAvots": "modelis",
                       "piemerotsPrecedents": used if isinstance(used, int) else None,
                       "klasifikacijasPamatojums": str((ans or {}).get("pamatojums") or "")[:500]}}


# ─────────────────────────── learning.record@1 ───────────────────────────

async def handle_learning_record(ctx: dict) -> dict:
    """After a reviewer corrected the proposal (decision 'labots'): store the
    correction as a precedent and return the corrected values. They replace the
    proposal in the session; the process then re-routes (if only the topic was
    corrected) and records the result."""
    inp = ctx.get("input") or {}
    new_code = (inp.get("labotsKods") or "").strip()
    new_unit = (inp.get("labotaVieniba") or "").strip()
    if not new_code and not new_unit:
        return {"output": {"labojumsSaglabats": False, "vienibaLabota": False}}
    ref = await reference_data(ctx.get("schema_ref"))
    klas, units = ref["klasifikators"], ref["vienibas"] or []

    predicted = {k: inp.get(k) for k in ("joma", "kategorija", "kods", "vieniba", "department",
                                          "klasifikacijasAvots", "piemerotsPrecedents")}
    corrected: dict = {}
    if new_code and new_code != (inp.get("kods") or ""):
        res = _result_from_code(klas, new_code) if klas else None
        if not res:
            raise ValueError(f"labotsKods {new_code} is not in the classifier")
        corrected.update(res)
    if new_unit and new_unit != (inp.get("vieniba") or ""):
        u = next((x for x in units if x["id"] == new_unit), None)
        if units and not u:
            raise ValueError(f"labotaVieniba {new_unit} is not in the organisation register")
        corrected.update({"vieniba": new_unit, "department": (u or {}).get("nosaukums") or new_unit})
    if not corrected:
        return {"output": {"labojumsSaglabats": False, "vienibaLabota": False}}

    kind = "klasifikacija" if "kods" in corrected else "marsrutesana"
    # what the record says is right, in full
    full = {"kods": corrected.get("kods", inp.get("kods")), "joma": corrected.get("joma", inp.get("joma")),
            "kategorija": corrected.get("kategorija", inp.get("kategorija")),
            # a new unit only when the reviewer chose one; otherwise the routing
            # table decides again from the corrected joma
            "vieniba": corrected.get("vieniba") if "vieniba" in corrected else (None if "kods" in corrected else inp.get("vieniba"))}
    pid = await record_precedent(
        package_id=await _package_of(ctx.get("session_id")),
        document_id=int(inp["documentId"]) if inp.get("documentId") else None,
        session_id=ctx.get("session_id"), kind=kind,
        text=inp.get("redactedContent") or inp.get("content") or "",
        predicted=predicted, corrected=full,
        reason=inp.get("labojumaIemesls") or inp.get("comment"), reviewer=inp.get("reviewer"))

    return {"output": {**corrected, "labojumsSaglabats": True, "precedents": pid, "labojumaVeids": kind,
                       "vienibaLabota": "vieniba" in corrected, "labots": True,
                       "ieprieksejais": {k: v for k, v in predicted.items() if v is not None}}}

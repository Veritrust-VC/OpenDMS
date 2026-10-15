"""Dokumenti — find documents by number, subject, sender or meaning (Aģents → Dokumenti).

Two modes:
  teksts  the words as typed, in the number, title, sender, summary and the
          process results (topic, classification, department)
  nozime  the language model turns the question into the terms a document about
          it would contain (synonyms, legal terms, classification topics); the
          same search then runs with those terms and ranks by how many match.
          There is no vector index in the DVS: this is query expansion, said so in
          the result ("terms").
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from opendms.database import get_pool

logger = logging.getLogger(__name__)

STATUS_LV = {"draft": "Projekts", "registered": "Reģistrēts", "received": "Saņemts", "assigned": "Nodots izpildei",
             "decided": "Izlemts", "sent": "Nosūtīts", "archived": "Arhivēts"}

HAYSTACK = """lower(concat_ws(' ', d.registration_number, d.title, d.content_summary,
                   d.metadata->'sender'->>'name', d.metadata->'sender'->>'organization', d.metadata->'sender'->>'email',
                   d.metadata->'ievade'->>'temats', d.metadata->'ievade'->>'kopsavilkums',
                   d.metadata->'uapf_result'->>'topic', d.metadata->'uapf_result'->>'kodaNosaukums',
                   d.metadata->'uapf_result'->>'kategorijasNosaukums', d.metadata->'uapf_result'->>'department',
                   d.metadata->'uapf_result'->>'kods', d.semantic_summary::text))"""

EXPAND_PROMPT = """Tu palīdzi {org} darbiniekam atrast dokumentus DVS. Pārvērt jautājumu meklēšanas terminos, kas būtu
dokumenta nosaukumā, kopsavilkumā vai klasifikācijā: sinonīmi, juridiskie termini, tēmas, iestāžu nosaukumi.
Vārdu formas dod saīsinātas līdz saknei (piem. "bērnudārz", "diskrimin"), lai der visas locījuma formas.
Atbildi TIKAI ar JSON: {{"termini": ["…", "…"]}} — 3 līdz 10 termini, mazajiem burtiem."""


def _terms(q: str) -> list[str]:
    return [t for t in re.split(r"[\s,;]+", q.lower().strip()) if len(t) >= 2][:10]


async def expand(q: str) -> list[str]:
    from opendms.ai import _complete_json
    from opendms.org_context import org_label
    out = await _complete_json(EXPAND_PROMPT.format(org=await org_label()), q[:500], max_tokens=300, timeout=30)
    terms = [str(t).strip().lower() for t in ((out or {}).get("termini") or []) if str(t).strip()]
    return list(dict.fromkeys(terms + _terms(q)))[:12] or _terms(q)


async def search(q: str, *, mode: str = "teksts", limit: int = 30, status: Optional[str] = None) -> dict:
    q = (q or "").strip()
    if not q:
        return {"items": [], "terms": [], "mode": mode}
    terms = await expand(q) if mode == "nozime" else _terms(q)
    if not terms:
        return {"items": [], "terms": [], "mode": mode}
    params: list = []
    hits = []
    for t in terms:
        params.append(f"%{t}%")
        hits.append(f"(CASE WHEN {HAYSTACK} LIKE ${len(params)} THEN 1 ELSE 0 END)")
    score = " + ".join(hits)
    where = [f"({score}) > 0"]
    if mode == "teksts" and len(terms) > 1:      # typed words: all must match
        where = [f"({score}) = {len(terms)}"]
    if status:
        params.append(status)
        where.append(f"d.status = ${len(params)}")
    params.append(max(1, min(int(limit), 100)))
    sql = f"""SELECT d.id, d.registration_number, d.title, d.status, d.created_at, d.content_summary,
                     d.metadata->'sender' AS sender, d.metadata->'uapf_result' AS result,
                     d.metadata->'uapf_review' AS review, d.metadata->>'virziens' AS virziens,
                     ({score}) AS score
                FROM documents d
               WHERE {' AND '.join(where)}
               ORDER BY score DESC, d.created_at DESC
               LIMIT ${len(params)}"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    items = []
    for r in rows:
        j = lambda v: json.loads(v) if isinstance(v, str) else (v or {})
        sender, res, rev = j(r["sender"]), j(r["result"]), j(r["review"])
        items.append({
            "documentId": r["id"], "registrationNumber": r["registration_number"], "title": r["title"],
            "status": r["status"], "statusLv": STATUS_LV.get(r["status"], r["status"]),
            "direction": "izejošais" if r["virziens"] == "izejosais" else "ienākošais",
            "date": r["created_at"].isoformat() if r["created_at"] else None,
            "sender": sender.get("name") or sender.get("organization") or sender.get("email"),
            "summary": (r["content_summary"] or "")[:300] or None,
            "topic": res.get("kodaNosaukums") or res.get("topic"), "department": res.get("department"),
            "openStep": rev.get("stepId") if rev.get("status") == "gaida" else None,
            "score": r["score"],
        })
    return {"items": items, "terms": terms, "mode": mode}

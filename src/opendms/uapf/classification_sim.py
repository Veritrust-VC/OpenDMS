"""
Simulated classification scheme — stands in for the institution's real
klasifikācijas shēma (lietu nomenklatūra) until one is connected.

classification.lookup@1 matches the document text against keyword lists and
returns the scheme entry with its responsible unit and retention period. Every
answer carries "simulets": true so nobody mistakes it for the real scheme.
"""

from __future__ import annotations

import re
import unicodedata

SCHEME_NAME = "Simulēta klasifikācijas shēma (demo, nav iestādes apstiprināta)"

# (indekss, nosaukums, struktūrvienība, glabāšanas termiņš, atslēgvārdu saknes)
SCHEME = [
    ("I2", "ES fondu un INTERREG projektu lietas", "Attīstības instrumentu departaments",
     "10 gadi", ["interreg", "projekt", "progresa parskat", "es fond", "eiropas teritorial", "baltijas juras regiona"]),
    ("P", "Informatīvie paziņojumi un sarakste iepazīšanai", "Dokumentu pārvaldības nodaļa",
     "5 gadi", ["pazinojum", "informacijai", "zinasanai", "informativ", "iepazisanai"]),
    ("V1", "Privātpersonu iesniegumi un sūdzības", "Juridiskais departaments",
     "5 gadi", ["iesniegum", "sudzib", "ludzu izskatit", "atbildi"]),
    ("T3", "Teritorijas attīstības plānošanas lietas", "Telpiskās plānošanas departaments",
     "pastāvīgi", ["teritorij", "planojum", "zemes vienib", "buvniecib"]),
    ("D5", "Digitālās transformācijas un IKT lietas", "Digitālās transformācijas departaments",
     "10 gadi", ["digital", "ikt", "informacijas sistem", "maksligais intelekt", "datu"]),
    ("A2", "Pašvaldību darbības jautājumi", "Pašvaldību departaments",
     "10 gadi", ["pasvaldib", "novad", "dome ", "domes"]),
]
DEFAULT = ("X", "Nav noteikts — jāklasificē manuāli", "Dokumentu pārvaldības nodaļa", "—")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").lower()
    return "".join(c for c in text if not unicodedata.combining(c))


def lookup(text: str) -> dict:
    folded = _fold(text)
    best, best_hits = None, []
    for entry in SCHEME:
        hits = [k for k in entry[4] if re.search(re.escape(k), folded)]
        if len(hits) > len(best_hits):
            best, best_hits = entry, hits
    code, title, unit, retention = (best[:4] if best else DEFAULT)
    return {
        "klasifikacijasIndekss": code,
        "klasifikacijasNosaukums": title,
        "strukturvieniba": unit,
        "glabasanasTermins": retention,
        "atbilstiba": round(min(1.0, 0.4 + 0.2 * len(best_hits)), 2) if best else 0.0,
        "atbilstosieVardi": best_hits,
        "shema": SCHEME_NAME,
        "simulets": True,
    }

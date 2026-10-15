"""LNA simulators: akta un saraksta izskatīšana pēc noteikumiem; iesniegšana ar žetonu."""

import importlib.util
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opendms.archive import destruction as ds

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def sim(tmp_path, monkeypatch):
    monkeypatch.setenv("LNA_DATA", str(tmp_path))
    monkeypatch.setenv("LNA_TOKENS", "ombud=tok-o,varam=tok-v")
    spec = importlib.util.spec_from_file_location("lna_simulator", ROOT / "lna-simulator" / "lna_simulator.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["lna_simulator"] = m
    spec.loader.exec_module(m)
    return m


ORG = {"std_code": "05-0000", "name": "Tiesībsarga birojs"}
CID = "LV-LIETA:05-0000:2020:01928f3e-7b6a-7c3d-9e4f-0123456789ab"


def _act(perm=False, ek=True):
    a = {"number": "2026/1", "act_date": date(2026, 10, 15), "created_at": datetime(2026, 10, 15, tzinfo=timezone.utc),
         "ek_protocol_no": "EK-3", "ek_date": date(2026, 10, 14), "history": [{"darbiba": "Projekts", "kad": "2026-10-15"}],
         "lietas": [{"case_name": "Iesniegumi", "case_index": "1-12", "case_year": 2020, "date_from": date(2020, 1, 3),
                     "date_to": date(2020, 12, 20), "dokumenti": 2, "datnes": 2, "retention_kind": "Gadi", "retention_years": 5,
                     "case_id": CID}]}
    if perm:
        a["lietas"][0]["retention_kind"] = "Pastavigi"
    if not ek:
        a["ek_protocol_no"] = None
    return ds.act_xml(ORG, {}, a, [{"vardsUzvards": "Anna"}]).decode()


def test_act_rules(sim):
    assert sim.review_act(_act())["lemums"] == "Saskanots"
    r = sim.review_act(_act(perm=True))
    assert r["lemums"] == "Noraidits" and "pastāvīgi" in r["piezimes"][0]
    assert any("ekspertu komisijas" in n for n in sim.review_act(_act(ek=False))["piezimes"])


def test_submit_and_get(sim):
    c = TestClient(sim.app)
    assert c.post("/api/v1/iesniegumi", json={"veids": "plans", "gads": 2027}).status_code == 401
    r = c.post("/api/v1/iesniegumi", json={"veids": "akts", "atsauce": "7", "xml": _act()}, headers={"Authorization": "Bearer tok-o"})
    assert r.status_code == 201 and r.json()["statuss"] == "Saskanots" and r.json()["lemums"]["atsauce"].startswith("LNA-SIM-")
    iid = r.json()["id"]
    assert c.get(f"/api/v1/iesniegumi/{iid}", headers={"Authorization": "Bearer tok-v"}).status_code == 404   # cita iestāde
    p = c.post("/api/v1/iesniegumi", json={"veids": "plans", "gads": 2027}, headers={"Authorization": "Bearer tok-o"}).json()
    assert p["lemums"]["nodosanasLaiks"].startswith("2027-")
    assert "Iznīcināšanas akts" in c.get("/").text


def test_resume_output_mapping():
    from opendms.archive import lna_client as lna
    assert lna.resume_output("akts", {"lemums": "Saskanots", "atsauce": "LNA-SIM-1", "piezimes": []}) == \
        {"lnaLemums": "Saskanots", "lnaAtsauce": "LNA-SIM-1", "piezimes": None}
    p = lna.resume_output("plans", {"lemums": "Saskanots", "atsauce": "R", "vienosanasDatums": "2026-10-15", "nodosanasLaiks": "2027-05-31"})
    assert p["planaDatums"] == "2026-10-15" and "2027-05-31" in p["piezimes"]
    n = lna.resume_output("nodosana", {"lemums": "Pienemts", "atsauce": "R", "pienemsanasAkts": {"lnaStrukturvieniba": "EDG", "atbildigais": "A"}})
    assert n["lnaLemums"] == "Pienemts" and n["piezimes"] == "EDG, A"

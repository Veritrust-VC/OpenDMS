"""Status names and number format from ProcessGit."""

import asyncio
import json

from opendms import vocab


def test_format_number():
    assert vocab.format_number("{gads}/{kartas}", 7, length=4, year=2026) == "2026/0007"
    assert vocab.format_number("{iestade}-{gads}-{kartas}", 12, year=2026, org_code="TB") == "TB-2026-00012"
    assert vocab.format_number("{registrs}/{gads}/{kartas}", 3, length=3, year=2026) == "2026/003"


class Conn:
    def __init__(self):
        self.counter = {}

    async def execute(self, sql, *a):
        return "OK"

    async def fetchval(self, sql, *a):
        if "INSERT INTO registration_counters" in sql:
            k = (a[0], a[1])
            self.counter[k] = self.counter[k] + 1 if k in self.counter else a[2]
            return self.counter[k]
        if "date_part" in sql:
            return 35
        if "FROM organizations" in sql:
            return "TB"
        if "COUNT(*)" in sql:
            return 41
        return None


def test_next_number_uses_processgit_format_and_continues_the_year(monkeypatch):
    async def load(force=False):
        return {"statusi": {}, "numurs": {"formats": "{gads}/{kartas}", "kartasGarums": 4}}
    monkeypatch.setattr(vocab, "load", load)
    c = Conn()
    a = asyncio.run(vocab.next_number(c, 1))
    b = asyncio.run(vocab.next_number(c, 1))
    assert a.endswith("/0036") and b.endswith("/0037")


def test_without_format_old_number(monkeypatch):
    async def load(force=False):
        return {"statusi": {}, "numurs": None}
    monkeypatch.setattr(vocab, "load", load)
    assert asyncio.run(vocab.next_number(Conn(), 1)) == "1-00042"


def test_load_merges_statuses(monkeypatch):
    files = {"statusi.json": json.dumps({"versija": "1", "statusi": {"assigned": "Izpildē"}}).encode(),
             "numurs.json": b"{}"}

    async def fetch_file(ref):
        return files[ref.rsplit("/", 1)[-1]]
    import opendms.uapf.learning as ln
    monkeypatch.setattr(ln, "fetch_file", fetch_file)
    monkeypatch.setattr(vocab, "_ref", lambda: "tiesibsargs/lietvedibas-vardnicas")
    v = asyncio.run(vocab.load(force=True))
    assert v["statusi"]["assigned"] == "Izpildē" and v["statusi"]["registered"] == "Reģistrēts" and v["numurs"] is None

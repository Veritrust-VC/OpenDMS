"""Dokumenti: typed words must all match; meaning mode expands the question."""

import asyncio

from opendms import search
from opendms.mcp import tools


class Conn:
    def __init__(self, store):
        self.store = store

    async def fetch(self, sql, *params):
        self.store["sql"], self.store["params"] = sql, params
        return []


class Pool:
    def __init__(self, store):
        self.store = store

    def acquire(self):
        store = self.store

        class C:
            async def __aenter__(self):
                return Conn(store)

            async def __aexit__(self, *e):
                return False
        return C()


def test_text_mode_requires_all_words(monkeypatch):
    st = {}

    async def gp():
        return Pool(st)
    monkeypatch.setattr(search, "get_pool", gp)
    r = asyncio.run(search.search("Bērnu tiesības", mode="teksts"))
    assert r["terms"] == ["bērnu", "tiesības"]
    assert ") = 2" in st["sql"] and st["params"][:2] == ("%bērnu%", "%tiesības%")


def test_meaning_mode_expands(monkeypatch):
    st = {}

    async def gp():
        return Pool(st)

    async def expand(q):
        return ["bērnudārz", "pirmsskol", "rind"]
    monkeypatch.setattr(search, "get_pool", gp)
    monkeypatch.setattr(search, "expand", expand)
    r = asyncio.run(search.search("vieta bērnudārzā", mode="nozime"))
    assert r["terms"] == ["bērnudārz", "pirmsskol", "rind"] and ") > 0" in st["sql"]


def test_tool_listed():
    assert "meklet_dokumentus" in {t["name"] for t in tools.public_tools()}

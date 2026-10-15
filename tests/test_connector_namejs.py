"""Namejs connector — token handling, URL building and operations against a mock Namejs."""

import asyncio
import json

import httpx
import pytest

from opendms.connectors import describe_all, get_driver, namejs


def run(coro):
    return asyncio.run(coro)


CFG = {"base_url": "https://10.1.2.3", "client_id": "opendms", "verify_tls": False}
SEC = {"client_secret": "s3cret"}


class FakeNamejs:
    """Answers like the Namejs STS + /API, records what was asked."""

    def __init__(self):
        self.calls = []
        self.tokens = 0

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.calls.append((req.method, req.url.path, dict(req.url.params), req.content))
        if req.url.path == "/STS/connect/token":
            form = dict(x.split("=", 1) for x in req.content.decode().split("&"))
            if form.get("client_secret") != "s3cret" and form.get("password") != "pw":
                return httpx.Response(400, json={"error": "invalid_client"})
            self.tokens += 1
            return httpx.Response(200, json={"access_token": f"tok{self.tokens}", "expires_in": 3600})
        if req.headers.get("authorization", "")[:10] != "Bearer tok":
            return httpx.Response(401)
        p = req.url.path
        if p == "/API/api/users/myProfile":
            return httpx.Response(200, text=json.dumps({"userName": "integracija"}),
                                  headers={"content-type": "text/plain"})
        if p == "/API/api/flowStatuses":
            return httpx.Response(200, json=[{"id": 1, "code": "DST_REG"}, {"id": 2, "code": "DST_IZP"}])
        if p == "/API/api/documents":
            return httpx.Response(200, json=[{"id": 7, "name": "Iesniegums", "registrationNo": "1-2/3"}])
        if p == "/API/api/documents/7/register":
            return httpx.Response(204)
        if p == "/API/api/documentStatusNotifications" and req.method == "GET":
            return httpx.Response(200, json={"items": [{"id": 11, "documentId": 7, "status": "DST_REG"}]})
        if p == "/API/api/documentStatusNotifications" and req.method == "PATCH":
            return httpx.Response(204)
        if p == "/API/api/documents/7/files/3":
            return httpx.Response(200, content=b"%PDF-1.7",
                                  headers={"content-type": "application/pdf",
                                           "content-disposition": 'attachment; filename="v.pdf"'})
        return httpx.Response(404, text="not found")


@pytest.fixture
def fake(monkeypatch):
    f = FakeNamejs()
    real = httpx.AsyncClient

    def factory(*a, **kw):
        kw.pop("verify", None)
        return real(*a, transport=httpx.MockTransport(f.handler), **kw)

    monkeypatch.setattr(namejs.httpx, "AsyncClient", factory)
    namejs._tokens.clear()
    return f


def test_registered_and_named_namejs():
    d = get_driver("namejs")
    assert d is namejs and d.DISPLAY_NAME == "Namejs" and d.IMPLEMENTED
    cat = {x["kind"]: x for x in describe_all()}
    keys = [f["key"] for f in cat["namejs"]["config_fields"]]
    assert keys[:2] == ["base_url", "api_path"] and "client_id" in keys
    assert all(f["kind"] == "password" for f in cat["namejs"]["secret_fields"])


@pytest.mark.parametrize("base,api,want_api,want_tok", [
    ("https://dvs.iestade.lv", None, "https://dvs.iestade.lv/API", "https://dvs.iestade.lv/STS/connect/token"),
    ("10.20.30.40", "", "https://10.20.30.40/API", "https://10.20.30.40/STS/connect/token"),
    ("https://dvs.iestade.lv/API/", "/API", "https://dvs.iestade.lv/API", "https://dvs.iestade.lv/STS/connect/token"),
    ("https://x.lv:8443", "Namejs/API", "https://x.lv:8443/Namejs/API", "https://x.lv:8443/STS/connect/token"),
])
def test_urls(base, api, want_api, want_tok):
    cfg = {"base_url": base, "api_path": api}
    assert namejs._base(cfg) == want_api
    assert namejs._token_url(cfg) == want_tok


def test_preflight_by_grant():
    r = run(namejs.test({"base_url": "x"}, {}))
    assert not r.ok and set(r.data["missing"]) >= {"client_id", "client_secret"}
    r = run(namejs.test({"base_url": "x", "client_id": "c", "grant_type": "password"}, {}))
    assert not r.ok and set(r.data["missing"]) == {"username", "password"}


def test_connection_test_ok(fake):
    r = run(namejs.test(CFG, SEC))
    assert r.ok, r.reason
    assert r.data["account"] == "integracija" and r.data["flow_statuses"] == 2
    assert fake.tokens == 1          # one token reused for both calls


def test_bad_secret_is_a_result_not_exception(fake):
    r = run(namejs.test(CFG, {"client_secret": "wrong"}))
    assert not r.ok and "STS" in r.reason and "invalid_client" in r.reason


def test_password_grant(fake):
    cfg = {**CFG, "grant_type": "password", "username": "janis"}
    r = run(namejs.test(cfg, {"password": "pw"}))
    assert r.ok, r.reason
    form = fake.calls[0][3].decode()
    assert "grant_type=password" in form and "username=janis" in form


def test_operations(fake):
    r = run(namejs.invoke("search_documents", CFG, SEC, {"registration_no": "1-2/3"}, {}))
    assert r.ok and r.data["count"] == 1
    q = [c for c in fake.calls if c[1] == "/API/api/documents"][0][2]
    assert q == {"RegistrationNo": "1-2/3", "Limit": "50"}

    assert run(namejs.invoke("register_document", CFG, SEC, {"document_id": 7}, {})).data["registered"]

    r = run(namejs.invoke("poll_status_notifications", CFG, SEC, {}, {}))
    assert r.ok and r.data["count"] == 1 and r.data["acknowledged"]
    patch = [c for c in fake.calls if c[0] == "PATCH"][0]
    assert json.loads(patch[3]) == [11]

    r = run(namejs.invoke("get_document_file", CFG, SEC, {"document_id": 7, "file_id": 3}, {}))
    assert r.ok and r.data["file_name"] == "v.pdf" and r.data["size"] == 8

    r = run(namejs.invoke("get_document", CFG, SEC, {}, {}))
    assert not r.ok and "document_id" in r.reason
    r = run(namejs.invoke("nope", CFG, SEC, {}, {}))
    assert not r.ok and "available" in r.data

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opendms.routers import documents as documents_router
from opendms.routers import intelligence as intelligence_router
from opendms.middleware.auth import get_current_user


async def _fake_get_pool(pool):
    return pool


async def _fake_default_org():
    return {"id": 1}


async def _fake_log(**kwargs):
    return None


async def _fake_create_document(**kwargs):
    return {"docDid": "did:doc:1", "semanticSummary": {"summarySource": "AI"}, "sensitivityControl": {"allowCentralization": True}}


async def _fake_extract_summary(*args, **kwargs):
    return {"semanticSummary": {"summarySource": "AI"}, "sensitivityControl": {"allowCentralization": True}}


async def _fake_topics(**kwargs):
    return {"items": [{"topic": "ENVIRONMENT"}]}


async def _fake_similar(*args, **kwargs):
    return {"items": [{"title": "Similar"}]}


async def _fake_warnings(**kwargs):
    return {"items": [{"title": "Risk"}]}


async def _fake_briefing(*args, **kwargs):
    return {"summary": "ok"}


class _Acquire:
    def __init__(self, conn):
        self.conn = conn
    async def __aenter__(self):
        return self.conn
    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn
    def acquire(self):
        return _Acquire(self.conn)


class FakeConn:
    def __init__(self):
        self.insert_payload = None
        self.updated = None

    async def fetchval(self, query, *args):
        if "COUNT(*) FROM documents" in query:
            return 0
        return None

    async def fetchrow(self, query, *args):
        if query.strip().startswith("INSERT INTO documents"):
            self.insert_payload = args
            return {
                "id": 1,
                "title": args[0],
                "registration_number": args[1],
                "doc_did": "did:doc:1",
                "status": "registered",
                "org_id": args[3],
                "semantic_summary": args[8],
                "sensitivity_control": args[9],
                "ai_summary_status": args[10],
                "created_at": "now",
            }
        if "FROM documents d" in query:
            return {
                "id": 1,
                "title": "Doc",
                "registration_number": "1-00001",
                "doc_did": "did:doc:1",
                "status": "registered",
                "org_id": 1,
                "metadata": json.dumps({}),
                "semantic_summary": json.dumps({"summarySource": "AI"}),
                "sensitivity_control": json.dumps({"allowCentralization": True}),
            }
        if "SELECT id, org_id FROM documents" in query:
            return {"id": 1, "org_id": 1}
        return None

    async def execute(self, query, *args):
        if query.strip().startswith("UPDATE documents SET semantic_summary"):
            self.updated = args
        return "OK"

    async def fetch(self, query, *args):
        return []


@pytest.fixture
def app(monkeypatch):
    app = FastAPI()
    app.include_router(documents_router.router)
    app.include_router(intelligence_router.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "email": "a@b", "role": "admin"}

    conn = FakeConn()
    pool = FakePool(conn)
    monkeypatch.setattr(documents_router, "get_pool", lambda: _fake_get_pool(pool))
    monkeypatch.setattr(documents_router, "get_default_org_required", _fake_default_org)
    monkeypatch.setattr(documents_router, "log_integration_event", _fake_log)
    monkeypatch.setattr(documents_router, "get_settings", lambda: SimpleNamespace(sdk_enabled=True, storage_backend="local"))
    monkeypatch.setattr(documents_router.sdk_client, "create_document", _fake_create_document)
    monkeypatch.setattr(documents_router.sdk_client, "extract_summary", _fake_extract_summary)

    monkeypatch.setattr(intelligence_router.sdk_client, "get_topic_trends", _fake_topics)
    monkeypatch.setattr(intelligence_router.sdk_client, "get_similar_documents", _fake_similar)
    monkeypatch.setattr(intelligence_router.sdk_client, "get_warnings", _fake_warnings)
    monkeypatch.setattr(intelligence_router.sdk_client, "generate_briefing", _fake_briefing)

    app.state._conn = conn
    return app


def test_document_create_with_semantic_summary(app):
    c = TestClient(app)
    r = c.post("/api/documents", json={
        "title": "Doc",
        "content_summary": "Legacy summary",
        "metadata": {},
        "semantic_summary": {"summarySource": "HYBRID", "summary": "Reviewed"},
        "sensitivity_control": {"allowCentralization": True},
    })
    assert r.status_code == 201
    assert r.json()["ai_summary_status"] == "VALIDATED"


def test_legacy_document_create_still_works(app):
    c = TestClient(app)
    r = c.post("/api/documents", json={"title": "Doc", "content_summary": "Legacy", "metadata": {}})
    assert r.status_code == 201
    assert r.json()["ai_summary_status"] in {"GENERATED", "SKIPPED"}


def test_extract_summary_preview_endpoint(app):
    c = TestClient(app)
    files = {"file": ("a.txt", b"hello", "text/plain")}
    data = {"metadata": json.dumps({"docType": "REPORT"})}
    r = c.post("/api/documents/extract-summary-preview", files=files, data=data)
    assert r.status_code == 200
    assert r.json()["semanticSummary"]["summarySource"] == "AI"


def test_intelligence_proxy_endpoints(app):
    c = TestClient(app)
    assert c.get("/api/intelligence/topics").status_code == 200
    assert c.get("/api/intelligence/similar/did:doc:1").status_code == 200
    assert c.get("/api/intelligence/warnings").status_code == 200
    assert c.post("/api/intelligence/briefing", json={"context": {}}).status_code == 200

"""MCP lietvedība tools: catalogue and the read/write split."""

import asyncio
import json

from opendms.mcp import server, tools

NEW_READ = {"worklist", "document_history", "people_and_categories"}
NEW_WRITE = {"assign_document", "apply_classification", "add_note"}


def test_new_tools_listed_with_handlers():
    names = {t["name"] for t in tools.public_tools()}
    assert NEW_READ | NEW_WRITE <= names
    for n in NEW_READ | NEW_WRITE:
        assert n in tools.HANDLERS
    assert all("class" not in t for t in tools.public_tools())


def test_classes():
    for n in NEW_READ:
        assert tools.TOOL_INDEX[n]["class"] == tools.READ
    for n in NEW_WRITE:
        assert tools.TOOL_INDEX[n]["class"] == tools.WRITE


def test_no_decision_tools_exposed():
    names = {t["name"] for t in tools.public_tools()}
    for forbidden in ("decide_document", "send_document", "archive_document", "approve", "reject", "delete_document"):
        assert forbidden not in names


def test_read_scope_cannot_write():
    async def call(name):
        return await server._dispatch(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": name, "arguments": {"document_id": 1, "text": "x"}}},
            {"ok": True, "principal": "node-token", "scope": "read", "user": None})
    for n in NEW_WRITE:
        res = asyncio.run(call(n))
        assert res["result"]["isError"] is True
        assert "read access only" in json.loads(res["result"]["content"][0]["text"])["error"]

"""End-to-end tests for the streamable HTTP transport (fake Salesforce transport, no live org)."""

import asyncio
import json
import time

import pytest
from starlette.testclient import TestClient

from salesforce_mcp import auth, server
from tests.test_server_restful import _CaptureAdapter

_ACCEPT = "application/json, text/event-stream"


@pytest.fixture(scope="module")
def http_client():
    with TestClient(server.mcp.streamable_http_app()) as c:
        yield c


def _rpc(http_client, method, params=None, headers=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    resp = http_client.post("/mcp", json=body, headers={"Accept": _ACCEPT, **(headers or {})})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_initialize_and_tools_list_need_no_credentials(http_client):
    init = _rpc(
        http_client,
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
    )
    assert init["result"]["serverInfo"]["name"] == "Salesforce"
    tools = _rpc(http_client, "tools/list")["result"]["tools"]
    assert "run_soql_query" in {t["name"] for t in tools}


def test_tool_call_uses_the_callers_forwarded_env_headers(http_client, monkeypatch):
    adapter = _CaptureAdapter()

    def capturing_client(env):
        sf = auth.create_salesforce_client(env)
        sf.session.mount("https://", adapter)
        return sf

    monkeypatch.setattr(server, "create_salesforce_client", capturing_client)
    result = _rpc(
        http_client,
        "tools/call",
        {"name": "restful", "arguments": {"path": "limits"}},
        headers={
            "X-MintMCP-Env-SALESFORCE_ACCESS_TOKEN": "user-a-token",
            "X-MintMCP-Env-SALESFORCE_INSTANCE_URL": "https://user-a.my.salesforce.com",
        },
    )

    assert not result["result"]["isError"], result
    sent = adapter.sent[0]
    assert sent.url.startswith("https://user-a.my.salesforce.com/services/data/")
    assert sent.headers["Authorization"] == "Bearer user-a-token"
    assert json.loads(result["result"]["content"][0]["text"]) == {"ok": True}


def test_tool_call_without_credentials_returns_a_tool_error(http_client, monkeypatch):
    monkeypatch.setattr(server.client, "_sf", None)
    for name in ("SALESFORCE_USERNAME", "SALESFORCE_ACCESS_TOKEN", "SALESFORCE_INSTANCE_URL"):
        monkeypatch.delenv(name, raising=False)
    result = _rpc(
        http_client,
        "tools/call",
        {"name": "restful", "arguments": {"path": "limits"}},
        headers={"X-MintMCP-Env-SALESFORCE_ACCESS_TOKEN": "only-token"},
    )
    assert result["result"]["isError"]
    assert "Missing Salesforce credentials" in result["result"]["content"][0]["text"]


def test_slow_tool_calls_do_not_block_each_other(monkeypatch):
    class _SlowSf:
        def query(self, soql):
            time.sleep(0.5)
            return {"records": []}

    monkeypatch.setattr(server.client, "_sf", _SlowSf())

    async def two_queries():
        await asyncio.gather(
            server.run_soql_query("SELECT Id FROM Account"),
            server.run_soql_query("SELECT Id FROM Contact"),
        )

    started = time.monotonic()
    asyncio.run(two_queries())
    assert time.monotonic() - started < 0.9

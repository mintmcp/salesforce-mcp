"""Unit tests for the restful tool's HTTP encoding (fake transport, no live org)."""

import json

import requests
from simple_salesforce import Salesforce

from salesforce_mcp import server


class _CaptureAdapter(requests.adapters.BaseAdapter):
    def __init__(self):
        super().__init__()
        self.sent: list[requests.PreparedRequest] = []

    def send(self, request, **kwargs):
        self.sent.append(request)
        resp = requests.Response()
        resp.status_code = 200
        resp._content = b'{"ok": true}'
        resp.headers["Content-Type"] = "application/json"
        resp.request = request
        return resp

    def close(self):
        pass


def _capture(monkeypatch) -> _CaptureAdapter:
    adapter = _CaptureAdapter()
    session = requests.Session()
    session.mount("https://", adapter)
    sf = Salesforce(
        instance="example.my.salesforce.com", session_id="token", session=session
    )
    monkeypatch.setattr(server.client, "_sf", sf)
    return adapter


def test_restful_sends_data_as_json_body(monkeypatch):
    adapter = _capture(monkeypatch)
    payload = {"inputs": [{"action": "EDIT_AS_DRAFT_ARTICLE", "articleId": "kA0"}]}
    server.restful(
        "actions/standard/createDraftFromOnlineKnowledgeArticle",
        method="POST",
        data=payload,
    )
    req = adapter.sent[0]
    assert req.method == "POST"
    assert req.headers["Content-Type"] == "application/json"
    assert json.loads(req.body) == payload


def test_restful_get_sends_params_without_body(monkeypatch):
    adapter = _capture(monkeypatch)
    server.restful("analytics/reports/00O000000000001", params={"includeDetails": "true"})
    req = adapter.sent[0]
    assert req.method == "GET"
    assert "includeDetails=true" in req.url
    assert req.body is None

"""Unit tests for reading per-user env vars from MintMCP's X-MintMCP-Env-* headers."""

import socket
import threading

import requests

from salesforce_mcp import auth
from salesforce_mcp.auth import create_salesforce_client, env_from_headers, request_env


def test_env_from_headers_keeps_only_mintmcp_env_headers():
    headers = {
        "x-mintmcp-env-salesforce_access_token": "tok123",
        "X-MintMCP-Env-SALESFORCE_INSTANCE_URL": "https://example.my.salesforce.com",
        "authorization": "Bearer gateway-token",
        "content-type": "application/json",
    }
    assert env_from_headers(headers) == {
        "SALESFORCE_ACCESS_TOKEN": "tok123",
        "SALESFORCE_INSTANCE_URL": "https://example.my.salesforce.com",
    }


def test_env_from_headers_maps_hosted_oauth_headers():
    headers = {
        "X-Salesforce-Access-Token": "tok123",
        "x-salesforce-instance-url": "https://example.my.salesforce.com",
    }
    assert env_from_headers(headers) == {
        "SALESFORCE_ACCESS_TOKEN": "tok123",
        "SALESFORCE_INSTANCE_URL": "https://example.my.salesforce.com",
    }


def test_env_from_headers_without_mintmcp_headers_is_empty():
    assert env_from_headers({"authorization": "Bearer x"}) == {}


def test_create_salesforce_client_reads_the_given_env():
    sf = create_salesforce_client(
        {
            "SALESFORCE_ACCESS_TOKEN": "tok123",
            "SALESFORCE_INSTANCE_URL": "https://example.my.salesforce.com",
        }
    )
    assert sf.session_id == "tok123"
    assert sf.sf_instance == "example.my.salesforce.com"


def test_request_env_keeps_process_credentials_when_headers_carry_none(monkeypatch):
    monkeypatch.setenv("SALESFORCE_ACCESS_TOKEN", "global-token")
    monkeypatch.setenv("SALESFORCE_DOMAIN", "login")
    env = request_env({"SALESFORCE_DOMAIN": "test"})
    assert env["SALESFORCE_ACCESS_TOKEN"] == "global-token"
    assert env["SALESFORCE_DOMAIN"] == "test"


def test_salesforce_calls_time_out_instead_of_hanging(monkeypatch):
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    accepted = []
    threading.Thread(target=lambda: accepted.append(server.accept()), daemon=True).start()
    monkeypatch.setattr(auth, "REQUEST_TIMEOUT", (1, 1))
    sf = create_salesforce_client(
        {
            "SALESFORCE_ACCESS_TOKEN": "tok",
            "SALESFORCE_INSTANCE_URL": f"http://127.0.0.1:{server.getsockname()[1]}",
        }
    )

    outcome = []

    def query():
        try:
            sf.query("SELECT Id FROM Account")
        except requests.exceptions.RequestException as exc:
            outcome.append(exc)

    worker = threading.Thread(target=query, daemon=True)
    worker.start()
    worker.join(5)
    server.close()

    assert not worker.is_alive(), "Salesforce call hung past its timeout"
    assert isinstance(outcome[0], requests.exceptions.Timeout)


def test_access_token_with_a_bearer_prefix_is_accepted():
    # Mint's client credentials form pre-fills "Bearer " as the header prefix.
    sf = create_salesforce_client(
        {
            "SALESFORCE_ACCESS_TOKEN": "Bearer tok123",
            "SALESFORCE_INSTANCE_URL": "https://example.my.salesforce.com",
        }
    )
    assert sf.session_id == "tok123"

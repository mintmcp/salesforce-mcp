"""Unit tests for reading per-user env vars from MintMCP's X-MintMCP-Env-* headers."""

from salesforce_mcp.auth import create_salesforce_client, env_from_headers


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

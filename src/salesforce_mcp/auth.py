"""Salesforce authentication — username/password or OAuth."""

import os
from collections.abc import Mapping

from simple_salesforce import Salesforce

# Over HTTP, MintMCP sends each user's env vars as X-MintMCP-Env-<NAME> request headers.
_ENV_HEADER_PREFIX = "x-mintmcp-env-"
# MintMCP reserves the X-MintMCP-Env- prefix, so Hosted OAuth token fields map to these instead.
_OAUTH_HEADERS = {
    "x-salesforce-access-token": "SALESFORCE_ACCESS_TOKEN",
    "x-salesforce-instance-url": "SALESFORCE_INSTANCE_URL",
}


def env_from_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Collect the per-user env vars MintMCP forwards as `X-MintMCP-Env-<NAME>` or Hosted OAuth headers."""
    env = {}
    for name, value in headers.items():
        lower = name.lower()
        if lower.startswith(_ENV_HEADER_PREFIX):
            env[lower[len(_ENV_HEADER_PREFIX) :].upper()] = value
        elif lower in _OAUTH_HEADERS:
            env[_OAUTH_HEADERS[lower]] = value
    return env


def create_salesforce_client(env: Mapping[str, str] = os.environ) -> Salesforce:
    """Create a Salesforce client from environment variables.

    Tries username/password/token first (default), falls back to OAuth
    (access_token + instance_url) if those aren't set.
    """
    username = env.get("SALESFORCE_USERNAME")
    password = env.get("SALESFORCE_PASSWORD")
    security_token = env.get("SALESFORCE_SECURITY_TOKEN")
    domain = env.get("SALESFORCE_DOMAIN")

    if username and password and security_token:
        return Salesforce(
            username=username,
            password=password,
            security_token=security_token,
            domain=domain or "login",
        )

    access_token = env.get("SALESFORCE_ACCESS_TOKEN")
    instance_url = env.get("SALESFORCE_INSTANCE_URL")

    if access_token and instance_url:
        return Salesforce(instance_url=instance_url, session_id=access_token)

    raise ValueError(
        "Missing Salesforce credentials. Set either:\n"
        "  1) SALESFORCE_USERNAME + SALESFORCE_PASSWORD + SALESFORCE_SECURITY_TOKEN, or\n"
        "  2) SALESFORCE_ACCESS_TOKEN + SALESFORCE_INSTANCE_URL\n"
        "Over HTTP, send them as X-MintMCP-Env-<NAME> headers, or map Hosted OAuth "
        "to X-Salesforce-Access-Token and X-Salesforce-Instance-Url."
    )

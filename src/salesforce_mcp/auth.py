"""Salesforce authentication — username/password or OAuth."""

import os
from collections.abc import Mapping

import requests
from simple_salesforce import Salesforce

# (connect, read) seconds. Over HTTP every user shares one worker pool, so a stalled
# Salesforce call must not hold a thread forever. 120s matches Salesforce's own query limit.
REQUEST_TIMEOUT = (10, 120)
_CREDENTIAL_VARS = frozenset(
    {
        "SALESFORCE_USERNAME",
        "SALESFORCE_PASSWORD",
        "SALESFORCE_SECURITY_TOKEN",
        "SALESFORCE_ACCESS_TOKEN",
        "SALESFORCE_INSTANCE_URL",
    }
)
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


def request_env(header_env: Mapping[str, str]) -> dict[str, str]:
    """Process env overlaid with one request's header env.

    Credentials in the headers replace every credential in process env, so a user's
    token is never paired with, or outranked by, the connector's global login.
    """
    process_env = dict(os.environ)
    if _CREDENTIAL_VARS & header_env.keys():
        process_env = {k: v for k, v in process_env.items() if k not in _CREDENTIAL_VARS}
    return {**process_env, **header_env}


class _TimeoutSession(requests.Session):
    def request(self, *args, **kwargs):
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        return super().request(*args, **kwargs)


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
            session=_TimeoutSession(),
        )

    # Salesforce session IDs contain no spaces, so a "Bearer " header prefix is always a misconfiguration.
    access_token = env.get("SALESFORCE_ACCESS_TOKEN", "").removeprefix("Bearer ").strip()
    instance_url = env.get("SALESFORCE_INSTANCE_URL")

    if access_token and instance_url:
        return Salesforce(
            instance_url=instance_url, session_id=access_token, session=_TimeoutSession()
        )

    raise ValueError(
        "Missing Salesforce credentials. Set either:\n"
        "  1) SALESFORCE_USERNAME + SALESFORCE_PASSWORD + SALESFORCE_SECURITY_TOKEN, or\n"
        "  2) SALESFORCE_ACCESS_TOKEN + SALESFORCE_INSTANCE_URL\n"
        "Over HTTP, send them as X-MintMCP-Env-<NAME> headers, or map Hosted OAuth "
        "to X-Salesforce-Access-Token and X-Salesforce-Instance-Url."
    )

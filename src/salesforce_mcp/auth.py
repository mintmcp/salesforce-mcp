"""Salesforce authentication — username/password or OAuth."""

import os

from simple_salesforce import Salesforce


def create_salesforce_client() -> Salesforce:
    """Create a Salesforce client from environment variables.

    Tries username/password/token first (default), falls back to OAuth
    (access_token + instance_url) if those aren't set.
    """
    username = os.environ.get("SALESFORCE_USERNAME")
    password = os.environ.get("SALESFORCE_PASSWORD")
    security_token = os.environ.get("SALESFORCE_SECURITY_TOKEN")
    domain = os.environ.get("SALESFORCE_DOMAIN")

    if username and password and security_token:
        return Salesforce(
            username=username,
            password=password,
            security_token=security_token,
            domain=domain or "login",
        )

    access_token = os.environ.get("SALESFORCE_ACCESS_TOKEN")
    instance_url = os.environ.get("SALESFORCE_INSTANCE_URL")

    if access_token and instance_url:
        return Salesforce(instance_url=instance_url, session_id=access_token)

    raise ValueError(
        "Missing Salesforce credentials. Set either:\n"
        "  1) SALESFORCE_USERNAME + SALESFORCE_PASSWORD + SALESFORCE_SECURITY_TOKEN, or\n"
        "  2) SALESFORCE_ACCESS_TOKEN + SALESFORCE_INSTANCE_URL"
    )

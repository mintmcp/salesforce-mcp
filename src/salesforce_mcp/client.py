"""Salesforce client wrapper with lazy connection, validation, and caching."""

import re

from simple_salesforce import Salesforce
from simple_salesforce.api import SFType

from salesforce_mcp.auth import create_salesforce_client

_OBJECT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class SalesforceClient:
    def __init__(self) -> None:
        self._sf: Salesforce | None = None
        self._field_cache: dict[str, list[dict]] = {}

    @property
    def sf(self) -> Salesforce:
        """Lazy Salesforce connection — connects on first access."""
        if self._sf is None:
            self._sf = create_salesforce_client()
        return self._sf

    def get_sf_object(self, object_name: str) -> SFType:
        """Get a Salesforce object by name with validation."""
        if not _OBJECT_NAME_RE.match(object_name):
            raise ValueError(f"Invalid Salesforce object name: {object_name!r}")
        obj = getattr(self.sf, object_name)
        if not isinstance(obj, SFType):
            raise ValueError(f"Not a valid Salesforce object: {object_name!r}")
        return obj

    def get_object_fields(self, object_name: str) -> list[dict]:
        """Get field metadata for an object (cached)."""
        if object_name not in self._field_cache:
            sf_object = self.get_sf_object(object_name)
            desc = sf_object.describe()
            self._field_cache[object_name] = desc["fields"]
        return self._field_cache[object_name]


# Module-level singleton
client = SalesforceClient()

"""Salesforce client wrapper with lazy connection, validation, and caching."""

import re

from simple_salesforce import Salesforce
from simple_salesforce.api import SFType

from salesforce_mcp.auth import create_salesforce_client

_OBJECT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class SalesforceClient:
    def __init__(self) -> None:
        self._sf: Salesforce | None = None
        self._describe_cache: dict[str, dict] = {}

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

    def list_objects(self, search: str | None = None) -> list[dict]:
        """List all SObjects in the org, optionally filtered by substring."""
        result = self.sf.describe()
        sobjects = []
        for obj in result["sobjects"]:
            entry = {
                "name": obj["name"],
                "label": obj["label"],
                "queryable": obj["queryable"],
                "createable": obj["createable"],
                "custom": obj["custom"],
            }
            if search:
                search_lower = search.lower()
                if (
                    search_lower not in entry["name"].lower()
                    and search_lower not in entry["label"].lower()
                ):
                    continue
            sobjects.append(entry)
        return sobjects

    def describe_object(self, object_name: str) -> dict:
        """Get full describe metadata for an object (cached)."""
        if object_name not in self._describe_cache:
            sf_object = self.get_sf_object(object_name)
            desc = sf_object.describe()
            self._describe_cache[object_name] = {
                "fields": desc["fields"],
                "childRelationships": desc.get("childRelationships", []),
                "recordTypeInfos": desc.get("recordTypeInfos", []),
            }
        return self._describe_cache[object_name]


# Module-level singleton
client = SalesforceClient()

"""Salesforce MCP server — tool definitions."""

import functools
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from simple_salesforce.exceptions import SalesforceError

from salesforce_mcp.client import client

mcp = FastMCP("Salesforce")

# --- Access mode ---

_ACCESS_MODE = os.environ.get("SALESFORCE_ACCESS_MODE", "all").lower()
if _ACCESS_MODE not in ("read", "read_write", "all"):
    raise ValueError(
        f"Invalid SALESFORCE_ACCESS_MODE: {_ACCESS_MODE!r}. "
        "Must be 'read', 'read_write', or 'all'."
    )

_WRITE_ENABLED = _ACCESS_MODE in ("read_write", "all")
_ALL_ENABLED = _ACCESS_MODE == "all"


def _sf_error_handler(fn):
    """Convert Salesforce/validation errors to user-friendly messages."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as e:
            raise ValueError(str(e)) from e
        except SalesforceError as e:
            raise ValueError(f"Salesforce API error: {e}") from e

    return wrapper


# --- Read tools (always available) ---


@mcp.tool(
    annotations={
        "readOnlyHint": True,
    }
)
@_sf_error_handler
def list_objects(search: str | None = None) -> list[dict]:
    """List all Salesforce objects in this org. Use this as the first step when exploring
    an unfamiliar org or when you need to find a custom object.

    Returns: name (API name), label (display name), queryable, createable, custom.
    Use the optional search parameter to filter by name/label substring.
    Standard objects: Account, Contact, Lead, Opportunity, Case, Task, Event, User.
    Custom objects end in __c (e.g., Invoice__c).
    Follow up with describe_object to see fields for any object."""
    return client.list_objects(search)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
    }
)
@_sf_error_handler
def describe_object(object_name: str) -> dict:
    """Get complete metadata for a Salesforce object: fields, relationships, picklist values,
    and record types. Call this before querying or writing to an unfamiliar object.

    Each field includes: name (API name), label, type, referenceTo (for lookups),
    picklistValues (for picklists), nillable, createable, updateable.

    Common types: string, picklist, reference (lookup/master-detail), boolean, date,
    datetime, currency, double, int, id, textarea, phone, email, url.

    Standard objects: Account, Contact, Lead, Opportunity, Case, Task, Event, User.
    Custom objects and fields end in __c."""
    return client.describe_object(object_name)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
    }
)
@_sf_error_handler
def run_soql_query(query: str) -> dict:
    """Execute a SOQL query. SOQL syntax: SELECT fields FROM Object WHERE conditions ORDER BY field LIMIT n

    Use SOQL when you know which object to query. Use run_sosl_search instead when
    searching by keyword across multiple objects.

    Common objects: Account, Contact, Lead, Opportunity, Case, Task, Event, User.
    Custom objects end in __c. Custom fields end in __c.

    Relationship queries use dot notation for parent (SELECT Contact.Account.Name FROM Contact)
    and subqueries for children (SELECT Name, (SELECT LastName FROM Contacts) FROM Account).

    Always include LIMIT to avoid large result sets. Call describe_object first if you
    don't know the available fields. Results include totalSize, done, and records array."""
    return client.sf.query(query)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
    }
)
@_sf_error_handler
def run_sosl_search(search: str) -> dict:
    """Search across multiple Salesforce objects by keyword using full-text search.

    Syntax: FIND {search_term} IN ALL FIELDS RETURNING Object1(fields), Object2(fields)

    Use SOSL when you don't know which object contains the data, or need to search
    across Account, Contact, Lead, Opportunity simultaneously.
    Use run_soql_query instead for structured filtering (date ranges, status, owner).

    Example: FIND {Acme} IN ALL FIELDS RETURNING Account(Id, Name), Contact(Id, Name, Email)
    Wildcards: * (multiple chars), ? (single char). Minimum 2 characters."""
    return client.sf.search(search)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
    }
)
@_sf_error_handler
def get_record(object_name: str, record_id: str) -> dict:
    """Get a single Salesforce record by its ID. Returns all readable fields.

    Record IDs are 15 or 18 character strings. The first 3 characters indicate the object
    type (001=Account, 003=Contact, 006=Opportunity, 00Q=Lead, 500=Case).

    Use run_soql_query or run_sosl_search to find record IDs if you only have a name or email."""
    sf_object = client.get_sf_object(object_name)
    return sf_object.get(record_id)


def _describe_report(report_id: str) -> dict:
    return client.sf.restful(f"analytics/reports/{report_id}/describe")


@mcp.tool(
    annotations={
        "readOnlyHint": True,
    }
)
@_sf_error_handler
def get_report_metadata(report_id: str) -> dict:
    """Get detailed metadata for a Salesforce report: structure, columns, filters,
    groupings, and report type. Use this to understand a report's shape before running
    it, analyzing its output, or mirroring its logic in a SOQL query.

    Report IDs are 15 or 18 character strings starting with 00O. Find report IDs by
    querying the Report object (SELECT Id, Name, DeveloperName, FolderName FROM Report)
    or via the restful tool at analytics/reports/.

    Returns three sections:
    - reportMetadata: the report definition — reportType, reportFormat (TABULAR,
      SUMMARY, MATRIX), detailColumns, aggregates, groupingsDown/Across,
      reportFilters, reportBooleanFilter, standardDateFilter, sortBy.
    - reportExtendedMetadata: display-friendly labels and data types for each
      column and grouping (maps API names → labels).
    - reportTypeMetadata: report-type-level info — joined objects, filter
      operator map, date filter durations, and a SLIM list of field categories
      as [{label, fieldCount}, ...]. The heavy per-field catalog is omitted
      here to keep the payload small; use get_report_type_fields to drill
      into one category at a time.

    To run the report and get data rows, use the restful tool:
    restful("analytics/reports/{id}", params={"includeDetails": "true"})."""
    describe = _describe_report(report_id)
    rtm = describe.get("reportTypeMetadata") or {}
    categories = rtm.get("categories") or []
    describe["reportTypeMetadata"] = {
        **rtm,
        "categories": [
            {"label": c.get("label"), "fieldCount": len(c.get("columns") or {})}
            for c in categories
        ],
    }
    return describe


@mcp.tool(
    annotations={
        "readOnlyHint": True,
    }
)
@_sf_error_handler
def get_report_type_fields(
    report_id: str, category: str | None = None
) -> dict:
    """Drill into the per-field catalog of a report's report type. Use this after
    get_report_metadata when you need to know what fields are AVAILABLE to add to
    a report (not what's already in it).

    - category=None (default): returns the list of categories with field counts.
      Same slim view as reportTypeMetadata.categories in get_report_metadata.
    - category="<label>": returns the full field dict for that one category,
      where each field has label, dataType, filterable, picklist values, etc.
      Pass the exact label (e.g. "Account: General", "Contact: General").

    Typical agent workflow: call without category to see available categories →
    call with the one you need → build/edit the report from those fields."""
    describe = _describe_report(report_id)
    categories = (describe.get("reportTypeMetadata") or {}).get("categories") or []
    if category is None:
        return {
            "categories": [
                {"label": c.get("label"), "fieldCount": len(c.get("columns") or {})}
                for c in categories
            ]
        }
    for c in categories:
        if c.get("label") == category:
            return c
    valid = [c.get("label") for c in categories]
    raise ValueError(
        f"Category not found: {category!r}. Valid categories: {valid}"
    )


# --- Write tools (read_write and all) ---

if _WRITE_ENABLED:

    @mcp.tool(
        annotations={
            "readOnlyHint": False,
        }
    )
    @_sf_error_handler
    def create_record(object_name: str, data: dict[str, Any]) -> dict:
        """Create a new Salesforce record. Provide the object name and a dict of field values.

        Call describe_object first to see required fields and valid picklist values.
        The data dict keys must be field API names (e.g., LastName, not "Last Name").
        Returns the new record's ID on success.

        Example: create_record("Contact", {"LastName": "Smith", "Email": "smith@example.com"})"""
        sf_object = client.get_sf_object(object_name)
        return sf_object.create(data)

    @mcp.tool(
        annotations={
            "readOnlyHint": False,
        }
    )
    @_sf_error_handler
    def update_record(
        object_name: str, record_id: str, data: dict[str, Any]
    ) -> dict:
        """Update fields on an existing Salesforce record. Only include fields you want to change.

        Example: update_record("Opportunity", "006...", {"StageName": "Closed Won", "CloseDate": "2026-03-15"})
        Returns HTTP 204 on success."""
        sf_object = client.get_sf_object(object_name)
        return sf_object.update(record_id, data)


# --- Destructive / advanced tools (all only) ---

if _ALL_ENABLED:

    @mcp.tool(
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
        }
    )
    @_sf_error_handler
    def delete_record(object_name: str, record_id: str) -> dict:
        """Permanently delete a Salesforce record. This cannot be undone via the API.
        Records go to the Recycle Bin and can be recovered by an admin within 15 days."""
        sf_object = client.get_sf_object(object_name)
        return sf_object.delete(record_id)

    @mcp.tool(
        annotations={
            "readOnlyHint": False,
            "openWorldHint": True,
        }
    )
    @_sf_error_handler
    def tooling_execute(
        action: str, method: str = "GET", data: dict[str, Any] | None = None
    ) -> Any:
        """Execute a Salesforce Tooling API call. The Tooling API accesses metadata and
        developer objects: ApexClass, ApexTrigger, CustomField, Flow, ValidationRule.

        Example: tooling_execute("query/?q=SELECT Id,Name FROM ApexClass LIMIT 5")
        Example: tooling_execute("query/?q=SELECT Id,TableEnumOrId FROM CustomField WHERE TableEnumOrId='Account'")

        Use run_soql_query for regular data queries. Use this for metadata inspection."""
        return client.sf.toolingexecute(action, method=method, data=data or {})

    @mcp.tool(
        annotations={
            "readOnlyHint": False,
            "openWorldHint": True,
        }
    )
    @_sf_error_handler
    def apex_execute(
        action: str, method: str = "GET", data: dict[str, Any] | None = None
    ) -> Any:
        """Call a custom Apex REST endpoint. These are org-specific REST services written
        in Apex by developers. The action is the URL path after /services/apexrest/.

        This will return an error if no custom Apex REST endpoints exist in the org."""
        return client.sf.apexecute(action, method=method, data=data or {})

    @mcp.tool(
        annotations={
            "readOnlyHint": False,
            "openWorldHint": True,
        }
    )
    @_sf_error_handler
    def restful(
        path: str,
        method: str = "GET",
        params: dict[str, str] | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a raw Salesforce REST API call. This is an escape hatch for API endpoints
        not covered by other tools.

        Common paths:
        - sobjects/ — list all objects
        - sobjects/Account/describe/ — describe an object
        - analytics/reports/ — list reports
        - analytics/reports/{id} — run a report
        - limits/ — API usage limits
        - tooling/query/?q=SOQL — query metadata

        The path is relative to /services/data/vXX.0/. Method defaults to GET."""
        kwargs: dict[str, Any] = {"method": method}
        if params:
            kwargs["params"] = params
        if data:
            kwargs["data"] = data
        return client.sf.restful(path, **kwargs)

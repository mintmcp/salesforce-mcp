"""Salesforce MCP server — tool definitions."""

import functools
from typing import Any

from mcp.server.fastmcp import FastMCP
from simple_salesforce.exceptions import SalesforceError

from salesforce_mcp.client import client

mcp = FastMCP("Salesforce")


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


# --- Query tools ---


@mcp.tool()
@_sf_error_handler
def run_soql_query(query: str) -> dict:
    """Execute a SOQL query and return results."""
    result = client.sf.query(query)
    return result


@mcp.tool()
@_sf_error_handler
def run_sosl_search(search: str) -> dict:
    """Execute a SOSL search and return results."""
    result = client.sf.search(search)
    return result


# --- Object metadata ---


@mcp.tool()
@_sf_error_handler
def get_object_fields(object_name: str) -> list[dict]:
    """Get field metadata for a Salesforce object (cached)."""
    return client.get_object_fields(object_name)


# --- CRUD operations ---


@mcp.tool()
@_sf_error_handler
def get_record(object_name: str, record_id: str) -> dict:
    """Get a Salesforce record by ID."""
    sf_object = client.get_sf_object(object_name)
    return sf_object.get(record_id)


@mcp.tool()
@_sf_error_handler
def create_record(object_name: str, data: dict[str, Any]) -> dict:
    """Create a new Salesforce record."""
    sf_object = client.get_sf_object(object_name)
    return sf_object.create(data)


@mcp.tool()
@_sf_error_handler
def update_record(object_name: str, record_id: str, data: dict[str, Any]) -> dict:
    """Update an existing Salesforce record."""
    sf_object = client.get_sf_object(object_name)
    return sf_object.update(record_id, data)


@mcp.tool()
@_sf_error_handler
def delete_record(object_name: str, record_id: str) -> dict:
    """Delete a Salesforce record by ID."""
    sf_object = client.get_sf_object(object_name)
    return sf_object.delete(record_id)


# --- Advanced API tools ---


@mcp.tool()
@_sf_error_handler
def tooling_execute(
    action: str, method: str = "GET", data: dict[str, Any] | None = None
) -> Any:
    """Execute a Salesforce Tooling API call."""
    return client.sf.toolingexecute(action, method=method, data=data or {})


@mcp.tool()
@_sf_error_handler
def apex_execute(
    action: str, method: str = "GET", data: dict[str, Any] | None = None
) -> Any:
    """Execute a Salesforce Apex REST API call."""
    return client.sf.apexecute(action, method=method, data=data or {})


@mcp.tool()
@_sf_error_handler
def restful(
    path: str,
    method: str = "GET",
    params: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
) -> Any:
    """Execute a generic Salesforce REST API call."""
    kwargs: dict[str, Any] = {"method": method}
    if params:
        kwargs["params"] = params
    if data:
        kwargs["data"] = data
    return client.sf.restful(path, **kwargs)

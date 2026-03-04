# Salesforce MCP Server

## Setup

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e .
```

## Configuration

Set environment variables for authentication:

**Username/Password (default):**
```
SALESFORCE_USERNAME=your-username
SALESFORCE_PASSWORD=your-password
SALESFORCE_SECURITY_TOKEN=your-token
SALESFORCE_DOMAIN=login          # or "test" for sandbox
```

**OAuth (alternative):**
```
SALESFORCE_ACCESS_TOKEN=your-token
SALESFORCE_INSTANCE_URL=https://your-instance.salesforce.com
```

## Run

```bash
.venv/bin/python -m salesforce_mcp
```

## Tools

| Tool | Description |
|---|---|
| `run_soql_query` | Execute a SOQL query |
| `run_sosl_search` | Execute a SOSL search |
| `get_object_fields` | Get field metadata for an object |
| `get_record` | Get a record by ID |
| `create_record` | Create a new record |
| `update_record` | Update an existing record |
| `delete_record` | Delete a record |
| `tooling_execute` | Tooling API call |
| `apex_execute` | Apex REST API call |
| `restful` | Generic REST API call |

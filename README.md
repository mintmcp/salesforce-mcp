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

> **Note:** SOAP API login is disabled by default in newer Salesforce orgs. To enable it:
> 1. Go to **Setup** → Quick Find → **User Interface**
> 2. Under **API Settings**, enable **Enable SOAP API login()**
> 3. Click **Save**

**OAuth (alternative, recommended for enterprise):**
```
SALESFORCE_ACCESS_TOKEN=your-token
SALESFORCE_INSTANCE_URL=https://your-instance.salesforce.com
```

## Access Mode

Control which tools are available by setting `SALESFORCE_ACCESS_MODE`:

| Value | Tools Available | Use Case |
|---|---|---|
| `read` | list_objects, describe_object, run_soql_query, run_sosl_search, get_record | Safe exploration, reporting, read-only integrations |
| `read_write` (default) | All read tools + create_record, update_record | Day-to-day CRM operations |
| `all` | All tools including delete_record, tooling_execute, apex_execute, restful | Admin, development, full API access |

### Recommended Security Levels

| Environment | Recommended Mode | Rationale |
|---|---|---|
| Production (end users) | `read` | Prevents accidental data modification |
| Production (trusted ops) | `read_write` | Allows CRM data entry, blocks deletes and raw API |
| Sandbox / Development | `all` | Full access for testing and development |
| Demo / Exploration | `read` | Safe for exploring org structure and data |

Set it in your environment or MCP server config:
```
SALESFORCE_ACCESS_MODE=read
```

> **Tip:** When using this server with [MintMCP](https://mintmcp.com), you can configure fine-grained per-tool permissions directly in MintMCP instead of using the env var. This gives you more granular control (e.g., allow create but not update) without needing to restart the server.

### Tool Permissions by Access Mode

MCP tool annotations (`readOnlyHint`, `destructiveHint`) are set on each tool so MCP clients can enforce additional policies:

| Tool | Access Mode | readOnlyHint | destructiveHint |
|---|---|---|---|
| `list_objects` | read | true | — |
| `describe_object` | read | true | — |
| `run_soql_query` | read | true | — |
| `run_sosl_search` | read | true | — |
| `get_record` | read | true | — |
| `create_record` | read_write | false | — |
| `update_record` | read_write | false | — |
| `delete_record` | all | false | true |
| `tooling_execute` | all | false | — |
| `apex_execute` | all | false | — |
| `restful` | all | false | — |

## Run

```bash
.venv/bin/python -m salesforce_mcp
```

## Tools

| Tool | Description |
|---|---|
| `list_objects` | List all Salesforce objects in the org (with optional search filter) |
| `describe_object` | Get fields, relationships, picklist values, and record types for an object |
| `run_soql_query` | Execute a SOQL query |
| `run_sosl_search` | Cross-object full-text search via SOSL |
| `get_record` | Get a single record by ID |
| `create_record` | Create a new record |
| `update_record` | Update fields on an existing record |
| `delete_record` | Permanently delete a record |
| `tooling_execute` | Salesforce Tooling API (metadata, Apex classes, custom fields) |
| `apex_execute` | Call custom Apex REST endpoints |
| `restful` | Generic Salesforce REST API call |

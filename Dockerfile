FROM nikolaik/python-nodejs:python3.12-nodejs22-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m venv /app/.venv \
 && /app/.venv/bin/pip install --no-cache-dir . \
 && ln -s /app/.venv/bin/salesforce-mcp /usr/local/bin/salesforce-mcp
ENV PATH="/app/.venv/bin:$PATH"

# Salesforce credentials are supplied per-user by the MintMCP runtime: as request
# headers on an HTTP connector, as process env on a stdio connector.
ENV SALESFORCE_ACCESS_MODE=all

EXPOSE 8000

# HTTP connectors run this CMD. Stdio connectors set their command to the bare
# binary, which keeps the stdio default.
CMD ["/app/.venv/bin/salesforce-mcp", "--transport", "streamable-http"]

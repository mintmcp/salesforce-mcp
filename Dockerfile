FROM nikolaik/python-nodejs:python3.12-nodejs22-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
# The registry entry launches /app/.venv/bin/salesforce-mcp, so the install
# must land in that venv — not in the system site-packages.
RUN python -m venv /app/.venv && /app/.venv/bin/pip install --no-cache-dir .

# Salesforce credentials are supplied per-user by the MintMCP runtime (stdio
# connector: injected as process env). Placeholders keep them unset at build time.
ENV SALESFORCE_ACCESS_MODE=all

EXPOSE 8000

CMD ["/app/.venv/bin/salesforce-mcp"]

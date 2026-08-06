FROM nikolaik/python-nodejs:python3.12-nodejs22-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
# A connector's saved startup-command is not re-derived when the image changes, and
# the runtime spawns the child with a default PATH that ignores ENV PATH, so the
# script has to resolve at the venv path and on the default PATH.
RUN python -m venv /app/.venv \
    && /app/.venv/bin/pip install --no-cache-dir . \
    && ln -s /app/.venv/bin/salesforce-mcp /usr/local/bin/salesforce-mcp
ENV PATH="/app/.venv/bin:$PATH"

# Salesforce credentials are supplied per-user by the MintMCP runtime (stdio
# connector: injected as process env). Placeholders keep them unset at build time.
ENV SALESFORCE_ACCESS_MODE=all

EXPOSE 8000

CMD ["/app/.venv/bin/salesforce-mcp"]

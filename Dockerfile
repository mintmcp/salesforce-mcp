FROM nikolaik/python-nodejs:python3.12-nodejs22-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
# A connector's saved startup-command is not re-derived when the image changes, so
# install into the venv path AND put it on PATH — both invocations must resolve.
RUN python -m venv /app/.venv && /app/.venv/bin/pip install --no-cache-dir .
ENV PATH="/app/.venv/bin:$PATH"

# Salesforce credentials are supplied per-user by the MintMCP runtime (stdio
# connector: injected as process env). Placeholders keep them unset at build time.
ENV SALESFORCE_ACCESS_MODE=all

EXPOSE 8000

CMD ["/app/.venv/bin/salesforce-mcp"]

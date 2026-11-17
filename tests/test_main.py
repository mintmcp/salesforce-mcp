"""Tests for the CLI entry point's transport selection."""

import pytest

from salesforce_mcp import __main__ as entry


@pytest.mark.parametrize(
    ("argv", "transport"),
    [(["salesforce-mcp"], "stdio"), (["salesforce-mcp", "--transport", "streamable-http"], "streamable-http")],
)
def test_main_selects_the_transport(monkeypatch, argv, transport):
    calls = []
    monkeypatch.setattr(entry.mcp, "run", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr("sys.argv", argv)

    entry.main()

    assert calls == [{"transport": transport}]

"""Entry point: python -m salesforce_mcp"""

import argparse

from salesforce_mcp.server import mcp


def main():
    parser = argparse.ArgumentParser(prog="salesforce-mcp")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="stdio (default) or streamable HTTP at /mcp on $PORT (default 8000)",
    )
    mcp.run(transport=parser.parse_args().transport)


if __name__ == "__main__":
    main()

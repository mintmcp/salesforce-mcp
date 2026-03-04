"""Entry point: python -m salesforce_mcp"""

from salesforce_mcp.server import mcp


def main():
    mcp.run()


if __name__ == "__main__":
    main()

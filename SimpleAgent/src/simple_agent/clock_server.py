"""MCP server exposing the host system's current date and time."""

from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("SimpleAgent System Clock")


@mcp.tool()
def get_system_datetime() -> dict[str, str]:
    """Get the MCP server's current local and UTC date and time.

    The local timezone name and its UTC offset are included in the result.
    """
    utc_now = datetime.now(timezone.utc).replace(microsecond=0)
    local_now = utc_now.astimezone()
    offset = local_now.utcoffset()
    assert offset is not None
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    hours, remainder = divmod(abs(total_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    offset_text = f"{sign}{hours:02d}:{minutes:02d}"
    if seconds:
        offset_text += f":{seconds:02d}"

    return {
        "local_datetime": local_now.isoformat(timespec="seconds"),
        "utc_datetime": utc_now.isoformat(timespec="seconds"),
        "timezone_name": local_now.tzname() or "",
        "utc_offset": offset_text,
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

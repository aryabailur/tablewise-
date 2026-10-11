"""Ember & Vine MCP server (stdio). Exposes booking + knowledge tools to Claude Desktop / Claude Code.

Run:  python mcp_server.py   (from /backend, using the backend venv)
Reuses booking_service and rag directly - no HTTP hop. Never print to stdout (it carries the MCP protocol).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP  # noqa: E402
except ImportError:  # mcp 2.x renamed FastMCP -> MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP  # noqa: E402

from app import booking_service as bs  # noqa: E402
from app import rag  # noqa: E402
from app.db import init_db  # noqa: E402
from app.seed import seed_tables  # noqa: E402

init_db()
seed_tables()

mcp = FastMCP("ember-and-vine")


def _safe(fn, *args, **kwargs) -> dict[str, Any]:
    try:
        return fn(*args, **kwargs)
    except bs.BookingError as e:
        return {"error": e.message}


@mcp.tool()
def search_restaurant_info(query: str, k: int = 4) -> list[dict[str, Any]]:
    """Search Ember & Vine's knowledge base (menu, allergens, policies, hours, parking, events, FAQ).
    Returns the most relevant passages with their source file and section."""
    return rag.retrieve(query, k=max(1, min(k, 8)))


@mcp.tool()
def check_availability(date: str, party_size: int, time: Optional[str] = None, zone: Optional[str] = None) -> dict:
    """Check free tables. date: YYYY-MM-DD; party_size 1-12; time: optional HH:MM (24h);
    zone: optional window|garden|bar|private. Seatings every 30 min, 17:00-22:00."""
    r = _safe(bs.check_availability, date, party_size, time, zone)
    if "error" in r:
        return r
    out = {"date": r["date"], "party_size": r["party_size"], "zone": r["zone"],
           "available_times": [s["time"] for s in r["slots"] if s["available"]]}
    for k in ("requested_time", "requested_available", "nearest_alternatives", "suggested_table"):
        if k in r:
            out[k] = r[k]
    return out


@mcp.tool()
def create_booking(guest_name: str, party_size: int, date: str, time: str, phone: Optional[str] = None,
                   email: Optional[str] = None, zone: Optional[str] = None, notes: Optional[str] = None) -> dict:
    """Create a reservation (confirm details with the guest first). date YYYY-MM-DD, time HH:MM (24h).
    Returns the booking including its code (EV-XXXX)."""
    try:
        start = bs.combine(date, time)
    except bs.BookingError as e:
        return {"error": e.message}
    return _safe(bs.create_booking, guest_name=guest_name, party_size=party_size, start_time=start,
                 phone=phone, email=email, zone=zone, notes=notes)


@mcp.tool()
def get_booking(code: str) -> dict:
    """Look up a booking by its code (EV-XXXX)."""
    return _safe(bs.get_booking, code)


@mcp.tool()
def modify_booking(code: str, date: Optional[str] = None, time: Optional[str] = None,
                   party_size: Optional[int] = None, zone: Optional[str] = None, notes: Optional[str] = None) -> dict:
    """Modify a booking. Omitted fields keep their current values. date YYYY-MM-DD, time HH:MM (24h)."""
    start = None
    if date or time:
        current = _safe(bs.get_booking, code)
        if "error" in current:
            return current
        d, t = current["start_time"].split("T")
        try:
            start = bs.combine(date or d, time or t[:5])
        except bs.BookingError as e:
            return {"error": e.message}
    return _safe(bs.modify_booking, code, start_time=start, party_size=party_size, zone=zone, notes=notes)


@mcp.tool()
def cancel_booking(code: str) -> dict:
    """Cancel a booking by its code (EV-XXXX)."""
    return _safe(bs.cancel_booking, code)


if __name__ == "__main__":
    mcp.run()  # stdio transport

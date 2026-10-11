"""Tablewise MCP server (stdio). Exposes restaurant search, booking and knowledge tools to Claude Desktop / Code.

Run:  python mcp_server.py   (from /backend, using the backend venv)
Reuses booking_service and rag directly - no HTTP hop. Never print to stdout (it carries the MCP protocol).
Bookings made here are recorded with source="mcp".
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP
except ImportError:  # mcp 2.x renamed FastMCP -> MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP

from app import booking_service as bs
from app import rag
from app.seed import ensure_seeded

ensure_seeded()

mcp = FastMCP("tablewise")
DEFAULT = bs.DEFAULT_RESTAURANT


def _safe(fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except bs.BookingError as e:
        return {"error": e.message}


@mcp.tool()
def search_restaurants(cuisine: str | None = None, area: str | None = None, price_level: int | None = None,
                       tags: list[str] | None = None, party_size: int | None = None, date: str | None = None,
                       time: str | None = None) -> Any:
    """Find Tablewise restaurants in Mumbai with their next 3 open slots. All filters optional:
    cuisine (Italian, Japanese, Seafood, North Indian, Thali...), area (Lower Parel, Bandra, Powai, Juhu, Colaba,
    Andheri), price_level 1-4, tags (rooftop, bar, live-music, pet-friendly, pure-veg), party_size,
    date YYYY-MM-DD (default today), time HH:MM (default now)."""
    return _safe(bs.search_restaurants, cuisine=cuisine, area=area, price_level=price_level, tags=tags,
                 party_size=party_size, date=date, time=time)


@mcp.tool()
def search_restaurant_info(query: str, k: int = 4, restaurant_slug: str | None = None) -> list[dict[str, Any]]:
    """Search the restaurants' knowledge base (about, menu, allergens, policies) plus the Tablewise FAQ.
    restaurant_slug (e.g. ember-vine, trattoria-alba) restricts the search to one restaurant."""
    return rag.retrieve(query, k=max(1, min(k, 8)), restaurant_slug=restaurant_slug)


@mcp.tool()
def check_availability(date: str, party_size: int, time: str | None = None, zone: str | None = None,
                       restaurant_slug: str = DEFAULT) -> dict:
    """Check free tables at a restaurant. date: YYYY-MM-DD; party_size 1-12; time: optional HH:MM (24h);
    zone: optional window|garden|bar|private|rooftop|patio. restaurant_slug defaults to ember-vine."""
    r = _safe(bs.check_availability, restaurant_slug, date, party_size, time, zone)
    if "error" in r:
        return r
    out = {"restaurant_slug": r["restaurant_slug"], "date": r["date"], "party_size": r["party_size"],
           "zone": r["zone"], "available_times": [s["time"] for s in r["slots"] if s["available"]]}
    for k in ("requested_time", "requested_available", "nearest_alternatives", "suggested_table"):
        if k in r:
            out[k] = r[k]
    return out


@mcp.tool()
def create_booking(guest_name: str, party_size: int, date: str, time: str, phone: str | None = None,
                   email: str | None = None, zone: str | None = None, notes: str | None = None,
                   restaurant_slug: str = DEFAULT) -> dict:
    """Create a reservation (confirm details with the guest first). date YYYY-MM-DD, time HH:MM (24h).
    Returns the booking including its code (e.g. EMB-7K2P). restaurant_slug defaults to ember-vine."""
    try:
        start = bs.combine(date, time)
    except bs.BookingError as e:
        return {"error": e.message}
    return _safe(bs.create_booking, restaurant_slug, guest_name=guest_name, party_size=party_size, start_time=start,
                 phone=phone, email=email, zone=zone, notes=notes, source="mcp")


@mcp.tool()
def get_booking(code: str, restaurant_slug: str | None = None) -> dict:
    """Look up a booking by its code (e.g. EMB-7K2P). restaurant_slug is optional (codes are globally unique)."""
    return _safe(bs.get_booking, code, restaurant_slug)


@mcp.tool()
def modify_booking(code: str, date: str | None = None, time: str | None = None, party_size: int | None = None,
                   zone: str | None = None, notes: str | None = None, restaurant_slug: str | None = None) -> dict:
    """Modify a booking. Omitted fields keep their current values. date YYYY-MM-DD, time HH:MM (24h)."""
    start = None
    if date or time:
        current = _safe(bs.get_booking, code, restaurant_slug)
        if "error" in current:
            return current
        d, t = current["start_time"].split("T")
        try:
            start = bs.combine(date or d, time or t[:5])
        except bs.BookingError as e:
            return {"error": e.message}
    return _safe(bs.modify_booking, code, start_time=start, party_size=party_size, zone=zone, notes=notes,
                 restaurant_slug=restaurant_slug)


@mcp.tool()
def cancel_booking(code: str, restaurant_slug: str | None = None) -> dict:
    """Cancel a booking by its code (e.g. EMB-7K2P)."""
    return _safe(bs.cancel_booking, code, restaurant_slug)


if __name__ == "__main__":
    mcp.run()  # stdio transport

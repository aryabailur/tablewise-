"""Pure booking logic shared by the REST API, the LangGraph tools and the MCP server.

Every restaurant-scoped function takes a restaurant_slug. Booking codes (e.g. EMB-7K2P) are globally unique, so
code-based functions accept an optional restaurant_slug that, when given, must match the booking's restaurant.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import String, cast, func, or_
from sqlmodel import select

from . import metrics
from .db import Booking, Restaurant, Table, get_session

DEFAULT_RESTAURANT = "ember-vine"
SLOT_MINUTES = 30
DEFAULT_DURATION = 90
MAX_PARTY = 12
ZONES = ("window", "garden", "bar", "private", "rooftop", "patio")
SOURCES = ("web", "chat", "mcp", "google", "phone")
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_ZONE_ALIASES = {"counter": "bar", "pdr": "private", "private room": "private", "private dining": "private",
                 "terrace": "rooftop", "roof": "rooftop", "roof top": "rooftop", "outdoor": "patio",
                 "outside": "patio", "courtyard": "garden"}


class BookingError(Exception):
    """Raised for any business-rule violation; message is guest-safe."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------- parsing helpers

def parse_date(value: str | date) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError as exc:
        raise BookingError(f"Invalid date '{value}'. Use YYYY-MM-DD.") from exc


def parse_time(value: str) -> time:
    v = value.strip().lower().replace(".", "")
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M%p", "%I:%M %p", "%I%p", "%I %p", "%H"):
        try:
            return datetime.strptime(v, fmt).time()
        except ValueError:
            continue
    raise BookingError(f"Invalid time '{value}'. Use HH:MM (24h).")


def combine(d: str | date, t: str | time) -> datetime:
    dd = parse_date(d)
    tt = parse_time(t) if isinstance(t, str) else t
    return datetime.combine(dd, tt)


def parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "")).replace(tzinfo=None)
    except ValueError as exc:
        raise BookingError(f"Invalid datetime '{value}'. Use YYYY-MM-DDTHH:MM.") from exc


def normalize_zone(zone: str | None) -> str | None:
    if not zone:
        return None
    z = zone.strip().lower()
    if z in ("any", "none", "no preference", ""):
        return None
    z = _ZONE_ALIASES.get(z, z)
    if z not in ZONES:
        raise BookingError(f"Unknown zone '{zone}'. Choose one of: {', '.join(ZONES)}.")
    return z


def _hhmm(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


# ---------------------------------------------------------------- serialisers

def restaurant_to_dict(r: Restaurant) -> dict[str, Any]:
    return {"slug": r.slug, "name": r.name, "code_prefix": r.code_prefix, "cuisine": list(r.cuisine or []),
            "area": r.area, "price_level": r.price_level, "rating": r.rating, "avg_cost_for_two": r.avg_cost_for_two,
            "tags": list(r.tags or []), "hours_open": r.hours_open, "hours_close": r.hours_close,
            "slot_minutes": r.slot_minutes, "cover_image": r.cover_image, "description": r.description}


def table_to_dict(t: Table) -> dict[str, Any]:
    return {"id": t.id, "name": t.name, "capacity": t.capacity, "zone": t.zone, "is_active": t.is_active}


def _slim(t: Table) -> dict[str, Any]:
    return {"id": t.id, "name": t.name, "capacity": t.capacity, "zone": t.zone}


def booking_to_dict(b: Booking, table: Table | None = None, restaurant: Restaurant | None = None) -> dict[str, Any]:
    if table is None or restaurant is None:
        with get_session() as s:
            table = table or s.get(Table, b.table_id)
            restaurant = restaurant or s.get(Restaurant, b.restaurant_id)
    return {
        "id": b.id,
        "code": b.code,
        "restaurant_slug": restaurant.slug if restaurant else None,
        "restaurant_name": restaurant.name if restaurant else None,
        "guest_name": b.guest_name,
        "phone": b.phone,
        "email": b.email,
        "party_size": b.party_size,
        "start_time": b.start_time.isoformat(timespec="seconds"),
        "end_time": (b.start_time + timedelta(minutes=b.duration_min)).isoformat(timespec="seconds"),
        "duration_min": b.duration_min,
        "table_id": b.table_id,
        "table_name": table.name if table else None,
        "zone": table.zone if table else None,
        "status": b.status,
        "source": b.source,
        "notes": b.notes,
        "created_at": b.created_at.isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------- restaurant helpers

def _restaurant(session, slug: str | None) -> Restaurant:
    key = (slug or DEFAULT_RESTAURANT).strip().lower()
    r = session.exec(select(Restaurant).where(Restaurant.slug == key)).first()
    if not r:
        raise BookingError(f"Unknown restaurant '{key}'.", 404)
    return r


def last_seating(r: Restaurant, duration: int = DEFAULT_DURATION) -> time:
    close = datetime.combine(date.today(), _hhmm(r.hours_close))
    return (close - timedelta(minutes=duration)).time()


def service_slots(r: Restaurant, d: date) -> list[datetime]:
    slots, cur = [], datetime.combine(d, _hhmm(r.hours_open))
    last = datetime.combine(d, last_seating(r))
    while cur <= last:
        slots.append(cur)
        cur += timedelta(minutes=r.slot_minutes or SLOT_MINUTES)
    return slots


def _validate_slot(r: Restaurant, start: datetime, party_size: int) -> None:
    if party_size < 1:
        raise BookingError("Party size must be at least 1.")
    if party_size > MAX_PARTY:
        raise BookingError(f"Online bookings are limited to {MAX_PARTY} guests. For larger parties please call "
                           f"{r.name} directly to arrange a private buyout.")
    first, last = _hhmm(r.hours_open), last_seating(r)
    if start.time() < first or start.time() > last:
        raise BookingError(f"{r.name} seats guests between {first:%H:%M} and {last:%H:%M} (last seating). "
                           f"Service ends at {r.hours_close}.")
    step = r.slot_minutes or SLOT_MINUTES
    if (start.hour * 60 + start.minute - first.hour * 60 - first.minute) % step != 0 or start.second:
        raise BookingError(f"Bookings start every {step} minutes from {first:%H:%M} (e.g. 19:00 or 19:30).")
    if start < datetime.now() - timedelta(minutes=5):
        raise BookingError("That time is in the past.")
    if start.date() > date.today() + timedelta(days=60):
        raise BookingError("We take reservations up to 60 days in advance.")


def _check_zone(session, r: Restaurant, zone: str | None) -> str | None:
    z = normalize_zone(zone)
    if z:
        zones = sorted({t.zone for t in session.exec(select(Table).where(Table.restaurant_id == r.id)).all()})
        if z not in zones:
            raise BookingError(f"{r.name} has no {z} seating. Available zones: {', '.join(zones)}.")
    return z


def _overlaps(b: Booking, start: datetime, end: datetime) -> bool:
    b_end = b.start_time + timedelta(minutes=b.duration_min)
    return b.start_time < end and start < b_end


def _day_context(session, r: Restaurant, d: date) -> tuple[list[Table], list[Booking]]:
    """Active tables + confirmed bookings around a service day (one query each)."""
    tables = session.exec(select(Table).where(Table.restaurant_id == r.id, Table.is_active == True)).all()
    day_start = datetime.combine(d, time(0, 0))
    bookings = session.exec(
        select(Booking).where(Booking.restaurant_id == r.id, Booking.status == "confirmed",
                              Booking.start_time >= day_start - timedelta(hours=6),
                              Booking.start_time < day_start + timedelta(days=1, hours=6))
    ).all()
    return list(tables), list(bookings)


def _free(tables: list[Table], bookings: list[Booking], start: datetime, duration: int, party_size: int,
          zone: str | None = None, exclude_booking_id: int | None = None) -> list[Table]:
    end = start + timedelta(minutes=duration)
    busy = {b.table_id for b in bookings if b.id != exclude_booking_id and _overlaps(b, start, end)}
    free = [t for t in tables if t.capacity >= party_size and (not zone or t.zone == zone) and t.id not in busy]
    return sorted(free, key=lambda t: (t.capacity, t.id))  # smallest fitting table first


def _free_tables(session, r: Restaurant, start: datetime, duration: int, party_size: int,
                 zone: str | None = None, exclude_booking_id: int | None = None) -> list[Table]:
    tables, bookings = _day_context(session, r, start.date())
    return _free(tables, bookings, start, duration, party_size, zone, exclude_booking_id)


def _next_slots(session, r: Restaurant, d: date, after: time | None, party_size: int, n: int = 3) -> list[str]:
    if party_size > MAX_PARTY:
        return []
    now = datetime.now()
    floor = datetime.combine(d, after) if after else (now if d == now.date() else datetime.combine(d, time(0)))
    floor = max(floor, now)
    tables, bookings = _day_context(session, r, d)
    out = []
    for start in service_slots(r, d):
        if start < floor:
            continue
        if _free(tables, bookings, start, DEFAULT_DURATION, party_size):
            out.append(start.strftime("%H:%M"))
            if len(out) >= n:
                break
    return out


# ---------------------------------------------------------------- restaurants

def list_restaurants() -> list[dict[str, Any]]:
    with get_session() as s:
        return [restaurant_to_dict(r) for r in s.exec(select(Restaurant).order_by(Restaurant.id)).all()]


def restaurant_slugs() -> list[str]:
    with get_session() as s:
        return list(s.exec(select(Restaurant.slug).order_by(Restaurant.id)).all())


def get_restaurant(restaurant_slug: str) -> dict[str, Any]:
    with get_session() as s:
        return restaurant_to_dict(_restaurant(s, restaurant_slug))


def _json_text(col):
    return func.lower(cast(col, String))


def search_restaurants(q: str | None = None, cuisine: str | None = None, area: str | None = None,
                       price_level: int | None = None, tags: list[str] | str | None = None,
                       party_size: int | None = None, date: str | None = None,
                       time: str | None = None) -> list[dict[str, Any]]:
    """Filter restaurants in SQL and attach the next 3 free slots for the party on the date (default today)."""
    if isinstance(tags, str):
        tags = [t for t in (x.strip() for x in tags.split(",")) if t]
    d = parse_date(date) if date else datetime.now().date()
    after = parse_time(time) if time else None
    party = party_size or 2
    stmt = select(Restaurant)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Restaurant.name).like(like), func.lower(Restaurant.area).like(like),
                              func.lower(Restaurant.description).like(like), _json_text(Restaurant.cuisine).like(like),
                              _json_text(Restaurant.tags).like(like)))
    if cuisine and cuisine.strip():
        stmt = stmt.where(_json_text(Restaurant.cuisine).like(f"%{cuisine.strip().lower()}%"))
    if area and area.strip():
        stmt = stmt.where(func.lower(Restaurant.area).like(f"%{area.strip().lower()}%"))
    if price_level:
        stmt = stmt.where(Restaurant.price_level == price_level)
    for tag in tags or []:
        stmt = stmt.where(_json_text(Restaurant.tags).like(f'%"{tag.strip().lower()}"%'))
    with get_session() as s:
        rows = s.exec(stmt.order_by(Restaurant.rating.desc(), Restaurant.id)).all()
        return [restaurant_to_dict(r) | {"next_slots": _next_slots(s, r, d, after, party)} for r in rows]


# ---------------------------------------------------------------- tables & availability

def list_tables(restaurant_slug: str = DEFAULT_RESTAURANT) -> list[dict[str, Any]]:
    with get_session() as s:
        r = _restaurant(s, restaurant_slug)
        rows = s.exec(select(Table).where(Table.restaurant_id == r.id).order_by(Table.id)).all()
        return [table_to_dict(t) for t in rows]


def check_availability(restaurant_slug: str, day: str | date, party_size: int, time_str: str | None = None,
                       zone: str | None = None) -> dict[str, Any]:
    """Availability for a day. If time_str is given, also reports that exact slot + nearest alternatives."""
    d = parse_date(day)
    if party_size > MAX_PARTY:
        raise BookingError(f"Online bookings are limited to {MAX_PARTY} guests; please call the restaurant for "
                           "larger parties.")
    now = datetime.now()
    slots = []
    with get_session() as s:
        r = _restaurant(s, restaurant_slug)
        z = _check_zone(s, r, zone)
        tables, bookings = _day_context(s, r, d)
        for start in service_slots(r, d):
            free = [] if start < now else _free(tables, bookings, start, DEFAULT_DURATION, party_size, z)
            slots.append({
                "time": start.strftime("%H:%M"),
                "start": start.isoformat(timespec="seconds"),
                "available": bool(free),
                "available_tables": [_slim(t) for t in free],
                "best_table": _slim(free[0]) if free else None,
            })
        result: dict[str, Any] = {"date": d.isoformat(), "party_size": party_size, "restaurant_slug": r.slug,
                                  "restaurant_name": r.name, "zone": z, "slots": slots}
    if time_str:
        wanted = combine(d, time_str).strftime("%H:%M")
        match = next((sl for sl in slots if sl["time"] == wanted), None)
        result["requested_time"] = wanted
        result["requested_available"] = bool(match and match["available"])
        open_times = [sl["time"] for sl in slots if sl["available"]]
        wanted_min = int(wanted[:2]) * 60 + int(wanted[3:])
        result["nearest_alternatives"] = sorted(
            [t for t in open_times if t != wanted],
            key=lambda t: abs(int(t[:2]) * 60 + int(t[3:]) - wanted_min))[:4]
        if match and match["best_table"]:
            result["suggested_table"] = match["best_table"]
    return result


# ---------------------------------------------------------------- bookings

def _new_code(session, prefix: str) -> str:
    while True:
        code = f"{prefix}-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
        if not session.exec(select(Booking).where(Booking.code == code)).first():
            return code


def create_booking(restaurant_slug: str, guest_name: str, party_size: int, start_time: str | datetime,
                   phone: str | None = None, email: str | None = None, notes: str | None = None,
                   zone: str | None = None, table_id: int | None = None, duration_min: int = DEFAULT_DURATION,
                   source: str = "web") -> dict[str, Any]:
    if not guest_name or not guest_name.strip():
        raise BookingError("A guest name is required.")
    src = (source or "web").strip().lower()
    if src not in SOURCES:
        raise BookingError(f"Unknown source '{source}'. Use one of: {', '.join(SOURCES)}.")
    start = parse_datetime(start_time)
    with get_session() as s:
        r = _restaurant(s, restaurant_slug)
        _validate_slot(r, start, party_size)
        z = _check_zone(s, r, zone)
        free = _free_tables(s, r, start, duration_min, party_size, z)
        if table_id is not None:
            chosen = next((t for t in free if t.id == table_id), None)
            if not chosen:
                raise BookingError("That table isn't available for this time and party size.", 409)
        else:
            if not free:
                where = f" in the {z} zone" if z else ""
                raise BookingError(f"Sorry, {r.name} has no table for {party_size} free at {start:%H:%M} on "
                                   f"{start:%a %d %b}{where}.", 409)
            chosen = free[0]
        booking = Booking(code=_new_code(s, r.code_prefix), restaurant_id=r.id, guest_name=guest_name.strip(),
                          phone=phone or None, email=email or None, party_size=party_size, start_time=start,
                          duration_min=duration_min, table_id=chosen.id, notes=notes or None, source=src)
        s.add(booking)
        s.commit()
        s.refresh(booking)
        metrics.BOOKINGS_CREATED.labels(restaurant=r.slug, source=src).inc()
        return booking_to_dict(booking, chosen, r)


def _get(session, code: str, restaurant_slug: str | None = None) -> tuple[Booking, Restaurant]:
    key = code.strip().upper()
    b = session.exec(select(Booking).where(Booking.code == key)).first()
    r = session.get(Restaurant, b.restaurant_id) if b else None
    if not b or (restaurant_slug and r and r.slug != restaurant_slug.strip().lower()):
        raise BookingError(f"No booking found with code {key}.", 404)
    return b, r


def get_booking(code: str, restaurant_slug: str | None = None) -> dict[str, Any]:
    with get_session() as s:
        b, r = _get(s, code, restaurant_slug)
        return booking_to_dict(b, s.get(Table, b.table_id), r)


def modify_booking(code: str, start_time: str | datetime | None = None, party_size: int | None = None,
                   notes: str | None = None, guest_name: str | None = None, phone: str | None = None,
                   email: str | None = None, zone: str | None = None,
                   restaurant_slug: str | None = None) -> dict[str, Any]:
    with get_session() as s:
        b, r = _get(s, code, restaurant_slug)
        if b.status != "confirmed":
            raise BookingError(f"Booking {b.code} is cancelled and can't be modified.", 409)
        new_start = parse_datetime(start_time) if start_time else b.start_time
        new_party = party_size or b.party_size
        z = _check_zone(s, r, zone)
        if start_time or party_size or z:
            _validate_slot(r, new_start, new_party)
            free = _free_tables(s, r, new_start, b.duration_min, new_party, z, exclude_booking_id=b.id)
            if not free:
                raise BookingError(f"Sorry, nothing for {new_party} is free at {new_start:%H:%M} on "
                                   f"{new_start:%a %d %b}.", 409)
            current = next((t for t in free if t.id == b.table_id), None)
            b.table_id = (current or free[0]).id
            b.start_time, b.party_size = new_start, new_party
        if notes is not None:
            b.notes = notes
        if guest_name:
            b.guest_name = guest_name
        if phone:
            b.phone = phone
        if email:
            b.email = email
        s.add(b)
        s.commit()
        s.refresh(b)
        return booking_to_dict(b, s.get(Table, b.table_id), r)


def cancel_booking(code: str, restaurant_slug: str | None = None) -> dict[str, Any]:
    with get_session() as s:
        b, r = _get(s, code, restaurant_slug)
        if b.status == "cancelled":
            raise BookingError(f"Booking {b.code} is already cancelled.", 409)
        b.status = "cancelled"
        s.add(b)
        s.commit()
        s.refresh(b)
        metrics.BOOKINGS_CANCELLED.labels(restaurant=r.slug).inc()
        return booking_to_dict(b, s.get(Table, b.table_id), r)


def list_bookings(day: str | date | None = None, restaurant_slug: str | None = None) -> list[dict[str, Any]]:
    with get_session() as s:
        q = select(Booking)
        if restaurant_slug:
            q = q.where(Booking.restaurant_id == _restaurant(s, restaurant_slug).id)
        if day:
            d = parse_date(day)
            q = q.where(Booking.start_time >= datetime.combine(d, time(0)),
                        Booking.start_time < datetime.combine(d + timedelta(days=1), time(0)))
        tables = {t.id: t for t in s.exec(select(Table)).all()}
        restaurants = {r.id: r for r in s.exec(select(Restaurant)).all()}
        return [booking_to_dict(b, tables.get(b.table_id), restaurants.get(b.restaurant_id))
                for b in s.exec(q.order_by(Booking.start_time, Booking.id)).all()]

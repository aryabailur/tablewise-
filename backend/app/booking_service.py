"""Pure booking logic shared by the REST API, the LangGraph tools and the MCP server."""
from __future__ import annotations

import secrets
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlmodel import select

from .db import Booking, Table, get_session

OPEN_TIME = time(17, 0)
CLOSE_TIME = time(23, 0)
LAST_SEATING = time(22, 0)
SLOT_MINUTES = 30
DEFAULT_DURATION = 90
MAX_PARTY = 12
ZONES = ("window", "garden", "bar", "private")
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


class BookingError(Exception):
    """Raised for any business-rule violation; message is guest-safe."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------- helpers

def table_to_dict(t: Table) -> dict[str, Any]:
    return {"id": t.id, "name": t.name, "capacity": t.capacity, "zone": t.zone, "is_active": t.is_active}


def _slim(t: Table) -> dict[str, Any]:
    return {"id": t.id, "name": t.name, "capacity": t.capacity, "zone": t.zone}


def booking_to_dict(b: Booking, table: Table | None = None) -> dict[str, Any]:
    if table is None:
        with get_session() as s:
            table = s.get(Table, b.table_id)
    return {
        "id": b.id,
        "code": b.code,
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
        "notes": b.notes,
        "created_at": b.created_at.isoformat(timespec="seconds"),
    }


def parse_date(value: str | date) -> date:
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


def _normalize_zone(zone: str | None) -> str | None:
    if not zone:
        return None
    z = zone.strip().lower()
    if z in ("any", "none", "no preference", ""):
        return None
    aliases = {"patio": "garden", "terrace": "garden", "outside": "garden", "outdoor": "garden",
               "counter": "bar", "pdr": "private", "private room": "private", "private dining": "private"}
    z = aliases.get(z, z)
    if z not in ZONES:
        raise BookingError(f"Unknown zone '{zone}'. Choose one of: {', '.join(ZONES)}.")
    return z


def service_slots(d: date) -> list[datetime]:
    slots, cur = [], datetime.combine(d, OPEN_TIME)
    last = datetime.combine(d, LAST_SEATING)
    while cur <= last:
        slots.append(cur)
        cur += timedelta(minutes=SLOT_MINUTES)
    return slots


def _validate_slot(start: datetime, party_size: int) -> None:
    if party_size < 1:
        raise BookingError("Party size must be at least 1.")
    if party_size > MAX_PARTY:
        raise BookingError(
            f"Online bookings are limited to {MAX_PARTY} guests. For larger parties please contact our events team "
            "at events@emberandvine.com for a private buyout.")
    if start.time() < OPEN_TIME or start.time() > LAST_SEATING:
        raise BookingError("We seat guests between 17:00 and 22:00 (last seating). Service ends at 23:00.")
    if start.minute % SLOT_MINUTES != 0:
        raise BookingError("Bookings start on the hour or half hour (e.g. 19:00 or 19:30).")
    if start < datetime.now() - timedelta(minutes=5):
        raise BookingError("That time is in the past.")
    if start.date() > date.today() + timedelta(days=60):
        raise BookingError("We take reservations up to 60 days in advance.")


def _overlaps(b: Booking, start: datetime, end: datetime) -> bool:
    b_end = b.start_time + timedelta(minutes=b.duration_min)
    return b.start_time < end and start < b_end


def _free_tables(session, start: datetime, duration: int, party_size: int,
                 zone: str | None = None, exclude_booking_id: int | None = None) -> list[Table]:
    end = start + timedelta(minutes=duration)
    tables = session.exec(select(Table).where(Table.is_active == True, Table.capacity >= party_size)).all()
    if zone:
        tables = [t for t in tables if t.zone == zone]
    day_start = datetime.combine(start.date(), time(0, 0))
    bookings = session.exec(
        select(Booking).where(Booking.status == "confirmed", Booking.start_time >= day_start - timedelta(hours=6),
                              Booking.start_time < day_start + timedelta(days=1, hours=6))
    ).all()
    busy = {b.table_id for b in bookings if b.id != exclude_booking_id and _overlaps(b, start, end)}
    free = [t for t in tables if t.id not in busy]
    return sorted(free, key=lambda t: (t.capacity, t.id))  # smallest fitting table first


# ---------------------------------------------------------------- public API

def list_tables() -> list[dict[str, Any]]:
    with get_session() as s:
        return [table_to_dict(t) for t in s.exec(select(Table).order_by(Table.id)).all()]


def check_availability(day: str | date, party_size: int, time_str: str | None = None,
                       zone: str | None = None) -> dict[str, Any]:
    """Availability for a day. If time_str is given, also reports that exact slot + nearest alternatives."""
    d = parse_date(day)
    z = _normalize_zone(zone)
    if party_size > MAX_PARTY:
        raise BookingError(
            f"Online bookings are limited to {MAX_PARTY} guests; larger parties should contact events@emberandvine.com.")
    now = datetime.now()
    slots = []
    with get_session() as s:
        for start in service_slots(d):
            free = [] if start < now else _free_tables(s, start, DEFAULT_DURATION, party_size, z)
            slots.append({
                "time": start.strftime("%H:%M"),
                "start": start.isoformat(timespec="seconds"),
                "available": bool(free),
                "available_tables": [_slim(t) for t in free],
                "best_table": _slim(free[0]) if free else None,
            })
    result: dict[str, Any] = {"date": d.isoformat(), "party_size": party_size, "zone": z, "slots": slots}
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


def _new_code(session) -> str:
    while True:
        code = "EV-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
        if not session.exec(select(Booking).where(Booking.code == code)).first():
            return code


def create_booking(guest_name: str, party_size: int, start_time: str | datetime, phone: str | None = None,
                   email: str | None = None, notes: str | None = None, zone: str | None = None,
                   table_id: int | None = None, duration_min: int = DEFAULT_DURATION) -> dict[str, Any]:
    if not guest_name or not guest_name.strip():
        raise BookingError("A guest name is required.")
    start = parse_datetime(start_time)
    _validate_slot(start, party_size)
    z = _normalize_zone(zone)
    with get_session() as s:
        free = _free_tables(s, start, duration_min, party_size, z)
        if table_id is not None:
            chosen = next((t for t in free if t.id == table_id), None)
            if not chosen:
                raise BookingError("That table isn't available for this time and party size.", 409)
        else:
            if not free:
                where = f" in the {z} zone" if z else ""
                raise BookingError(f"Sorry, no table for {party_size} is free at {start:%H:%M} on {start:%a %d %b}{where}.", 409)
            chosen = free[0]
        booking = Booking(code=_new_code(s), guest_name=guest_name.strip(), phone=phone or None, email=email or None,
                          party_size=party_size, start_time=start, duration_min=duration_min, table_id=chosen.id,
                          notes=notes or None)
        s.add(booking)
        s.commit()
        s.refresh(booking)
        return booking_to_dict(booking, chosen)


def _get(session, code: str) -> Booking:
    b = session.exec(select(Booking).where(Booking.code == code.strip().upper())).first()
    if not b:
        raise BookingError(f"No booking found with code {code.strip().upper()}.", 404)
    return b


def get_booking(code: str) -> dict[str, Any]:
    with get_session() as s:
        b = _get(s, code)
        return booking_to_dict(b, s.get(Table, b.table_id))


def modify_booking(code: str, start_time: str | datetime | None = None, party_size: int | None = None,
                   notes: str | None = None, guest_name: str | None = None, phone: str | None = None,
                   email: str | None = None, zone: str | None = None) -> dict[str, Any]:
    with get_session() as s:
        b = _get(s, code)
        if b.status != "confirmed":
            raise BookingError(f"Booking {b.code} is cancelled and can't be modified.", 409)
        new_start = parse_datetime(start_time) if start_time else b.start_time
        new_party = party_size or b.party_size
        z = _normalize_zone(zone)
        if start_time or party_size or z:
            _validate_slot(new_start, new_party)
            free = _free_tables(s, new_start, b.duration_min, new_party, z, exclude_booking_id=b.id)
            if not free:
                raise BookingError(f"Sorry, nothing for {new_party} is free at {new_start:%H:%M} on {new_start:%a %d %b}.", 409)
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
        return booking_to_dict(b, s.get(Table, b.table_id))


def cancel_booking(code: str) -> dict[str, Any]:
    with get_session() as s:
        b = _get(s, code)
        if b.status == "cancelled":
            raise BookingError(f"Booking {b.code} is already cancelled.", 409)
        b.status = "cancelled"
        s.add(b)
        s.commit()
        s.refresh(b)
        return booking_to_dict(b, s.get(Table, b.table_id))


def list_bookings(day: str | date | None = None) -> list[dict[str, Any]]:
    with get_session() as s:
        q = select(Booking)
        if day:
            d = parse_date(day)
            q = q.where(Booking.start_time >= datetime.combine(d, time(0)),
                        Booking.start_time < datetime.combine(d + timedelta(days=1), time(0)))
        tables = {t.id: t for t in s.exec(select(Table)).all()}
        return [booking_to_dict(b, tables.get(b.table_id)) for b in s.exec(q.order_by(Booking.start_time)).all()]

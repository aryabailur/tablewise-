"""Seed 14 tables, a handful of demo bookings, and ingest the knowledge base.

Run: python -m app.seed  (from /backend)
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from sqlmodel import select

from . import booking_service, rag
from .db import Booking, Table, get_session, init_db

TABLES = [
    ("W1", 2, "window"), ("W2", 2, "window"), ("W3", 4, "window"), ("W4", 4, "window"),
    ("G1", 2, "garden"), ("G2", 4, "garden"), ("G3", 6, "garden"), ("G4", 8, "garden"),
    ("B1", 2, "bar"), ("B2", 2, "bar"), ("B3", 2, "bar"),
    ("P1", 6, "private"), ("P2", 10, "private"), ("P3", 12, "private"),
]

DEMO_GUESTS = ["Ana Ruiz", "Kenji Watanabe", "Priya Raman", "Luca Bianchi", "Amara Okafor", "Sofia Lindqvist",
               "Mateo Alvarez", "Hannah Cho", "Noah Fischer", "Leila Haddad", "Oliver Grant", "Zoe Marchetti"]


def seed_tables() -> int:
    with get_session() as s:
        if s.exec(select(Table)).first():
            return 0
        for name, cap, zone in TABLES:
            s.add(Table(name=name, capacity=cap, zone=zone))
        s.commit()
        return len(TABLES)


def seed_demo_bookings(reset: bool = False) -> int:
    """Sprinkle realistic bookings over today + the next 3 days so the UI has texture."""
    with get_session() as s:
        if reset:
            for b in s.exec(select(Booking)).all():
                s.delete(b)
            s.commit()
        elif s.exec(select(Booking)).first():
            return 0
    rng = random.Random(42)
    made = 0
    for offset in range(0, 4):
        d = date.today() + timedelta(days=offset)
        for _ in range(9 if offset else 6):
            start = datetime.combine(d, time(17, 0)) + timedelta(minutes=30 * rng.randint(2, 9))
            if start < datetime.now():
                continue
            try:
                booking_service.create_booking(
                    guest_name=rng.choice(DEMO_GUESTS), party_size=rng.choice([2, 2, 2, 3, 4, 4, 5, 6]),
                    start_time=start, phone=f"(415) 555-{rng.randint(1000, 9999)}",
                    notes=rng.choice([None, None, "Anniversary", "Window if possible", "Nut allergy", "Birthday"]))
                made += 1
            except booking_service.BookingError:
                continue
    return made


def main() -> None:
    init_db()
    print(f"tables seeded: {seed_tables()}")
    print(f"demo bookings: {seed_demo_bookings(reset=True)}")
    print("ingesting knowledge base (first run downloads the bge-small embedding model)...")
    print(f"chunks ingested: {rag.ingest()}")


if __name__ == "__main__":
    main()

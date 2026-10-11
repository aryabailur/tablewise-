"""Seed the 6 Mumbai restaurants, their tables, demo bookings, and ingest the knowledge base.

Run: python -m app.seed  (from /backend) for a full reset: drop_all + create_all + reseed.
On normal startup (ensure_seeded) an existing database is migrated in place instead (db.migrate_db); when that adds
the guest-detail columns, existing bookings are back-filled with demo allergies/dietary/occasion details.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from sqlmodel import select

from . import booking_service, rag
from .db import Booking, Restaurant, Table, get_session, init_db

RESTAURANTS: list[dict] = [
    {"slug": "ember-vine", "name": "Ember & Vine", "code_prefix": "EMB", "cuisine": ["Wood-fire", "Modern European"],
     "area": "Lower Parel", "price_level": 4, "avg_cost_for_two": 4200, "tags": ["bar", "live-music"],
     "hours_open": "18:00", "hours_close": "23:30", "rating": 4.6,
     "cover_image": "linear-gradient(135deg,#ff7a3d,#5a0f2e)",
     "description": "A wood-fire kitchen and natural wine bar in a restored mill compound. Everything passes "
                    "through the 4-metre hearth; live jazz Thursday to Saturday."},
    {"slug": "trattoria-alba", "name": "Trattoria Alba", "code_prefix": "ALB", "cuisine": ["Italian", "Pizza"],
     "area": "Bandra", "price_level": 3, "avg_cost_for_two": 2800, "tags": ["rooftop", "bar", "pet-friendly"],
     "hours_open": "12:00", "hours_close": "23:30", "rating": 4.5,
     "cover_image": "linear-gradient(135deg,#f6c453,#9b2c1f)",
     "description": "Hand-rolled pasta and Neapolitan pizza from a wood oven, with a breezy rooftop over "
                    "Bandra's Pali Hill and a spritz bar. Dogs welcome on the terrace."},
    {"slug": "saffron-terrace", "name": "Saffron Terrace", "code_prefix": "SAF",
     "cuisine": ["North Indian", "Mughlai"], "area": "Powai", "price_level": 3, "avg_cost_for_two": 2400,
     "tags": ["rooftop", "live-music"], "hours_open": "12:00", "hours_close": "23:00", "rating": 4.4,
     "cover_image": "linear-gradient(135deg,#ffb347,#7b1e3a)",
     "description": "Slow-cooked Mughlai classics, tandoor breads and dum biryani on a lakeside rooftop "
                    "terrace overlooking Powai, with ghazal nights on weekends."},
    {"slug": "koli-tide", "name": "Koli & Tide", "code_prefix": "KOL", "cuisine": ["Coastal", "Seafood", "Malvani"],
     "area": "Juhu", "price_level": 2, "avg_cost_for_two": 1800, "tags": ["pet-friendly", "bar"],
     "hours_open": "12:00", "hours_close": "23:30", "rating": 4.3,
     "cover_image": "linear-gradient(135deg,#2ec4b6,#0b3c5d)",
     "description": "Konkan and Koli coastal cooking a short walk from Juhu beach: the day's catch in Malvani "
                    "masala, sol kadhi and a breezy patio bar."},
    {"slug": "kanji-house", "name": "Kanji House", "code_prefix": "KNJ", "cuisine": ["Japanese", "Pan-Asian"],
     "area": "Colaba", "price_level": 4, "avg_cost_for_two": 4800, "tags": ["bar"],
     "hours_open": "19:00", "hours_close": "23:59", "rating": 4.7,
     "cover_image": "linear-gradient(135deg,#e63946,#1d1d2c)",
     "description": "An intimate Colaba izakaya and omakase counter: robata grill, hand rolls and a "
                    "Japanese whisky bar open till midnight."},
    {"slug": "tulsi-thali", "name": "Tulsi Thali House", "code_prefix": "TUL",
     "cuisine": ["Gujarati", "Rajasthani", "Thali"], "area": "Andheri", "price_level": 1, "avg_cost_for_two": 900,
     "tags": ["pure-veg"], "hours_open": "11:30", "hours_close": "22:30", "rating": 4.2,
     "cover_image": "linear-gradient(135deg,#a8e063,#3c6e2f)",
     "description": "Unlimited pure-vegetarian Gujarati and Rajasthani thalis served at your table, refilled "
                    "until you say stop. A family favourite in Andheri West."},
]

# (name, capacity, zone) per restaurant
TABLES: dict[str, list[tuple[str, int, str]]] = {
    "ember-vine": [("W1", 2, "window"), ("W2", 2, "window"), ("W3", 4, "window"), ("G1", 4, "garden"),
                   ("G2", 6, "garden"), ("B1", 2, "bar"), ("B2", 2, "bar"), ("B3", 2, "bar"),
                   ("P1", 6, "private"), ("P2", 10, "private"), ("P3", 12, "private")],
    "trattoria-alba": [("W1", 2, "window"), ("W2", 4, "window"), ("R1", 2, "rooftop"), ("R2", 4, "rooftop"),
                       ("R3", 4, "rooftop"), ("R4", 8, "rooftop"), ("B1", 2, "bar"), ("B2", 2, "bar"),
                       ("P1", 10, "private")],
    "saffron-terrace": [("R1", 2, "rooftop"), ("R2", 4, "rooftop"), ("R3", 6, "rooftop"), ("R4", 8, "rooftop"),
                        ("W1", 2, "window"), ("W2", 4, "window"), ("G1", 4, "garden"), ("P1", 12, "private")],
    "koli-tide": [("PT1", 2, "patio"), ("PT2", 4, "patio"), ("PT3", 6, "patio"), ("W1", 2, "window"),
                  ("W2", 4, "window"), ("B1", 2, "bar"), ("B2", 2, "bar"), ("P1", 10, "private")],
    "kanji-house": [("C1", 2, "bar"), ("C2", 2, "bar"), ("C3", 2, "bar"), ("W1", 2, "window"),
                    ("W2", 4, "window"), ("P1", 6, "private")],
    "tulsi-thali": [("W1", 2, "window"), ("W2", 4, "window"), ("W3", 4, "window"), ("G1", 4, "garden"),
                    ("G2", 6, "garden"), ("G3", 8, "garden"), ("P1", 12, "private")],
}

DEMO_GUESTS = ["Aarav Mehta", "Ananya Iyer", "Rohan Desai", "Priya Nair", "Kabir Malhotra", "Ishita Shah",
               "Vikram Rao", "Meera Kulkarni", "Arjun Kapoor", "Sana Sheikh", "Neha Joshi", "Dev Patel",
               "Zara Fernandes", "Aditya Menon", "Tara Banerjee", "Farhan Qureshi"]
SOURCES = ["web", "web", "web", "chat", "chat", "mcp", "google", "google", "phone"]
NOTES = [None, None, None, None, "Window if possible", "High chair please", "Running 10 minutes late is likely"]
# Guest details for ~40% of demo bookings: (allergies, dietary, occasion, special_requests)
GUEST_PROFILES: list[tuple[list[str], str, str, str | None]] = [
    (["nuts"], "none", "birthday", "Birthday cake with dessert, please - nut-free"),
    (["shellfish"], "none", "anniversary", "A quiet corner table if possible"),
    (["gluten"], "none", "business", None),
    ([], "vegan", "date", "Window seat if possible"),
    (["dairy", "eggs"], "veg", "none", None),
    ([], "jain", "none", "No onion, garlic or root vegetables"),
    (["peanuts", "sesame"], "none", "birthday", "Candle on the dessert"),
    ([], "halal", "business", "Need to leave by 9:30 pm"),
    (["fish"], "veg", "anniversary", "Rose petals on the table, please"),
    (["soy"], "none", "date", None),
    ([], "veg", "birthday", "Surprise for our daughter - please don't mention it on arrival"),
    (["dairy"], "none", "none", "Wheelchair access needed"),
]
DETAIL_RATE = 0.4
BOOKINGS_PER_RESTAURANT = 15


def seed_restaurants() -> int:
    with get_session() as s:
        if s.exec(select(Restaurant)).first():
            return 0
        for data in RESTAURANTS:
            s.add(Restaurant(slot_minutes=30, **data))
        s.commit()
        return len(RESTAURANTS)


def seed_tables() -> int:
    """Create restaurants (if missing) and their tables (if missing). Returns tables created."""
    seed_restaurants()
    made = 0
    with get_session() as s:
        for r in s.exec(select(Restaurant)).all():
            if s.exec(select(Table).where(Table.restaurant_id == r.id)).first():
                continue
            for name, cap, zone in TABLES.get(r.slug, []):
                s.add(Table(restaurant_id=r.id, name=name, capacity=cap, zone=zone))
                made += 1
        s.commit()
    return made


def _guest_details(rng: random.Random) -> dict:
    if rng.random() >= DETAIL_RATE:
        return {}
    allergies, dietary, occasion, special = rng.choice(GUEST_PROFILES)
    return {"allergies": list(allergies), "dietary": dietary, "occasion": occasion, "special_requests": special}


def backfill_guest_details(seed: int = 7) -> int:
    """Give ~40% of bookings that have no guest details yet some demo details (used right after migrating)."""
    rng, made = random.Random(seed), 0
    with get_session() as s:
        for b in s.exec(select(Booking).order_by(Booking.id)).all():
            if b.allergies or (b.dietary or "none") != "none" or (b.occasion or "none") != "none" or b.special_requests:
                continue
            details = _guest_details(rng)
            if details:
                for key, value in details.items():
                    setattr(b, key, value)
                s.add(b)
                made += 1
        s.commit()
    return made


def seed_demo_bookings(per_restaurant: int = BOOKINGS_PER_RESTAURANT, seed: int = 42) -> int:
    """Spread realistic bookings over today + the next 6 days so the UI and dashboards have texture."""
    rng = random.Random(seed)
    made = 0
    with get_session() as s:
        restaurants = s.exec(select(Restaurant).order_by(Restaurant.id)).all()
    for r in restaurants:
        count, attempts = 0, 0
        while count < per_restaurant and attempts < per_restaurant * 8:
            attempts += 1
            d = date.today() + timedelta(days=rng.randint(0, 6))
            slots = [sl for sl in booking_service.service_slots(r, d) if sl > datetime.now() + timedelta(minutes=10)]
            if not slots:
                continue
            evening = [sl for sl in slots if sl.hour >= 19] or slots  # bias towards dinner
            start = rng.choice(evening if rng.random() < 0.7 else slots)
            try:
                booking_service.create_booking(
                    r.slug, guest_name=rng.choice(DEMO_GUESTS), party_size=rng.choice([2, 2, 2, 3, 4, 4, 5, 6]),
                    start_time=start, phone=f"+91 98{rng.randint(10, 99)} {rng.randint(100000, 999999)}",
                    notes=rng.choice(NOTES), source=rng.choice(SOURCES), **_guest_details(rng))
                count += 1
            except booking_service.BookingError:
                continue
        made += count
    return made


def ensure_seeded() -> None:
    """Startup hook: create schema and seed when the database is empty (never wipes existing data)."""
    added = init_db()
    with get_session() as s:
        empty = s.exec(select(Restaurant)).first() is None
    seed_tables()
    if empty:
        seed_demo_bookings()
    elif "allergies" in added:  # v2 database just migrated in place: give existing demo bookings some texture
        backfill_guest_details()


def main() -> None:
    init_db(reset=True)  # migration: drop_all + create_all
    print(f"restaurants seeded: {seed_restaurants()}")
    print(f"tables seeded: {seed_tables()}")
    print(f"demo bookings: {seed_demo_bookings()}")
    print("ingesting knowledge base (first run downloads the bge-small embedding model)...")
    print(f"chunks ingested: {rag.ingest()}")


if __name__ == "__main__":
    main()

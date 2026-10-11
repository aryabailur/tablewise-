"""Fast smoke tests: booking logic on a throwaway SQLite DB and the RAG chunker. No LLM, no network."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from sqlmodel import SQLModel, create_engine

from app import booking_service as bs
from app import db, rag
from app.seed import seed_tables

EV = "ember-vine"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db, "engine", engine)  # get_session() resolves db.engine at call time
    SQLModel.metadata.create_all(engine)
    seed_tables()
    return engine


def test_availability_picks_smallest_fitting_table(temp_db):
    day = (date.today() + timedelta(days=1)).isoformat()
    result = bs.check_availability(EV, day, 4, "20:00")
    assert len(result["slots"]) == 9  # 18:00 to 22:00 (close 23:30 minus 90 min) every 30 minutes
    assert result["requested_available"] is True
    assert result["suggested_table"]["capacity"] == 4  # smallest table that seats 4
    with pytest.raises(bs.BookingError):
        bs.check_availability(EV, day, bs.MAX_PARTY + 1)


def test_create_then_cancel_booking(temp_db):
    start = datetime.combine(date.today() + timedelta(days=2), time(19, 0))
    booking = bs.create_booking(EV, guest_name="Test Guest", party_size=2, start_time=start, phone="555-0100",
                                source="chat")
    assert booking["code"].startswith("EMB-")
    assert booking["restaurant_slug"] == EV and booking["source"] == "chat"
    assert booking["status"] == "confirmed"

    overlapping = next(s for s in bs.check_availability(EV, start.date(), 2)["slots"] if s["time"] == "19:30")
    assert booking["table_id"] not in {t["id"] for t in overlapping["available_tables"]}

    assert bs.cancel_booking(booking["code"])["status"] == "cancelled"
    with pytest.raises(bs.BookingError):
        bs.cancel_booking(booking["code"])


def test_chunker_splits_by_heading():
    md = "# Menu\n\nIntro to the menu.\n\n## Mains\n\nDry-aged ribeye.\n\n## Desserts\n\nBasque cheesecake."
    chunks = rag.chunk_markdown(md, "menu.md")
    assert [c["section"] for c in chunks] == ["Menu", "Mains", "Desserts"]
    assert all(c["source"] == "menu.md" for c in chunks)
    assert "Dry-aged ribeye." in chunks[1]["text"]


def test_overlapping_bookings_get_separate_tables_until_full(temp_db):
    start = datetime.combine(date.today() + timedelta(days=3), time(20, 0))
    # only P2 (10) and P3 (12) seat ten guests at Ember & Vine
    first = bs.create_booking(EV, guest_name="Party A", party_size=10, start_time=start)
    second = bs.create_booking(EV, guest_name="Party B", party_size=10, start_time=start + timedelta(minutes=30))
    assert first["table_id"] != second["table_id"]

    with pytest.raises(bs.BookingError) as exc:  # overlaps both large tables
        bs.create_booking(EV, guest_name="Party C", party_size=10, start_time=start + timedelta(minutes=60))
    assert exc.value.status_code == 409

    # back-to-back is not an overlap: the first table frees up exactly when its 90-minute hold ends
    third = bs.create_booking(EV, guest_name="Party D", party_size=10, start_time=start + timedelta(minutes=90))
    assert third["table_id"] == first["table_id"]


def test_restaurants_are_isolated_and_searchable(temp_db):
    assert len(bs.list_restaurants()) == 6
    start = datetime.combine(date.today() + timedelta(days=1), time(13, 0))
    alba = bs.create_booking("trattoria-alba", guest_name="Lunch Guest", party_size=2, start_time=start)
    assert alba["code"].startswith("ALB-") and alba["restaurant_name"] == "Trattoria Alba"
    with pytest.raises(bs.BookingError):  # Ember & Vine opens at 18:00
        bs.create_booking(EV, guest_name="Too Early", party_size=2, start_time=start)
    with pytest.raises(bs.BookingError) as exc:  # code belongs to another restaurant
        bs.get_booking(alba["code"], restaurant_slug=EV)
    assert exc.value.status_code == 404

    rooftop_bandra = bs.search_restaurants(area="bandra", tags=["rooftop"], party_size=2,
                                           date=(date.today() + timedelta(days=1)).isoformat(), time="19:00")
    assert [r["slug"] for r in rooftop_bandra] == ["trattoria-alba"]
    assert rooftop_bandra[0]["next_slots"] == ["19:00", "19:30", "20:00"]
    assert {r["slug"] for r in bs.search_restaurants(cuisine="seafood")} == {"koli-tide"}
    assert bs.search_restaurants(price_level=1)[0]["slug"] == "tulsi-thali"

"""Fast smoke tests: booking logic on a throwaway SQLite DB and the RAG chunker. No LLM, no network."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from sqlmodel import SQLModel, create_engine

from app import booking_service as bs
from app import db, rag
from app.seed import seed_tables


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db, "engine", engine)  # get_session() resolves db.engine at call time
    SQLModel.metadata.create_all(engine)
    seed_tables()
    return engine


def test_availability_picks_smallest_fitting_table(temp_db):
    day = (date.today() + timedelta(days=1)).isoformat()
    result = bs.check_availability(day, 4, "20:00")
    assert len(result["slots"]) == 11  # 17:00 to 22:00 every 30 minutes
    assert result["requested_available"] is True
    assert result["suggested_table"]["capacity"] == 4  # smallest table that seats 4
    with pytest.raises(bs.BookingError):
        bs.check_availability(day, bs.MAX_PARTY + 1)


def test_create_then_cancel_booking(temp_db):
    start = datetime.combine(date.today() + timedelta(days=2), time(19, 0))
    booking = bs.create_booking(guest_name="Test Guest", party_size=2, start_time=start, phone="555-0100")
    assert booking["code"].startswith("EV-")
    assert booking["status"] == "confirmed"

    overlapping = next(s for s in bs.check_availability(start.date(), 2)["slots"] if s["time"] == "19:30")
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

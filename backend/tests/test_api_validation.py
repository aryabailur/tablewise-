"""Booking endpoints reject malformed input with 422 before touching the database."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)  # not used as a context manager, so startup (DB seed, RAG ingest) is skipped

VALID = {"guest_name": "Ana Ruiz", "party_size": 2, "start_time": "2026-12-01T19:00:00"}


@pytest.mark.parametrize("override", [
    {"guest_name": "   "},
    {"party_size": 0},
    {"party_size": 13},
    {"start_time": "tomorrow at 8"},
    {"phone": "call me maybe"},
    {"email": "not-an-email"},
    {"zone": "rooftop"},
    {"duration_min": 5},
])
def test_create_booking_rejects_invalid_input(override):
    response = client.post("/api/bookings", json=VALID | override)
    assert response.status_code == 422, response.text


def test_code_date_and_thread_formats_are_validated():
    assert client.get("/api/bookings/not-a-code").status_code == 422
    assert client.patch("/api/bookings/EV-12", json={"party_size": 2}).status_code == 422
    assert client.get("/api/availability", params={"date": "12/01/2026", "party_size": 2}).status_code == 422
    assert client.get("/api/bookings", params={"date": "yesterday"}).status_code == 422
    assert client.post("/api/chat", json={"message": "hi", "thread_id": "bad id with spaces"}).status_code == 422

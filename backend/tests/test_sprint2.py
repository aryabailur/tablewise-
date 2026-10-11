"""Sprint 2: guest details (allergies/dietary/occasion/special requests), host statuses, in-place migration and the
allergy cross-check against menu.md. Throwaway SQLite DBs only - no LLM, no network."""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlmodel import SQLModel, create_engine

from app import allergens, db, graph
from app import booking_service as bs
from app.main import app
from app.seed import seed_demo_bookings, seed_tables

EV = "ember-vine"
client = TestClient(app)  # no lifespan: startup seeding is skipped, the fixture DB is used instead
VALID = {"guest_name": "Ana Ruiz", "party_size": 2, "start_time": "2026-12-01T19:00:00"}


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db, "engine", engine)
    SQLModel.metadata.create_all(engine)
    seed_tables()
    return engine


def _start(days: int = 2, hour: int = 20) -> datetime:
    return datetime.combine(date.today() + timedelta(days=days), time(hour, 0))


# ---------------------------------------------------------------- validation

@pytest.mark.parametrize("override", [
    {"allergies": ["kiwi"]},
    {"allergies": "nuts"},
    {"dietary": "keto"},
    {"occasion": "wedding"},
    {"special_requests": "x" * 501},
])
def test_create_rejects_unknown_guest_details(override):
    assert client.post("/api/bookings", json=VALID | override).status_code == 422
    assert client.post("/api/restaurants/ember-vine/bookings", json=VALID | override).status_code == 422


@pytest.mark.parametrize("body", [{"status": "eaten"}, {"allergies": ["kiwi"]}, {"dietary": "paleo"},
                                  {"occasion": "graduation"}, {"special_requests": "y" * 501}])
def test_patch_rejects_unknown_values(body):
    assert client.patch("/api/bookings/EMB-AAAA", json=body).status_code == 422


def test_service_normalizes_and_rejects():
    assert bs.normalize_allergies(["Nuts", "peanut", "nuts", " Egg "]) == ["nuts", "peanuts", "eggs"]
    assert bs.normalize_allergies("gluten, dairy") == ["gluten", "dairy"]
    assert bs.normalize_dietary(None) == "none" and bs.normalize_dietary("Vegetarian") == "veg"
    for fn, bad in ((bs.normalize_allergies, ["kiwi"]), (bs.normalize_dietary, "keto"),
                    (bs.normalize_occasion, "wedding")):
        with pytest.raises(bs.BookingError) as exc:
            fn(bad)
        assert exc.value.status_code == 422


def test_create_and_get_return_all_fields(temp_db):
    body = {"guest_name": "Mira Shah", "party_size": 2, "start_time": _start().isoformat(), "phone": "98200 12345",
            "allergies": ["Nuts", "shellfish"], "dietary": "veg", "occasion": "anniversary",
            "special_requests": "Quiet table please"}
    created = client.post("/api/restaurants/ember-vine/bookings", json=body)
    assert created.status_code == 201, created.text
    got = client.get(f"/api/bookings/{created.json()['code']}").json()
    assert got["allergies"] == ["nuts", "shellfish"]
    assert (got["dietary"], got["occasion"], got["special_requests"]) == ("veg", "anniversary", "Quiet table please")
    assert {"table_name", "zone", "restaurant_name", "status"} <= got.keys()

    plain = bs.create_booking(EV, guest_name="Plain", party_size=2, start_time=_start(hour=19))
    assert (plain["allergies"], plain["dietary"], plain["occasion"], plain["special_requests"]) == ([], "none",
                                                                                                    "none", None)
    patched = client.patch(f"/api/bookings/{plain['code']}", json={"allergies": ["gluten"], "occasion": "birthday"})
    assert patched.status_code == 200 and patched.json()["allergies"] == ["gluten"]
    assert patched.json()["occasion"] == "birthday" and patched.json()["dietary"] == "none"


# ---------------------------------------------------------------- statuses

def _table_free(booking: dict) -> bool:
    slot = next(s for s in bs.check_availability(EV, booking["start_time"][:10], 10)["slots"]
                if s["time"] == booking["start_time"][11:16])
    return booking["table_id"] in {t["id"] for t in slot["available_tables"]}


def test_status_transitions_and_availability(temp_db):
    b = bs.create_booking(EV, guest_name="Host Test", party_size=10, start_time=_start(days=3))
    code = b["code"]
    assert not _table_free(b)

    seated = client.patch(f"/api/bookings/{code}", json={"status": "seated"})
    assert seated.status_code == 200 and seated.json()["status"] == "seated"
    assert not _table_free(b)  # seated still holds the table
    assert client.patch(f"/api/bookings/{code}", json={"party_size": 4}).status_code == 409  # no rescheduling

    for status in ("completed", "no_show"):
        assert client.patch(f"/api/bookings/{code}", json={"status": status}).json()["status"] == status
        assert _table_free(b)  # finished / no-show bookings release the table

    assert client.patch(f"/api/bookings/{code}", json={"status": "confirmed"}).status_code == 200
    assert not _table_free(b)

    assert client.patch(f"/api/bookings/{code}", json={"status": "cancelled"}).json()["status"] == "cancelled"
    assert _table_free(b)
    for body in ({"status": "confirmed"}, {"status": "seated"}, {"notes": "late"}, {"allergies": ["soy"]}):
        assert client.patch(f"/api/bookings/{code}", json=body).status_code == 409
    assert client.delete(f"/api/bookings/{code}").status_code == 409  # already cancelled


def test_reactivating_a_released_table_that_was_rebooked_conflicts(temp_db):
    start = _start(days=4)
    first = bs.create_booking(EV, guest_name="Gone", party_size=12, start_time=start)  # only P3 seats 12
    bs.modify_booking(first["code"], status="no_show")
    bs.create_booking(EV, guest_name="Walk-in", party_size=12, start_time=start)
    with pytest.raises(bs.BookingError) as exc:
        bs.modify_booking(first["code"], status="seated")
    assert exc.value.status_code == 409


# ---------------------------------------------------------------- migration

V2_BOOKING_DDL = """CREATE TABLE booking (
    id INTEGER PRIMARY KEY, code VARCHAR NOT NULL UNIQUE, restaurant_id INTEGER NOT NULL REFERENCES restaurant (id),
    guest_name VARCHAR NOT NULL, phone VARCHAR, email VARCHAR, party_size INTEGER NOT NULL,
    start_time DATETIME NOT NULL, duration_min INTEGER NOT NULL, table_id INTEGER NOT NULL REFERENCES "table" (id),
    status VARCHAR NOT NULL, source VARCHAR NOT NULL, notes VARCHAR, created_at DATETIME NOT NULL)"""


def test_old_schema_sqlite_db_is_migrated_in_place(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'v2.db'}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db, "engine", engine)
    SQLModel.metadata.create_all(engine)
    seed_tables()
    start = _start(days=5)
    with engine.begin() as conn:  # rebuild booking exactly as v2 shipped it, with one existing booking
        conn.execute(text("DROP TABLE booking"))
        conn.execute(text(V2_BOOKING_DDL))
        conn.execute(text("INSERT INTO booking (code, restaurant_id, guest_name, party_size, start_time, duration_min, "
                          "table_id, status, source, notes, created_at) VALUES ('EMB-OLD1', 1, 'Old Guest', 2, "
                          ":start, 90, 1, 'confirmed', 'web', 'Nut allergy', :now)"),
                     {"start": start.isoformat(sep=" "), "now": datetime.now().isoformat(sep=" ")})
    before = {c["name"] for c in inspect(engine).get_columns("booking")}
    assert "allergies" not in before

    added = db.init_db()
    assert added == ["allergies", "dietary", "occasion", "special_requests"]
    assert db.init_db() == []  # idempotent
    old = bs.get_booking("EMB-OLD1")
    assert old["guest_name"] == "Old Guest" and old["notes"] == "Nut allergy"  # data kept, not reseeded
    assert (old["allergies"], old["dietary"], old["occasion"], old["special_requests"]) == ([], "none", "none", None)
    assert len(bs.list_restaurants()) == 6
    updated = bs.modify_booking("EMB-OLD1", allergies=["nuts"], status="seated")
    assert updated["allergies"] == ["nuts"] and updated["status"] == "seated"
    new = bs.create_booking(EV, guest_name="New Guest", party_size=2, start_time=start, dietary="vegan")
    assert new["dietary"] == "vegan"


def test_seed_gives_about_forty_percent_guest_details(temp_db):
    made = seed_demo_bookings(per_restaurant=15)
    rows = bs.list_bookings()
    assert made == len(rows) > 50
    detailed = [b for b in rows if b["allergies"] or b["dietary"] != "none" or b["occasion"] != "none"
                or b["special_requests"]]
    assert 0.25 <= len(detailed) / len(rows) <= 0.55
    assert any(b["allergies"] for b in rows)


# ---------------------------------------------------------------- allergy cross-check

def test_dishes_to_avoid_reads_the_restaurant_menu():
    avoid = allergens.dishes_to_avoid(EV, ["nuts", "shellfish", "gluten"])
    assert "Charred Padrón Peppers" in avoid["nuts"] and "Seared Scallops" in avoid["nuts"]
    assert "Ember Bread" not in avoid["nuts"]
    assert {"Coal-Roasted Bombay Oysters", "Seared Scallops"} <= set(avoid["shellfish"])
    assert "Ember Bread" in avoid["gluten"] and "Smoked Half Chicken" not in avoid["gluten"]
    assert "Crab Sukka" in allergens.dishes_to_avoid("koli-tide", ["shellfish"])["shellfish"]
    assert "Bombil Fry" not in allergens.dishes_to_avoid("koli-tide", ["shellfish"])["shellfish"]
    assert allergens.allergy_check(EV, []) is None


def test_allergy_check_with_custom_menu(tmp_path):
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "menu.md").write_text(
        "# Demo Diner — Menu\n\n## Mains\n\n- **Satay** — peanut sauce. ₹400.\n"
        "- **Green Salad** — lemon. ₹300. (VG, GF)\n- **Tahini Bowl** — greens. ₹350. Contains: sesame.\n",
        encoding="utf-8")
    check = allergens.allergy_check("demo", ["peanuts", "sesame", "fish"], knowledge_dir=tmp_path)
    assert check["avoid"] == {"peanuts": ["Satay"], "sesame": ["Tahini Bowl"], "fish": []}
    assert "Demo Diner" in check["note"] and "Satay" in check["note"] and "Green Salad" not in check["note"]
    missing = allergens.allergy_check("nowhere", ["fish"], knowledge_dir=tmp_path)
    assert missing["avoid"] == {"fish": []} and "couldn't find a menu" in missing["note"]


def test_allergy_followup_only_when_reply_skips_the_dishes():
    booking = allergens.attach_allergy_check({"code": "EMB-AB12", "restaurant_slug": EV, "allergies": ["shellfish"]})
    results = [{"name": "create_booking", "result": booking}]
    assert graph.allergy_followup(results, "You're booked! Code **EMB-AB12**.") == booking["allergy_check"]["note"]
    dishes = ", ".join(booking["allergy_check"]["avoid"]["shellfish"])
    assert graph.allergy_followup(results, f"Booked. Please skip {dishes}.") is None
    assert graph.allergy_followup([{"name": "create_booking", "result": {"code": "X", "allergies": []}}], "") is None
    assert graph.allergy_followup([{"name": "check_availability", "result": {}}], "") is None


def test_offline_concierge_lookup_names_dishes_to_avoid(temp_db, monkeypatch):
    monkeypatch.setattr(graph, "LLM_ENABLED", False)
    monkeypatch.setattr(graph.rag, "retrieve", lambda *a, **k: [])
    b = bs.create_booking(EV, guest_name="Allergy Guest", party_size=2, start_time=_start(), allergies=["nuts"])

    async def collect():
        return [e async for e in graph.run_chat(f"Can you look up {b['code']}?", "test-allergy-lookup")]
    events = asyncio.run(collect())
    reply = "".join(e["content"] for e in events if e["type"] == "token")
    assert "Allergy check" in reply and "Charred Padrón Peppers" in reply
    assert reply.count("Allergy check") == 1
    tool_end = next(e for e in events if e["type"] == "tool" and e["status"] == "end")
    assert tool_end["result"]["allergy_check"]["avoid"]["nuts"]


def test_chat_tools_accept_guest_details(temp_db):
    state = {"current_restaurant": EV, "messages": []}
    start = _start(days=6)
    created = json.loads(graph.create_booking.func(
        guest_name="Tool Guest", party_size=2, date=start.date().isoformat(), time="20:00", state=state,
        phone="98200 11111", allergies=["dairy"], dietary="vegan", occasion="date", special_requests="Window"))
    assert created["allergies"] == ["dairy"] and created["allergy_check"]["avoid"]["dairy"]
    modified = json.loads(graph.modify_booking.func(code=created["code"], state=state, allergies=["kiwi"]))
    assert "error" in modified
    modified = json.loads(graph.modify_booking.func(code=created["code"], state=state, occasion="birthday"))
    assert modified["occasion"] == "birthday" and modified["dietary"] == "vegan"
    menu = json.loads(graph.check_menu_allergens.func(allergies=["sesame"], state=state))
    assert "Smoked Beetroot Carpaccio" in menu["avoid"]["sesame"]

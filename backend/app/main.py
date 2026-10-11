"""FastAPI app: multi-restaurant REST booking API, SSE concierge chat and Prometheus metrics."""
from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field, field_validator

from . import booking_service as bs
from . import rag
from .graph import LLM_ENABLED, MODEL, PROVIDER, run_chat
from .seed import ensure_seeded


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_seeded()
    if rag.count() == 0:
        await asyncio.to_thread(rag.ingest)
    yield


app = FastAPI(title="Tablewise", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(app, include_in_schema=False)


@app.exception_handler(bs.BookingError)
async def booking_error_handler(_: Request, exc: bs.BookingError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


CODE_PATTERN = r"^[A-Za-z]{2,3}-[A-Za-z0-9]{4}$"  # e.g. EMB-7K2P
SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
TAGS_PATTERN = r"^[A-Za-z0-9 ,-]*$"
_PHONE = re.compile(r"\+?[0-9][0-9 ().-]{5,18}[0-9]")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
Source = Literal["web", "chat", "mcp", "google", "phone"]
Allergen = Literal["nuts", "peanuts", "gluten", "dairy", "shellfish", "fish", "eggs", "soy", "sesame"]
Dietary = Literal["veg", "vegan", "jain", "halal", "none"]
Occasion = Literal["birthday", "anniversary", "business", "date", "none"]
Status = Literal["confirmed", "seated", "completed", "no_show", "cancelled"]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str = Field(min_length=1, max_length=128, pattern=r"^[\w.:-]+$")
    restaurant_slug: str | None = Field(default=None, max_length=64, pattern=SLUG_PATTERN)


class _BookingInput(BaseModel):
    """Shared validation for booking payloads: trimmed text, real-looking contacts, known zones."""

    @field_validator("guest_name", "phone", "email", "notes", "zone", "special_requests", mode="before",
                     check_fields=False)
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("allergies", mode="before", check_fields=False)
    @classmethod
    def _allergies_lower(cls, v):
        return [a.strip().lower() if isinstance(a, str) else a for a in v] if isinstance(v, list) else v

    @field_validator("allergies", check_fields=False)
    @classmethod
    def _allergies_unique(cls, v: list[str] | None) -> list[str] | None:
        return list(dict.fromkeys(v)) if v is not None else None

    @field_validator("phone", check_fields=False)
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v and not _PHONE.fullmatch(v):
            raise ValueError("phone must be 7-20 digits; + ( ) - . and spaces are allowed")
        return v or None

    @field_validator("email", check_fields=False)
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        if v and not _EMAIL.fullmatch(v):
            raise ValueError("email address is not valid")
        return v or None

    @field_validator("zone", check_fields=False)
    @classmethod
    def _zone(cls, v: str | None) -> str | None:
        if not v or v.lower() == "any":
            return None
        if v.lower() not in bs.ZONES:
            raise ValueError(f"zone must be one of: {', '.join(bs.ZONES)}")
        return v.lower()


class BookingCreate(_BookingInput):
    guest_name: str = Field(min_length=1, max_length=80)
    party_size: int = Field(ge=1, le=bs.MAX_PARTY)
    start_time: datetime
    phone: str | None = Field(default=None, max_length=25)
    email: str | None = Field(default=None, max_length=254)
    notes: str | None = Field(default=None, max_length=500)
    zone: str | None = None
    table_id: int | None = Field(default=None, ge=1)
    duration_min: int = Field(default=bs.DEFAULT_DURATION, ge=30, le=240)
    source: Source = "web"
    allergies: list[Allergen] = Field(default_factory=list, max_length=9)
    dietary: Dietary = "none"
    occasion: Occasion = "none"
    special_requests: str | None = Field(default=None, max_length=bs.MAX_SPECIAL_REQUESTS)


class LegacyBookingCreate(BookingCreate):
    restaurant_slug: str | None = Field(default=None, max_length=64, pattern=SLUG_PATTERN)


class BookingUpdate(_BookingInput):
    party_size: int | None = Field(default=None, ge=1, le=bs.MAX_PARTY)
    start_time: datetime | None = None
    notes: str | None = Field(default=None, max_length=500)
    guest_name: str | None = Field(default=None, min_length=1, max_length=80)
    phone: str | None = Field(default=None, max_length=25)
    email: str | None = Field(default=None, max_length=254)
    zone: str | None = None
    status: Status | None = None
    allergies: list[Allergen] | None = Field(default=None, max_length=9)
    dietary: Dietary | None = None
    occasion: Occasion | None = None
    special_requests: str | None = Field(default=None, max_length=bs.MAX_SPECIAL_REQUESTS)


def _slug_path(description: str = "Restaurant slug, e.g. ember-vine"):
    return Path(pattern=SLUG_PATTERN, max_length=64, description=description)


def _code_path():
    return Path(pattern=CODE_PATTERN, description="Booking code, e.g. EMB-7K2P")


def _restaurant_query():
    return Query(bs.DEFAULT_RESTAURANT, pattern=SLUG_PATTERN, max_length=64, description="Restaurant slug")


# ---------------------------------------------------------------- health

@app.get("/api/health")
def health():
    try:
        restaurants = len(bs.restaurant_slugs())
    except Exception:
        restaurants = 0
    return {"status": "ok", "llm": LLM_ENABLED, "provider": PROVIDER, "model": MODEL, "documents": rag.count(),
            "restaurants": restaurants}


# ---------------------------------------------------------------- restaurants

@app.get("/api/restaurants")
def restaurants(q: str | None = Query(None, max_length=100), area: str | None = Query(None, max_length=60),
                cuisine: str | None = Query(None, max_length=60), price_level: int | None = Query(None, ge=1, le=4),
                tags: str | None = Query(None, max_length=200, pattern=TAGS_PATTERN, description="comma-separated"),
                party_size: int = Query(2, ge=1, le=bs.MAX_PARTY),
                date: str | None = Query(None, pattern=DATE_PATTERN, description="YYYY-MM-DD (default today)"),
                time: str | None = Query(None, pattern=TIME_PATTERN, description="HH:MM (default now)")):
    return bs.search_restaurants(q=q, cuisine=cuisine, area=area, price_level=price_level, tags=tags,
                                 party_size=party_size, date=date, time=time)


@app.get("/api/restaurants/{slug}")
def restaurant(slug: str = _slug_path()):
    return bs.get_restaurant(slug) | {"docs": rag.read_docs(slug)}


@app.get("/api/restaurants/{slug}/tables")
def restaurant_tables(slug: str = _slug_path()):
    return bs.list_tables(slug)


@app.get("/api/restaurants/{slug}/availability")
def restaurant_availability(slug: str = _slug_path(),
                            date: str = Query(..., pattern=DATE_PATTERN, description="YYYY-MM-DD"),
                            party_size: int = Query(2, ge=1, le=bs.MAX_PARTY),
                            zone: str | None = Query(None, max_length=20)):
    return bs.check_availability(slug, date, party_size, zone=zone)


@app.post("/api/restaurants/{slug}/bookings", status_code=201)
def restaurant_create_booking(body: BookingCreate, slug: str = _slug_path()):
    return bs.create_booking(slug, **body.model_dump())


# ---------------------------------------------------------------- bookings (global codes) + legacy routes

@app.get("/api/tables")
def tables(restaurant: str = _restaurant_query()):
    return bs.list_tables(restaurant)


@app.get("/api/availability")
def availability(date: str = Query(..., pattern=DATE_PATTERN, description="YYYY-MM-DD"),
                 party_size: int = Query(2, ge=1, le=bs.MAX_PARTY), zone: str | None = Query(None, max_length=20),
                 restaurant: str = _restaurant_query()):
    return bs.check_availability(restaurant, date, party_size, zone=zone)


@app.get("/api/bookings")
def bookings(date: str | None = Query(None, pattern=DATE_PATTERN, description="YYYY-MM-DD"),
             restaurant: str | None = Query(None, pattern=SLUG_PATTERN, max_length=64)):
    return bs.list_bookings(date, restaurant)


@app.post("/api/bookings", status_code=201)
def create(body: LegacyBookingCreate, restaurant: str | None = Query(None, pattern=SLUG_PATTERN, max_length=64)):
    data = body.model_dump()
    slug = data.pop("restaurant_slug") or restaurant or bs.DEFAULT_RESTAURANT
    return bs.create_booking(slug, **data)


@app.get("/api/bookings/{code}")
def get(code: str = _code_path()):
    return bs.get_booking(code)


@app.patch("/api/bookings/{code}")
def update(body: BookingUpdate, code: str = _code_path()):
    return bs.modify_booking(code, **body.model_dump())


@app.delete("/api/bookings/{code}")
def cancel(code: str = _code_path()):
    return bs.cancel_booking(code)


# ---------------------------------------------------------------- chat

@app.post("/api/chat")
async def chat(req: ChatRequest):
    async def events():
        async for evt in run_chat(req.message, req.thread_id, req.restaurant_slug):
            yield f"data: {json.dumps(evt, default=str)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

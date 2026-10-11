"""FastAPI app: REST booking API + SSE concierge chat."""
from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from . import booking_service as bs
from . import rag
from .db import init_db
from .graph import LLM_ENABLED, MODEL, PROVIDER, run_chat
from .seed import seed_tables


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    seed_tables()
    if rag.count() == 0:
        await asyncio.to_thread(rag.ingest)
    yield


app = FastAPI(title="Tablewise - Ember & Vine", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(bs.BookingError)
async def booking_error_handler(_: Request, exc: bs.BookingError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


CODE_PATTERN = r"^[Ee][Vv]-[A-Za-z0-9]{4}$"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
_PHONE = re.compile(r"\+?[0-9][0-9 ().-]{5,18}[0-9]")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str = Field(min_length=1, max_length=128, pattern=r"^[\w.:-]+$")


class _BookingInput(BaseModel):
    """Shared validation for booking payloads: trimmed text, real-looking contacts, known zones."""

    @field_validator("guest_name", "phone", "email", "notes", "zone", mode="before", check_fields=False)
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

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


class BookingUpdate(_BookingInput):
    party_size: int | None = Field(default=None, ge=1, le=bs.MAX_PARTY)
    start_time: datetime | None = None
    notes: str | None = Field(default=None, max_length=500)
    guest_name: str | None = Field(default=None, min_length=1, max_length=80)
    phone: str | None = Field(default=None, max_length=25)
    email: str | None = Field(default=None, max_length=254)
    zone: str | None = None


@app.get("/api/health")
def health():
    return {"status": "ok", "llm": LLM_ENABLED, "provider": PROVIDER, "model": MODEL, "documents": rag.count()}


@app.get("/api/tables")
def tables():
    return bs.list_tables()


@app.get("/api/availability")
def availability(date: str = Query(..., pattern=DATE_PATTERN, description="YYYY-MM-DD"),
                 party_size: int = Query(2, ge=1, le=bs.MAX_PARTY), zone: str | None = Query(None, max_length=20)):
    return bs.check_availability(date, party_size, zone=zone)


@app.get("/api/bookings")
def bookings(date: str | None = Query(None, pattern=DATE_PATTERN, description="YYYY-MM-DD")):
    return bs.list_bookings(date)


@app.post("/api/bookings", status_code=201)
def create(body: BookingCreate):
    return bs.create_booking(**body.model_dump())


@app.get("/api/bookings/{code}")
def get(code: str = Path(pattern=CODE_PATTERN, description="Booking code, e.g. EV-7K2P")):
    return bs.get_booking(code)


@app.patch("/api/bookings/{code}")
def update(body: BookingUpdate, code: str = Path(pattern=CODE_PATTERN, description="Booking code, e.g. EV-7K2P")):
    return bs.modify_booking(code, **body.model_dump())


@app.delete("/api/bookings/{code}")
def cancel(code: str = Path(pattern=CODE_PATTERN, description="Booking code, e.g. EV-7K2P")):
    return bs.cancel_booking(code)


@app.post("/api/chat")
async def chat(req: ChatRequest):
    async def events():
        async for evt in run_chat(req.message, req.thread_id):
            yield f"data: {json.dumps(evt, default=str)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

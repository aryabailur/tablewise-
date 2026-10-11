"""FastAPI app: REST booking API + SSE concierge chat."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

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


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str = Field(min_length=1, max_length=128)


class BookingCreate(BaseModel):
    guest_name: str
    party_size: int = Field(ge=1, le=bs.MAX_PARTY)
    start_time: str
    phone: str | None = None
    email: str | None = None
    notes: str | None = None
    zone: str | None = None
    table_id: int | None = None
    duration_min: int = bs.DEFAULT_DURATION


class BookingUpdate(BaseModel):
    party_size: int | None = Field(default=None, ge=1, le=bs.MAX_PARTY)
    start_time: str | None = None
    notes: str | None = None
    guest_name: str | None = None
    phone: str | None = None
    email: str | None = None
    zone: str | None = None


@app.get("/api/health")
def health():
    return {"status": "ok", "llm": LLM_ENABLED, "provider": PROVIDER, "model": MODEL, "documents": rag.count()}


@app.get("/api/tables")
def tables():
    return bs.list_tables()


@app.get("/api/availability")
def availability(date: str = Query(..., description="YYYY-MM-DD"), party_size: int = Query(2, ge=1, le=bs.MAX_PARTY),
                 zone: str | None = None):
    return bs.check_availability(date, party_size, zone=zone)


@app.get("/api/bookings")
def bookings(date: str | None = None):
    return bs.list_bookings(date)


@app.post("/api/bookings", status_code=201)
def create(body: BookingCreate):
    return bs.create_booking(**body.model_dump())


@app.get("/api/bookings/{code}")
def get(code: str):
    return bs.get_booking(code)


@app.patch("/api/bookings/{code}")
def update(code: str, body: BookingUpdate):
    return bs.modify_booking(code, **body.model_dump())


@app.delete("/api/bookings/{code}")
def cancel(code: str):
    return bs.cancel_booking(code)


@app.post("/api/chat")
async def chat(req: ChatRequest):
    async def events():
        async for evt in run_chat(req.message, req.thread_id):
            yield f"data: {json.dumps(evt, default=str)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

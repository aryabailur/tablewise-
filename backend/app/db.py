"""SQLModel models + engine/session helpers for restaurants, tables, bookings and RAG chunks.

DATABASE_URL selects the database (default: SQLite file at backend/data/tablewise.db).
Postgres works via psycopg 3, e.g. postgresql+psycopg://tablewise:tablewise@postgres:5432/tablewise.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import JSON, Column, DateTime, Text, UniqueConstraint, inspect
from sqlmodel import Field, Session, SQLModel, create_engine

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "tablewise.db"
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{DB_PATH}"


def make_engine(url: str = DATABASE_URL):
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)


engine = make_engine()


class Restaurant(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    name: str
    code_prefix: str = Field(unique=True)  # booking codes look like EMB-7K2P
    cuisine: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    area: str = Field(index=True)
    price_level: int = Field(index=True)  # 1-4
    rating: float = 4.0
    avg_cost_for_two: int  # INR
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    hours_open: str  # "HH:MM"
    hours_close: str  # "HH:MM" (midnight stored as 23:59)
    slot_minutes: int = 30
    cover_image: str = ""  # CSS gradient string
    description: str = ""


class Table(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("restaurant_id", "name", name="uq_table_restaurant_name"),)

    id: int | None = Field(default=None, primary_key=True)
    restaurant_id: int = Field(foreign_key="restaurant.id", index=True)
    name: str = Field(index=True)
    capacity: int
    zone: str  # window | garden | bar | private | rooftop | patio
    is_active: bool = True


class Booking(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    restaurant_id: int = Field(foreign_key="restaurant.id", index=True)
    guest_name: str
    phone: str | None = None
    email: str | None = None
    party_size: int
    start_time: datetime = Field(index=True, sa_type=DateTime)  # naive local (Asia/Kolkata) time
    duration_min: int = 90
    table_id: int = Field(foreign_key="table.id")
    status: str = Field(default="confirmed", index=True)  # confirmed | cancelled
    source: str = Field(default="web", index=True)  # web | chat | mcp | google | phone
    notes: str | None = None
    created_at: datetime = Field(default_factory=datetime.now, sa_type=DateTime)


class RagDocument(SQLModel, table=True):
    __tablename__ = "rag_documents"

    id: str = Field(primary_key=True)
    restaurant_slug: str = Field(index=True)  # "_platform" for Tablewise-wide docs
    source: str
    section: str
    chunk_index: int
    text: str = Field(sa_column=Column(Text, nullable=False))


def _schema_outdated() -> bool:
    """True when an old single-restaurant schema is present (booking table without restaurant_id)."""
    insp = inspect(engine)
    if not insp.has_table("booking"):
        return False
    return "restaurant_id" not in {c["name"] for c in insp.get_columns("booking")}


def init_db(reset: bool = False) -> None:
    if reset or _schema_outdated():
        SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)

"""SQLModel models + engine/session helpers for tables and bookings."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import DateTime
from sqlmodel import Field, Session, SQLModel, create_engine

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "tablewise.db"

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


class Table(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    capacity: int
    zone: str  # window | garden | bar | private
    is_active: bool = True


class Booking(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    guest_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    party_size: int
    start_time: datetime = Field(index=True, sa_type=DateTime)  # naive local time
    duration_min: int = 90
    table_id: int = Field(foreign_key="table.id")
    status: str = Field(default="confirmed", index=True)  # confirmed | cancelled
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now, sa_type=DateTime)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)

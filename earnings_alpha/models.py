from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .settings import settings

class Base(DeclarativeBase): pass
class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    announced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    session: Mapped[str] = mapped_column(String(20))
    eps_surprise: Mapped[float] = mapped_column(Float, default=0)
    revenue_surprise: Mapped[float] = mapped_column(Float, default=0)
    guidance_score: Mapped[float] = mapped_column(Float, default=0)
    probability: Mapped[float] = mapped_column(Float, default=0)
    signal: Mapped[str] = mapped_column(String(12), default="WAIT")
class Position(Base):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(Integer, index=True)
    side: Mapped[str] = mapped_column(String(5))
    quantity: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[float] = mapped_column(Float)
    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="paper only")
class Watch(Base):
    __tablename__ = "watches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    session: Mapped[str] = mapped_column(String(20), default="after_market")
    expected_eps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_revenue: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="WAITING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_polled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    detected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    analysis_json: Mapped[str] = mapped_column(Text, default="{}")
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})
Session = sessionmaker(bind=engine, expire_on_commit=False)
def init_db(): Base.metadata.create_all(engine)

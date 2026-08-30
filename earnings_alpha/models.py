from datetime import datetime
from sqlalchemy import DateTime, Float, Integer, String, Text, create_engine
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
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="paper only")
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})
Session = sessionmaker(bind=engine, expire_on_commit=False)
def init_db(): Base.metadata.create_all(engine)

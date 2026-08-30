from dataclasses import dataclass
import os

@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./earnings_alpha.db")
    target: float = float(os.getenv("PROFIT_TARGET_PCT", "0.055"))
    stop: float = float(os.getenv("STOP_LOSS_PCT", "0.035"))
    min_probability: float = float(os.getenv("MIN_MODEL_PROBABILITY", "0.70"))
    live_orders: bool = os.getenv("ENABLE_LIVE_ORDERS", "false").lower() == "true"
settings = Settings()
if settings.live_orders:
    raise RuntimeError("Live execution is deliberately unsupported in Earnings Alpha v3; set ENABLE_LIVE_ORDERS=false")

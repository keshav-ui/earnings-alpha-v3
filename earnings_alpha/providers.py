"""Credential-safe provider contracts. Replace stubs only with licensed API implementations."""
from dataclasses import dataclass
from datetime import datetime, timezone
import os, httpx

@dataclass(frozen=True)
class Quote: bid: float; ask: float; last: float; timestamp: datetime
@dataclass(frozen=True)
class Trade: price: float; size: int; timestamp: datetime
class ProviderUnavailable(RuntimeError): pass
class MarketDataProvider:
    def quote(self, symbol: str) -> Quote: raise NotImplementedError
    def trades(self, symbol: str, start: datetime, end: datetime) -> list[Trade]: raise NotImplementedError
class EarningsProvider:
    def results(self, symbol: str, announced_at: datetime) -> dict: raise NotImplementedError
    def consensus(self, symbol: str, announced_at: datetime) -> dict: raise NotImplementedError
class TranscriptNewsProvider:
    def documents(self, symbol: str, since: datetime) -> list[dict]: raise NotImplementedError
class ReplayProvider(MarketDataProvider, EarningsProvider, TranscriptNewsProvider):
    """Deterministic synthetic data; clearly labelled replay, never an executable feed."""
    def quote(self, symbol): return Quote(100.00, 100.10, 100.05, datetime.now(timezone.utc))
    def trades(self, symbol, start, end): return [Trade(100.05, 100, start), Trade(100.10, 150, end)]
    def results(self, symbol, announced_at): return {"source":"replay", "eps_surprise":0.08,"revenue_surprise":0.04,"guidance_score":0.2}
    def consensus(self, symbol, announced_at): return {"source":"replay"}
    def documents(self, symbol, since): return [{"source":"replay", "sentiment":0.1}]
class SecXbrlProvider:
    """Public SEC verification. Requires a truthful contact User-Agent; rate-limit in production."""
    BASE="https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    def company_facts(self, cik: str) -> dict:
        agent=os.getenv("SEC_USER_AGENT", "")
        if not agent or "@" not in agent: raise ProviderUnavailable("Set SEC_USER_AGENT to a real contact before SEC requests")
        r=httpx.get(self.BASE.format(cik=cik.zfill(10)),headers={"User-Agent":agent},timeout=20)
        r.raise_for_status(); return r.json()
class CredentialedAdapter:
    def __init__(self, env_key: str, name: str): self.key=os.getenv(env_key); self.name=name
    def require_ready(self):
        if not self.key: raise ProviderUnavailable(f"{self.name} is not configured; using ReplayProvider. Add licensed credentials to enable its adapter.")
        raise ProviderUnavailable(f"{self.name} credentials detected, but endpoint mapping is intentionally provider-specific. Complete and test the licensed adapter before enabling it.")

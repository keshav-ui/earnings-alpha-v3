"""Credential-safe provider contracts. Replace stubs only with licensed API implementations."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib, math, os, httpx

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
    @staticmethod
    def _seed(symbol: str) -> int:
        return int(hashlib.sha256(symbol.upper().encode()).hexdigest()[:12], 16)
    def quote(self, symbol):
        seed=self._seed(symbol); mid=round(35+(seed%42000)/100,2)
        spread=round(max(.02,mid*(.0004+(seed%7)/10000)),2)
        return Quote(round(mid-spread/2,2),round(mid+spread/2,2),mid,datetime.now(timezone.utc))
    def trades(self, symbol, start, end):
        q=self.quote(symbol)
        return [Trade(q.last,100+(self._seed(symbol)%900),start),Trade(q.ask,150+(self._seed(symbol)%700),end)]
    def results(self, symbol, announced_at):
        seed=self._seed(symbol)
        return {"source":"replay","eps_surprise":round(((seed%31)-10)/100,3),"revenue_surprise":round((((seed//31)%25)-8)/100,3),"guidance_score":round((((seed//775)%21)-10)/20,3)}
    def consensus(self, symbol, announced_at):
        seed=self._seed(symbol)
        return {"source":"replay","analysts":8+seed%29,"eps_estimate":round(.4+(seed%400)/100,2)}
    def documents(self, symbol, since):
        seed=self._seed(symbol)
        return [{"source":"replay","sentiment":round((((seed//19)%21)-10)/10,2),"headline_count":3+seed%12}]
    def snapshot(self, symbol: str, announced_at: datetime) -> dict:
        seed=self._seed(symbol); q=self.quote(symbol); result=self.results(symbol,announced_at)
        spread=(q.ask-q.bid)/q.last
        imbalance=round((((seed//11)%181)-90)/100,3)
        return {**result,"quote":q,"spread_pct":spread,"aggressor_imbalance":imbalance,
                "relative_volume":round(.7+(seed%280)/100,2),"price_reaction":round((((seed//23)%141)-70)/1000,3),
                "transcript_sentiment":self.documents(symbol,announced_at)[0]["sentiment"],
                "consensus":self.consensus(symbol,announced_at)}
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

class MassiveSnapshotProvider(MarketDataProvider):
    """Licensed consolidated U.S. snapshot feed. Entitlements determine real-time availability."""
    BASE="https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers/{symbol}"
    def __init__(self, api_key: str):
        if not api_key: raise ProviderUnavailable("MASSIVE_API_KEY is not configured")
        self.api_key=api_key
    def quote(self, symbol: str) -> Quote:
        r=httpx.get(self.BASE.format(symbol=symbol.upper()),params={"apiKey":self.api_key},timeout=8);r.raise_for_status()
        t=r.json().get("ticker",{}); q=t.get("lastQuote",{}); trade=t.get("lastTrade",{})
        if not q or not trade: raise ProviderUnavailable("licensed snapshot did not include quote and trade entitlements")
        stamp=(trade.get("t") or t.get("updated") or 0)/1_000_000_000
        return Quote(float(q["p"]),float(q["P"]),float(trade["p"]),datetime.fromtimestamp(stamp,tz=timezone.utc))
    def trades(self, symbol, start, end): raise NotImplementedError("Use the licensed trade stream for tick history")

class LicensedEarningsProvider(EarningsProvider, TranscriptNewsProvider):
    """Adapter for a licensed normalized gateway; never scrapes issuer or Nasdaq web pages."""
    def __init__(self, results_url: str, results_key: str, news_url: str="", news_key: str=""):
        if not results_url or not results_key: raise ProviderUnavailable("licensed earnings results feed is not configured")
        self.results_url,self.results_key,self.news_url,self.news_key=results_url,results_key,news_url,news_key
    def _get(self,url,key,symbol):
        r=httpx.get(url.format(symbol=symbol.upper()),headers={"Authorization":f"Bearer {key}"},timeout=8);r.raise_for_status();return r.json()
    def results(self,symbol,announced_at):
        x=self._get(self.results_url,self.results_key,symbol)
        required=("actual_eps","estimated_eps","actual_revenue","estimated_revenue","announced_at")
        if not all(k in x for k in required): raise ProviderUnavailable("earnings gateway response is missing normalized fields")
        eps_base=max(abs(float(x["estimated_eps"])),.01); rev_base=max(abs(float(x["estimated_revenue"])),1)
        return {"source":x.get("source","licensed"),"eps_surprise":(float(x["actual_eps"])-float(x["estimated_eps"]))/eps_base,"revenue_surprise":(float(x["actual_revenue"])-float(x["estimated_revenue"]))/rev_base,"guidance_score":float(x.get("guidance_score",0)),"commentary":x.get("commentary","")[:5000],"announced_at":x["announced_at"]}
    def consensus(self,symbol,announced_at): return self._get(self.results_url,self.results_key,symbol)
    def documents(self,symbol,since):
        if not self.news_url or not self.news_key:return []
        x=self._get(self.news_url,self.news_key,symbol);return x if isinstance(x,list) else x.get("documents",[])

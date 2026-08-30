from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Iterable
import math

@dataclass(frozen=True)
class Bar:
    timestamp: datetime; bid: float; ask: float; last: float; volume: float
@dataclass(frozen=True)
class BacktestResult:
    outcome: str; entry: float; exit: float; return_pct: float; exit_at: datetime; costs_pct: float
def next_regular_open(t: datetime) -> datetime:
    # Calendar adapter should still replace this for US exchange holidays/half days.
    t=t.astimezone(ZoneInfo("America/New_York")); candidate=t.replace(hour=9, minute=30, second=0, microsecond=0)
    if t >= candidate: candidate += timedelta(days=1)
    while candidate.weekday() >= 5: candidate += timedelta(days=1)
    return candidate
def features(bars: list[Bar], event: dict) -> dict:
    if not bars: raise ValueError("bars required")
    first,last=bars[0],bars[-1]; mids=[(b.bid+b.ask)/2 for b in bars]
    spread=sum(b.ask-b.bid for b in bars)/len(bars)/max(mids[-1],.01)
    signed=sum((1 if b.last >= (b.bid+b.ask)/2 else -1)*b.volume for b in bars)
    return {"eps_surprise":event.get("eps_surprise",0),"revenue_surprise":event.get("revenue_surprise",0),"guidance_score":event.get("guidance_score",0),"return_since_announcement":(last.last/first.last)-1,"spread_pct":spread,"aggressor_imbalance":signed/max(sum(b.volume for b in bars),1),"volume":sum(b.volume for b in bars)}
def backtest(bars: Iterable[Bar], side="LONG", target=.055, stop=.035, slippage_bps=8.0) -> BacktestResult:
    bars=list(bars)
    if not bars: raise ValueError("no bars")
    buy=side=="LONG"; entry=(bars[0].ask if buy else bars[0].bid)*(1+(slippage_bps/10000 if buy else -slippage_bps/10000))
    deadline=next_regular_open(bars[0].timestamp); final=bars[-1]
    for b in bars[1:]:
        px=b.bid if buy else b.ask; ret=(px/entry-1)*(1 if buy else -1)
        if ret>=target: return BacktestResult("TARGET",entry,px,ret,b.timestamp,slippage_bps/10000)
        if ret<=-stop: return BacktestResult("STOP_LOSS",entry,px,ret,b.timestamp,slippage_bps/10000)
        if b.timestamp>=deadline: return BacktestResult("NEXT_SESSION_OPEN",entry,px,ret,b.timestamp,slippage_bps/10000)
    px=final.bid if buy else final.ask
    return BacktestResult("DATA_ENDED",entry,px,(px/entry-1)*(1 if buy else -1),final.timestamp,slippage_bps/10000)
def score_probability(f: dict) -> float:
    z=1.6*f["eps_surprise"]+1.2*f["revenue_surprise"]+.8*f["guidance_score"]+1.1*f["aggressor_imbalance"]-8*f["spread_pct"]
    return 1/(1+math.exp(-z))

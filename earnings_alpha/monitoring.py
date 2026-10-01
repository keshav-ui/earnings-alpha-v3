import asyncio, json, logging
from datetime import datetime, timezone
from .models import Session, Watch
from .providers import LicensedEarningsProvider, MassiveSnapshotProvider, ProviderUnavailable, ReplayProvider
from .research import score_probability
from .settings import settings

log=logging.getLogger("earnings_alpha.monitor")

def provider_status():
    market=bool(settings.massive_api_key); results=bool(settings.earnings_results_url and settings.earnings_api_key)
    return {"mode":"LIVE_LICENSED" if market and results else "REPLAY","poll_interval_seconds":settings.monitor_interval,"market_data":{"configured":market,"provider":"Massive consolidated US equities" if market else "Replay"},"earnings_results":{"configured":results,"provider":"Licensed normalized gateway" if results else "Replay"},"transcripts_news":{"configured":bool(settings.transcript_news_url and settings.transcript_api_key)},"sec_xbrl":{"configured":bool(__import__('os').getenv('SEC_USER_AGENT'))},"live_execution":False}

def poll_watch(watch_id:int, force_replay:bool=False):
    with Session() as db:
        w=db.get(Watch,watch_id)
        if not w or not w.active:return None
        now=datetime.now(timezone.utc); w.last_polled_at=now
        live=provider_status()["mode"]=="LIVE_LICENSED" and not force_replay
        try:
            if live:
                ep=LicensedEarningsProvider(settings.earnings_results_url,settings.earnings_api_key,settings.transcript_news_url,settings.transcript_api_key)
                result=ep.results(w.symbol,now); quote=MassiveSnapshotProvider(settings.massive_api_key).quote(w.symbol)
                announced=datetime.fromisoformat(str(result["announced_at"]).replace("Z","+00:00"))
                if announced <= w.created_at.replace(tzinfo=w.created_at.tzinfo or timezone.utc):
                    w.status="WAITING";db.commit();return {"status":"WAITING"}
                imbalance=0.0; spread=(quote.ask-quote.bid)/max(quote.last,.01); mode="LIVE_LICENSED"
            else:
                rp=ReplayProvider();result=rp.results(w.symbol,now);quote=rp.quote(w.symbol);imbalance=rp.snapshot(w.symbol,now)["aggressor_imbalance"];spread=(quote.ask-quote.bid)/quote.last;mode="REPLAY"
            p=score_probability({**result,"aggressor_imbalance":imbalance,"spread_pct":spread}); signal="BUY" if p>=settings.min_probability else "SELL" if 1-p>=settings.min_probability else "WAIT"
            payload={"symbol":w.symbol,"signal":signal,"bullish_probability":round(p,3),"eps_surprise":round(result["eps_surprise"],4),"revenue_surprise":round(result["revenue_surprise"],4),"guidance_score":round(result.get("guidance_score",0),3),"commentary":result.get("commentary","")[:800],"price":quote.last,"spread_pct":round(spread*100,4),"detected_at":now.isoformat(),"source_mode":mode}
            w.status="ANALYZED";w.detected_at=now;w.analysis_json=json.dumps(payload);db.commit();return payload
        except Exception as exc:
            w.status="PROVIDER_ERROR";w.analysis_json=json.dumps({"error":str(exc)[:300]});db.commit();log.warning("monitor poll failed for %s: %s",w.symbol,exc);return None

async def monitor_loop():
    while True:
        try:
            with Session() as db: ids=[x[0] for x in db.query(Watch.id).filter(Watch.active.is_(True)).all()]
            for watch_id in ids: await asyncio.to_thread(poll_watch,watch_id)
        except Exception as exc: log.exception("monitor cycle failed: %s",exc)
        await asyncio.sleep(settings.monitor_interval)

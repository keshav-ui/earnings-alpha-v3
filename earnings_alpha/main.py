from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging, json
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from .models import init_db, Session, Event, Position
from .providers import ReplayProvider
from .research import next_regular_open, score_probability
from .settings import settings

logging.basicConfig(level=logging.INFO, format="%(message)s")
log=logging.getLogger("earnings_alpha")
def record(action, **fields): log.info(json.dumps({"action":action, **fields}))
@asynccontextmanager
async def life(app):
    init_db()
    with Session() as db:
        if not db.query(Event).first():
            r=ReplayProvider().results("DEMO",datetime.now(timezone.utc)); prob=score_probability({**r,"aggressor_imbalance":.1,"spread_pct":.001})
            db.add(Event(symbol="DEMO",announced_at=datetime.now(timezone.utc),session="after_market",probability=prob,signal="BUY" if prob>=settings.min_probability else "WAIT",**{k:r[k] for k in ("eps_surprise","revenue_surprise","guidance_score")})); db.commit()
    yield
app=FastAPI(title="Earnings Alpha v3", lifespan=life)
class Enter(BaseModel): event_id:int; side:str="LONG"; quantity:int=Field(gt=0,le=100000)
class Exit(BaseModel): price:float=Field(gt=0)
def event_out(e): return {"id":e.id,"symbol":e.symbol,"announced_at":e.announced_at,"session":e.session,"probability":round(e.probability,3),"signal":e.signal,"target_pct":settings.target,"stop_pct":settings.stop}
def pos_out(p): return {"id":p.id,"event_id":p.event_id,"side":p.side,"quantity":p.quantity,"entry_price":p.entry_price,"entry_at":p.entry_at,"deadline":p.deadline,"exit_price":p.exit_price,"exit_at":p.exit_at,"exit_reason":p.exit_reason}
@app.get("/health")
def health(): return {"status":"ok","mode":"paper/replay","live_execution":False}
@app.get("/api/events")
def events():
    with Session() as db:return [event_out(x) for x in db.query(Event).order_by(Event.announced_at.desc()).all()]
@app.get("/api/positions")
def positions():
    with Session() as db:return [pos_out(x) for x in db.query(Position).order_by(Position.id.desc()).all()]
@app.post("/api/positions")
def enter(x:Enter):
    if x.side not in ("LONG","SHORT"): raise HTTPException(422,"side must be LONG or SHORT")
    with Session() as db:
        e=db.get(Event,x.event_id)
        if not e: raise HTTPException(404,"event not found")
        q=ReplayProvider().quote(e.symbol); price=q.ask if x.side=="LONG" else q.bid
        p=Position(event_id=e.id,side=x.side,quantity=x.quantity,entry_price=price,entry_at=q.timestamp,deadline=next_regular_open(q.timestamp))
        db.add(p);db.commit();record("paper_enter",position_id=p.id,symbol=e.symbol);return pos_out(p)
@app.post("/api/positions/{position_id}/exit")
def exit_now(position_id:int,x:Exit):
    with Session() as db:
        p=db.get(Position,position_id)
        if not p: raise HTTPException(404,"position not found")
        if p.exit_at: raise HTTPException(409,"position already closed")
        now=datetime.now(timezone.utc)
        if now>=p.deadline: raise HTTPException(409,"manual exit window closed; record a NEXT_SESSION_OPEN exit")
        p.exit_price=x.price;p.exit_at=now;p.exit_reason="MANUAL_EXIT";db.commit();record("paper_manual_exit",position_id=p.id);return pos_out(p)
@app.get("/",response_class=HTMLResponse)
def dashboard():
    return """<!doctype html><title>Earnings Alpha v3</title><style>body{font:16px system-ui;max-width:850px;margin:40px auto;background:#10151d;color:#e8eef7}button{padding:9px;margin:3px}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #334}</style><h1>Earnings Alpha <small>v3 · PAPER / REPLAY</small></h1><p>Entry after announcement. Manual exit is available until the next US regular-session open. No live-money execution exists in this build.</p><h2>Signals</h2><table id=e></table><h2>Positions</h2><table id=p></table><script>async function load(){let es=await (await fetch('/api/events')).json();e.innerHTML='<tr><th>Symbol</th><th>Signal</th><th>Probability</th><th>Action</th></tr>'+es.map(x=>`<tr><td>${x.symbol}</td><td>${x.signal}</td><td>${(x.probability*100).toFixed(1)}%</td><td><button onclick="enter(${x.id})">Paper enter</button></td></tr>`).join('');let ps=await (await fetch('/api/positions')).json();p.innerHTML='<tr><th>ID</th><th>Entry</th><th>Deadline</th><th>Status</th></tr>'+ps.map(x=>`<tr><td>${x.id}</td><td>${x.entry_price}</td><td>${new Date(x.deadline).toLocaleString()}</td><td>${x.exit_reason||`<button onclick="quit(${x.id},${x.entry_price})">EXIT NOW</button>`}</td></tr>`).join('')}async function enter(id){await fetch('/api/positions',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({event_id:id,quantity:10})});load()}async function quit(id,price){let v=prompt('Paper exit price',price);if(v)await fetch('/api/positions/'+id+'/exit',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({price:+v})});load()}load()</script>"""

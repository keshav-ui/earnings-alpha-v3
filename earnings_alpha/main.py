from contextlib import asynccontextmanager
import asyncio
from datetime import datetime, timezone
import logging, json
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from .models import init_db, Session, Event, Position, Watch
from .monitoring import monitor_loop, poll_watch, provider_status
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
    task=asyncio.create_task(monitor_loop())
    yield
    task.cancel()
app=FastAPI(title="Earnings Alpha v3", lifespan=life)
class Enter(BaseModel):
    event_id:int; side:str="LONG"; quantity:int=Field(gt=0,le=100000)
    target_pct:float=Field(default=settings.target,gt=0,le=.50)
    stop_pct:float=Field(default=settings.stop,gt=0,le=.50)
class Exit(BaseModel): price:float=Field(gt=0)
class Analyze(BaseModel):
    symbol:str=Field(min_length=1,max_length=12,pattern=r"^[A-Za-z][A-Za-z0-9.\-]{0,11}$")
    session:str="after_market"
    target_pct:float=Field(default=settings.target,gt=0,le=.50)
    stop_pct:float=Field(default=settings.stop,gt=0,le=.50)
class WatchIn(BaseModel):
    symbol:str=Field(min_length=1,max_length=12,pattern=r"^[A-Za-z][A-Za-z0-9.\-]{0,11}$")
    session:str="after_market"
    expected_eps:Optional[float]=None
    expected_revenue:Optional[float]=None
def event_out(e): return {"id":e.id,"symbol":e.symbol,"announced_at":e.announced_at,"session":e.session,"probability":round(e.probability,3),"signal":e.signal,"target_pct":settings.target,"stop_pct":settings.stop}
def pos_out(p, symbol=None):
    try: risk=json.loads(p.notes)
    except (ValueError,TypeError): risk={"target_pct":settings.target,"stop_pct":settings.stop}
    return {"id":p.id,"event_id":p.event_id,"symbol":symbol,"side":p.side,"quantity":p.quantity,"entry_price":p.entry_price,"entry_at":p.entry_at,"deadline":p.deadline,"exit_price":p.exit_price,"exit_at":p.exit_at,"exit_reason":p.exit_reason,**risk}
@app.get("/health")
def health(): return {"status":"ok","mode":"paper/replay","live_execution":False}
@app.get("/api/providers")
def providers(): return provider_status()
@app.get("/api/watchlist")
def watchlist():
    with Session() as db:
        rows=db.query(Watch).order_by(Watch.id.desc()).all()
        return [{"id":w.id,"symbol":w.symbol,"session":w.session,"status":w.status,"active":w.active,"last_polled_at":w.last_polled_at,"detected_at":w.detected_at,"analysis":json.loads(w.analysis_json or "{}") } for w in rows]
@app.post("/api/watchlist")
def create_watch(x:WatchIn):
    if x.session not in ("after_market","pre_market"): raise HTTPException(422,"session must be after_market or pre_market")
    w=Watch(symbol=x.symbol.upper(),session=x.session,expected_eps=x.expected_eps,expected_revenue=x.expected_revenue,created_at=datetime.now(timezone.utc),status="WAITING",active=True)
    with Session() as db: db.add(w);db.commit();wid=w.id
    result=poll_watch(wid,force_replay=provider_status()["mode"]!="LIVE_LICENSED")
    record("watch_created",symbol=x.symbol.upper(),interval_seconds=settings.monitor_interval)
    return {"id":wid,"status":"ANALYZED" if result else "WAITING","analysis":result,"provider":provider_status()}
@app.get("/api/events")
def events():
    with Session() as db:return [event_out(x) for x in db.query(Event).order_by(Event.announced_at.desc()).all()]
@app.get("/api/positions")
def positions():
    with Session() as db:
        rows=db.query(Position,Event.symbol).join(Event,Position.event_id==Event.id).order_by(Position.id.desc()).all()
        return [pos_out(p,symbol) for p,symbol in rows]
@app.post("/api/analyze")
def analyze(x:Analyze):
    if x.session not in ("after_market","pre_market"): raise HTTPException(422,"session must be after_market or pre_market")
    symbol=x.symbol.upper(); now=datetime.now(timezone.utc); provider=ReplayProvider(); snap=provider.snapshot(symbol,now)
    f={"eps_surprise":snap["eps_surprise"],"revenue_surprise":snap["revenue_surprise"],"guidance_score":snap["guidance_score"],"aggressor_imbalance":snap["aggressor_imbalance"],"spread_pct":snap["spread_pct"]}
    bullish=score_probability(f); bearish=1-bullish
    confidence=max(bullish,bearish)
    signal="BUY" if bullish>=settings.min_probability else "SELL" if bearish>=settings.min_probability else "WAIT"
    probability=bullish if signal=="BUY" else bearish if signal=="SELL" else confidence
    e=Event(symbol=symbol,announced_at=now,session=x.session,probability=probability,signal=signal,eps_surprise=f["eps_surprise"],revenue_surprise=f["revenue_surprise"],guidance_score=f["guidance_score"])
    with Session() as db:
        db.add(e);db.commit()
    q=snap["quote"]; expected=round(abs(.45*f["eps_surprise"]+.30*f["revenue_surprise"]+.025*snap["transcript_sentiment"]+.18*snap["price_reaction"])*100,2)
    reasons=[
        {"label":"EPS surprise","value":f'{f["eps_surprise"]*100:+.1f}%',"positive":f["eps_surprise"]>=0},
        {"label":"Revenue surprise","value":f'{f["revenue_surprise"]*100:+.1f}%',"positive":f["revenue_surprise"]>=0},
        {"label":"Guidance tone","value":f'{f["guidance_score"]:+.2f}',"positive":f["guidance_score"]>=0},
        {"label":"Order-flow imbalance","value":f'{f["aggressor_imbalance"]:+.2f}',"positive":f["aggressor_imbalance"]>=0},
        {"label":"Transcript sentiment","value":f'{snap["transcript_sentiment"]:+.2f}',"positive":snap["transcript_sentiment"]>=0},
    ]
    record("analysis_created",symbol=symbol,signal=signal,data_mode="replay")
    return {"event":event_out(e),"signal":signal,"probability":round(probability,3),"bullish_probability":round(bullish,3),"expected_move_pct":expected,"quote":{"bid":q.bid,"ask":q.ask,"last":q.last,"timestamp":q.timestamp},"features":reasons,"market":{"spread_pct":round(snap["spread_pct"]*100,3),"relative_volume":snap["relative_volume"],"price_reaction_pct":round(snap["price_reaction"]*100,2)},"plan":{"target_pct":x.target_pct,"stop_pct":x.stop_pct,"forced_exit_at":next_regular_open(now)},"data_mode":"REPLAY","disclaimer":"Synthetic replay analysis for research and paper trading only; not investment advice."}
@app.post("/api/positions")
def enter(x:Enter):
    if x.side not in ("LONG","SHORT"): raise HTTPException(422,"side must be LONG or SHORT")
    with Session() as db:
        e=db.get(Event,x.event_id)
        if not e: raise HTTPException(404,"event not found")
        if e.signal=="WAIT": raise HTTPException(409,"WAIT signals cannot open a paper position")
        expected_side="LONG" if e.signal=="BUY" else "SHORT"
        if x.side!=expected_side: raise HTTPException(409,f"{e.signal} signal requires {expected_side} paper side")
        q=ReplayProvider().quote(e.symbol); price=q.ask if x.side=="LONG" else q.bid
        p=Position(event_id=e.id,side=x.side,quantity=x.quantity,entry_price=price,entry_at=q.timestamp,deadline=next_regular_open(q.timestamp),notes=json.dumps({"target_pct":x.target_pct,"stop_pct":x.stop_pct}))
        db.add(p);db.commit();record("paper_enter",position_id=p.id,symbol=e.symbol);return pos_out(p,e.symbol)
@app.post("/api/positions/{position_id}/exit")
def exit_now(position_id:int,x:Exit):
    with Session() as db:
        p=db.get(Position,position_id)
        if not p: raise HTTPException(404,"position not found")
        if p.exit_at: raise HTTPException(409,"position already closed")
        now=datetime.now(timezone.utc)
        deadline=p.deadline if p.deadline.tzinfo else p.deadline.replace(tzinfo=timezone.utc)
        if now>=deadline: raise HTTPException(409,"manual exit window closed; record a NEXT_SESSION_OPEN exit")
        p.exit_price=x.price;p.exit_at=now;p.exit_reason="MANUAL_EXIT";db.commit();record("paper_manual_exit",position_id=p.id);return pos_out(p)
@app.get("/",response_class=HTMLResponse)
def dashboard():
    return DASHBOARD

DASHBOARD='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Earnings Alpha</title><style>
:root{--bg:#07111f;--panel:#0d1a2b;--panel2:#11233a;--line:#203853;--muted:#8ea4bd;--text:#f4f7fb;--green:#20d49a;--red:#ff6077;--amber:#ffbd59;--blue:#5f8cff}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 85% 5%,#14294a 0,transparent 30%),var(--bg);color:var(--text);font:15px Inter,system-ui,sans-serif}header{height:70px;border-bottom:1px solid var(--line);display:flex;align-items:center;padding:0 max(24px,calc((100% - 1180px)/2));gap:16px;position:sticky;top:0;background:#07111fee;backdrop-filter:blur(14px);z-index:3}.logo{font-size:20px;font-weight:800}.logo b{color:var(--green)}.badge{font-size:11px;font-weight:800;padding:6px 9px;border-radius:99px;background:#17382f;color:var(--green);letter-spacing:.08em}nav{margin-left:auto;color:var(--muted)}main{max-width:1180px;margin:35px auto;padding:0 24px 50px}.hero h1{font-size:36px;margin:0 0 8px}.hero p{color:var(--muted);margin:0 0 18px}.feedbar{display:flex;gap:9px;flex-wrap:wrap;margin-bottom:22px}.feed{font-size:12px;padding:7px 10px;border:1px solid var(--line);border-radius:99px;color:var(--muted)}.feed.live{color:var(--green);border-color:#246c59}.card{background:linear-gradient(145deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:16px;padding:22px;box-shadow:0 18px 50px #0003}.search{display:grid;grid-template-columns:2fr 1.3fr .8fr .8fr auto auto;gap:12px}.field label{display:block;color:var(--muted);font-size:12px;margin:0 0 7px;text-transform:uppercase;letter-spacing:.06em}input,select{width:100%;background:#091625;border:1px solid #294561;color:white;padding:12px;border-radius:9px;font:inherit}button{border:0;border-radius:9px;padding:12px 18px;font-weight:800;cursor:pointer;background:var(--blue);color:white}button:disabled{opacity:.5}.analyze{align-self:end}.watch{align-self:end;background:#263d5e}.grid{display:grid;grid-template-columns:1.25fr .75fr;gap:18px;margin-top:18px}.hidden{display:none}.signal-head{display:flex;justify-content:space-between;align-items:flex-start}.signal{font-size:38px;font-weight:900}.BUY{color:var(--green)}.SELL{color:var(--red)}.WAIT{color:var(--amber)}.prob{text-align:right}.prob strong{font-size:30px}.muted{color:var(--muted)}.meter{height:8px;background:#21344a;border-radius:9px;overflow:hidden;margin:14px 0 20px}.meter i{display:block;height:100%;background:linear-gradient(90deg,var(--blue),var(--green));width:0}.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.metric{padding:14px;background:#0a1727;border-radius:11px}.metric span{font-size:12px;color:var(--muted);display:block}.metric b{font-size:18px}.factors{margin-top:18px}.factor{display:flex;justify-content:space-between;padding:11px 0;border-bottom:1px solid var(--line)}.pos{color:var(--green)}.neg{color:var(--red)}h2{font-size:18px;margin:0 0 16px}.planline{display:flex;justify-content:space-between;padding:12px 0;border-bottom:1px solid var(--line)}.paper{width:100%;margin-top:18px;background:var(--green);color:#03251a}.notice{font-size:12px;color:var(--muted);line-height:1.5;margin-top:13px}.section{margin-top:26px}.positions{display:grid;gap:12px}.position{display:grid;grid-template-columns:1fr repeat(4,.8fr) auto;gap:15px;align-items:center;background:var(--panel);border:1px solid var(--line);padding:16px;border-radius:13px}.position small{display:block;color:var(--muted)}.exit{background:var(--red)}.empty{text-align:center;color:var(--muted);padding:25px}.status{margin-top:10px;color:var(--muted);min-height:20px}@media(max-width:800px){.search,.grid{grid-template-columns:1fr}.position{grid-template-columns:1fr 1fr}.hero h1{font-size:29px}nav{display:none}}
</style></head><body><header><div class="logo">Earnings <b>Alpha</b></div><span class="badge">PAPER / REPLAY</span><nav>Analyze &nbsp; · &nbsp; Monitor &nbsp; · &nbsp; Positions</nav></header><main><section class="hero"><h1>Earnings event intelligence</h1><p>Analyze now or monitor every 10 seconds for a new result, guidance, volume and post-release price action.</p><div class="feedbar" id="feeds"></div></section><section class="card"><form class="search" id="form"><div class="field"><label>US stock symbol</label><input id="symbol" placeholder="e.g. NVDA" required maxlength="12" autocomplete="off"></div><div class="field"><label>Announcement session</label><select id="session"><option value="after_market">After market</option><option value="pre_market">Pre-market</option></select></div><div class="field"><label>Target</label><input id="target" type="number" value="5.5" min="0.1" max="50" step="0.1"></div><div class="field"><label>Stop</label><input id="stop" type="number" value="3.5" min="0.1" max="50" step="0.1"></div><button class="analyze" id="analyze">Analyze</button><button type="button" class="watch" id="watch">Auto-monitor</button></form><div class="status" id="status"></div></section>
<section class="grid hidden" id="result"><div class="card"><div class="signal-head"><div><div class="muted" id="resultSymbol"></div><div class="signal" id="signal"></div></div><div class="prob"><span class="muted">Model confidence</span><br><strong id="probability"></strong></div></div><div class="meter"><i id="meter"></i></div><div class="metrics"><div class="metric"><span>Expected move</span><b id="move"></b></div><div class="metric"><span>Reference price</span><b id="price"></b></div><div class="metric"><span>Data mode</span><b id="mode"></b></div></div><div class="factors"><h2>What drives this signal</h2><div id="factors"></div></div></div><div class="card"><h2>Paper trade plan</h2><div class="planline"><span>Entry window</span><b id="window"></b></div><div class="planline"><span>Profit target</span><b class="pos" id="planTarget"></b></div><div class="planline"><span>Stop loss</span><b class="neg" id="planStop"></b></div><div class="planline"><span>Forced exit</span><b id="deadline"></b></div><div class="field" style="margin-top:14px"><label>Paper quantity</label><input id="qty" type="number" value="10" min="1"></div><button class="paper" id="paper">Enter paper trade</button><p class="notice">Research and paper trading only. No broker is connected and no live order can be sent.</p></div></section>
<section class="section"><h2>Automatic result monitor</h2><div class="positions" id="watches"><div class="card empty">No symbols monitored yet.</div></div></section><section class="section"><h2>Positions & trade journal</h2><div class="positions" id="positions"><div class="card empty">No paper positions yet.</div></div></section></main><script>
let current=null;const $=id=>document.getElementById(id);const pct=n=>(n*100).toFixed(1)+'%';
$('form').onsubmit=async e=>{e.preventDefault();$('analyze').disabled=true;$('status').textContent='Analyzing earnings, order flow, spread and transcript factors…';try{let r=await fetch('/api/analyze',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({symbol:$('symbol').value.trim(),session:$('session').value,target_pct:+$('target').value/100,stop_pct:+$('stop').value/100})});let d=await r.json();if(!r.ok)throw Error(d.detail||'Analysis failed');current=d;$('result').classList.remove('hidden');$('resultSymbol').textContent=d.event.symbol+' · '+d.event.session.replace('_',' ')+' earnings';$('signal').textContent=d.signal;$('signal').className='signal '+d.signal;$('probability').textContent=pct(d.probability);$('meter').style.width=pct(d.probability);$('move').textContent=d.expected_move_pct.toFixed(2)+'%';$('price').textContent='$'+d.quote.last.toFixed(2);$('mode').textContent=d.data_mode;$('factors').innerHTML=d.features.map(x=>`<div class="factor"><span>${x.label}</span><b class="${x.positive?'pos':'neg'}">${x.value}</b></div>`).join('');$('window').textContent=d.event.session==='after_market'?'After-hours':'Pre-market';$('planTarget').textContent='+'+pct(d.plan.target_pct);$('planStop').textContent='−'+pct(d.plan.stop_pct);$('deadline').textContent=new Date(d.plan.forced_exit_at).toLocaleString();$('paper').disabled=d.signal==='WAIT';$('paper').textContent=d.signal==='WAIT'?'WAIT — no entry':'Enter '+(d.signal==='SELL'?'short':'long')+' paper trade';$('status').textContent=d.data_mode+' data · updated '+new Date(d.quote.timestamp).toLocaleTimeString()}catch(err){$('status').textContent=err.message}finally{$('analyze').disabled=false}};
$('paper').onclick=async()=>{if(!current)return;let r=await fetch('/api/positions',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({event_id:current.event.id,side:current.signal==='SELL'?'SHORT':'LONG',quantity:+$('qty').value,target_pct:current.plan.target_pct,stop_pct:current.plan.stop_pct})});let d=await r.json();if(r.ok){$('status').textContent='Paper position opened. No live order was sent.';loadPositions()}else{$('status').textContent=d.detail||'Could not open paper position'}};
$('watch').onclick=async()=>{let symbol=$('symbol').value.trim();if(!symbol){$('status').textContent='Enter a symbol first.';return}let r=await fetch('/api/watchlist',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({symbol,session:$('session').value})});let d=await r.json();$('status').textContent=r.ok?`${symbol.toUpperCase()} is now checked every ${d.provider.poll_interval_seconds} seconds in ${d.provider.mode} mode.`:(d.detail||'Could not create monitor');loadWatches()};
async function loadProviders(){let p=await(await fetch('/api/providers')).json();$('feeds').innerHTML=[['Market',p.market_data.configured],['Results + estimates',p.earnings_results.configured],['Transcript/news',p.transcripts_news.configured],['SEC/XBRL',p.sec_xbrl.configured]].map(x=>`<span class="feed ${x[1]?'live':''}">${x[1]?'● LIVE':'○ REPLAY'} · ${x[0]}</span>`).join('')}
async function loadWatches(){let ws=await(await fetch('/api/watchlist')).json();$('watches').innerHTML=ws.length?ws.map(w=>`<div class="position"><div><b>${w.symbol}</b><small>${w.session.replace('_',' ')}</small></div><div><b>${w.status}</b><small>Monitor status</small></div><div><b>${w.analysis.signal||'—'}</b><small>Latest signal</small></div><div><b>${w.analysis.eps_surprise==null?'—':(w.analysis.eps_surprise*100).toFixed(1)+'%'}</b><small>EPS surprise</small></div><div><b>${w.last_polled_at?new Date(w.last_polled_at).toLocaleTimeString():'—'}</b><small>Last 10-sec check</small></div><div><span class="badge">${w.analysis.source_mode||'WAITING'}</span></div></div>`).join(''):'<div class="card empty">No symbols monitored yet.</div>'}
async function loadPositions(){let ps=await(await fetch('/api/positions')).json();$('positions').innerHTML=ps.length?ps.map(x=>`<div class="position"><div><b>${x.symbol||'#'+x.id} · ${x.side}</b><small>Paper position #${x.id}</small></div><div><b>${x.quantity}</b><small>Shares</small></div><div><b>$${x.entry_price.toFixed(2)}</b><small>Entry</small></div><div><b>+${pct(x.target_pct)} / −${pct(x.stop_pct)}</b><small>Target / stop</small></div><div><b>${x.exit_reason||'OPEN'}</b><small>${new Date(x.deadline).toLocaleString()}</small></div>${x.exit_reason?'':`<button class="exit" onclick="quit(${x.id},${x.entry_price})">EXIT NOW</button>`}</div>`).join(''):'<div class="card empty">No paper positions yet. Analyze a symbol to begin.</div>'}
async function quit(id,price){let v=prompt('Paper exit price',price);if(!v)return;let r=await fetch('/api/positions/'+id+'/exit',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({price:+v})});let d=await r.json();if(!r.ok)alert(d.detail||'Exit failed');loadPositions()}loadProviders();loadPositions();loadWatches();setInterval(loadWatches,10000);
</script></body></html>'''

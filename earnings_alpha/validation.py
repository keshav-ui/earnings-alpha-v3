import argparse, json
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from .research import Bar, backtest, features
from datetime import datetime

KEYS=["eps_surprise","revenue_surprise","guidance_score","return_since_announcement","spread_pct","aggressor_imbalance","volume"]
def load(path):
    rows=[]
    for line in Path(path).read_text().splitlines():
        x=json.loads(line); bars=[Bar(datetime.fromisoformat(b["timestamp"]),**{k:b[k] for k in ("bid","ask","last","volume")}) for b in x["bars"]]
        f=features([b for b in bars if b.timestamp<=bars[0].timestamp],x["event"]); outcome=backtest(bars)
        rows.append((x["event"].get("announced_at",bars[0].timestamp.isoformat()),f,int(outcome.outcome=="TARGET"),outcome.return_pct))
    return sorted(rows,key=lambda r:r[0])
def run(rows):
    """Expanding-window folds: fit + choose threshold only before each unseen test block."""
    if len(rows)<18: raise ValueError("Need at least 18 chronological events for walk-forward validation")
    initial=max(12, len(rows)//2); block=max(3,(len(rows)-initial)//3); folds=[]
    for end in range(initial,len(rows),block):
        prior=rows[:end]; test=rows[end:min(end+block,len(rows))]
        cut=max(6,len(prior)*2//3); fit,valid=prior[:cut],prior[cut:]
        y=np.array([r[2] for r in fit])
        if len(set(y))<2 or len(valid)<2: continue
        model=CalibratedClassifierCV(LogisticRegression(max_iter=1000),cv=3).fit(np.array([[r[1][k] for k in KEYS] for r in fit]),y)
        candidates=np.arange(.5,.91,.05)
        def val_return(t):
            chosen=[r[3] for r in valid if model.predict_proba([[r[1][k] for k in KEYS]])[0,1]>=t]
            return np.mean(chosen) if chosen else -999
        threshold=float(max(candidates,key=val_return))
        probs=model.predict_proba(np.array([[r[1][k] for k in KEYS] for r in test]))[:,1]
        chosen=[r for r,p in zip(test,probs) if p>=threshold]
        folds.append({"fit_events":len(fit),"validation_events":len(valid),"test_events":len(test),"threshold":round(threshold,2),"selected":len(chosen),"win_rate":round(float(np.mean([r[2] for r in chosen])),4) if chosen else None,"mean_return":round(float(np.mean([r[3] for r in chosen])),5) if chosen else None})
    if not folds: raise ValueError("No valid folds: supply more historical wins and non-wins")
    return {"folds":folds,"warning":"Research result only; inspect data licensing, exchange calendar accuracy, survivorship, and out-of-sample stability."}
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--input",required=True);p.add_argument("--output",required=True);a=p.parse_args(); Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps(run(load(a.input)),indent=2))

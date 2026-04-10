"""
grade_results.py
================
Auto-grades yesterday's picks.json against today's OHLC, appends to journal.csv,
and nudges weights.json toward components that correlated with winning picks.

Run nightly BEFORE generate_picks.py so the new run benefits from the updated weights.
"""
from __future__ import annotations
import json, csv, sys, datetime as dt
from pathlib import Path

HERE=Path(__file__).parent
PICKS=HERE/"picks.json"
HIST=HERE/"picks_history.jsonl"   # append-only snapshot of every run
JOURNAL=HERE/"journal.csv"
WEIGHTS=HERE/"weights.json"

LR=0.05  # learning rate for weight nudges

try: import yfinance as yf
except Exception: yf=None

def log(m): print(f"[grade] {m}",flush=True)

def load(p,d):
    try:
        if p.exists(): return json.loads(p.read_text(encoding="utf-8"))
    except Exception: pass
    return d

def grade_pick(sym, entry, sl, tgt):
    """Pull today's OHLC, determine if target or stop hit first (approx: bar logic)."""
    if yf is None: return None
    try:
        df=yf.Ticker(sym+".NS").history(period="5d",interval="1d")
        if df is None or df.empty: return None
        row=df.iloc[-1]
        hi=float(row["High"]); lo=float(row["Low"]); cl=float(row["Close"])
        hit_tgt=hi>=tgt; hit_sl=lo<=sl
        if hit_tgt and hit_sl: outcome="ambiguous"  # both touched; conservative
        elif hit_tgt: outcome="win"
        elif hit_sl:  outcome="loss"
        else:         outcome="open" if cl<tgt and cl>sl else "eod"
        pnl_pct=(cl-entry)/entry*100
        return {"high":hi,"low":lo,"close":cl,"outcome":outcome,"pnl_pct":round(pnl_pct,2)}
    except Exception as e:
        log(f"grade {sym} err {e}"); return None

def main():
    picks=load(PICKS,None)
    if not picks: log("no picks.json yet; nothing to grade"); return
    # snapshot previous picks to history before regeneration
    with HIST.open("a",encoding="utf-8") as f:
        f.write(json.dumps({"snapshot_at":dt.datetime.now().isoformat(),"picks":picks})+"\n")

    W=load(WEIGHTS,None) or {"trend":0.25,"momentum":0.20,"volume":0.15,"breakout":0.15,
                              "volatility":0.10,"liquidity":0.05,"news":0.10}

    rows=[]; wins=0; losses=0; total_pnl=0.0
    for p in picks.get("top_picks",[])+picks.get("stretch_picks",[]):
        sym=p.get("symbol",""); entry=p.get("price",0)
        sl=p.get("stop_loss",p.get("sl",0)); tgt=p.get("target",0)
        if not sym or not entry: continue
        g=grade_pick(sym,entry,sl,tgt)
        if not g: continue
        if g["outcome"]=="win": wins+=1
        elif g["outcome"]=="loss": losses+=1
        total_pnl+=g["pnl_pct"]
        rows.append([picks.get("data_as_of",""),picks.get("trade_for",""),sym,entry,sl,tgt,
                     g["high"],g["low"],g["close"],g["outcome"],g["pnl_pct"],p.get("score",""),
                     p.get("news_catalyst") or ""])

    # append to journal
    write_header=not JOURNAL.exists()
    with JOURNAL.open("a",newline="",encoding="utf-8") as f:
        w=csv.writer(f)
        if write_header:
            w.writerow(["data_as_of","trade_for","symbol","entry","sl","tgt","high","low","close",
                        "outcome","pnl_pct","score","news_catalyst"])
        w.writerows(rows)

    log(f"graded {len(rows)}  wins={wins} losses={losses}  avg_pnl={total_pnl/max(1,len(rows)):.2f}%")

    # --- weight nudging ---
    # simple heuristic: if news picks outperformed non-news, bump news weight; same for momentum
    if rows:
        news_pnl=[r[10] for r in rows if r[12]]
        nonews_pnl=[r[10] for r in rows if not r[12]]
        if news_pnl and nonews_pnl:
            delta=(sum(news_pnl)/len(news_pnl))-(sum(nonews_pnl)/len(nonews_pnl))
            W["news"]=max(0.02,min(0.25,W["news"]+LR*(1 if delta>0 else -1)*0.02))
        win_rate=wins/max(1,wins+losses)
        if win_rate>0.55:
            W["momentum"]=min(0.30,W["momentum"]+LR*0.01)
            W["trend"]=min(0.35,W["trend"]+LR*0.01)
        elif win_rate<0.45:
            W["volatility"]=min(0.20,W["volatility"]+LR*0.01)
            W["liquidity"]=min(0.15,W["liquidity"]+LR*0.01)
        # renormalize
        s=sum(W.values()); W={k:round(v/s,4) for k,v in W.items()}
        WEIGHTS.write_text(json.dumps(W,indent=2),encoding="utf-8")
        log(f"updated weights -> {W}")

if __name__=="__main__":
    try: main()
    except Exception as e:
        import traceback; traceback.print_exc(); sys.exit(0)  # never block the pipeline

"""
NSE Paper-Trading Picks Generator (v3)
=======================================
- Scans the FULL NSE equity universe (~2000 symbols) via EQUITY_L.csv
- Uses nsepython LIVE quotes as source of truth for price (matches Groww)
- yfinance used for historical OHLC (technicals)
- Reads news.json (auto-fetched by news_fetch step) to boost catalyst tickers
- Reads weights.json (updated by grade_results.py) so the bot LEARNS
- Outputs picks.json labelled with data_as_of (today close) and trade_for (next session)

PAPER TRADING ONLY. Not investment advice.
"""
from __future__ import annotations
import json, math, time, sys, traceback, datetime as dt
from pathlib import Path

HERE = Path(__file__).parent
PICKS_FILE   = HERE / "picks.json"
NEWS_FILE    = HERE / "news.json"
WEIGHTS_FILE = HERE / "weights.json"

CAPITAL=1000.0; RISK_PER_TRADE=50.0; ATR_SL_MULT=1.0; RR=2.0; TOP_N=6
MIN_PRICE=5.0; MAX_PRICE=5000.0; MIN_AVG_VOL=200_000; HIST_DAYS=120

DEFAULT_WEIGHTS = {"trend":0.20,"momentum":0.18,"volume":0.12,"breakout":0.13,
                   "volatility":0.08,"liquidity":0.04,"news":0.10,
                   "stoch":0.05,"bbands":0.05,"gap":0.03,"sentiment":0.02}

# Groww intraday (MIS) cost model — round-trip, rough
# brokerage: min(20, 0.03% of turnover) per leg; STT 0.025% on sell;
# exch txn 0.00345%; GST 18% on (brok+exch); SEBI 0.0001%; stamp 0.003% on buy
def groww_roundtrip_cost(price, qty):
    turnover_buy = price*qty; turnover_sell = price*qty
    brok = min(20, 0.0003*turnover_buy) + min(20, 0.0003*turnover_sell)
    stt = 0.00025*turnover_sell
    exch = 0.0000345*(turnover_buy+turnover_sell)
    gst = 0.18*(brok+exch)
    sebi = 0.000001*(turnover_buy+turnover_sell)
    stamp = 0.00003*turnover_buy
    return round(brok+stt+exch+gst+sebi+stamp, 2)

def log(m): print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)
def load_json(p,d):
    try:
        if p.exists(): return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e: log(f"warn: read {p.name}: {e}")
    return d
def next_trading_day(d):
    nd=d+dt.timedelta(days=1)
    while nd.weekday()>=5: nd+=dt.timedelta(days=1)
    return nd

def prev_trading_day(d):
    pd_=d-dt.timedelta(days=1)
    while pd_.weekday()>=5: pd_-=dt.timedelta(days=1)
    return pd_

try:
    import pandas as pd, numpy as np
except Exception as e:
    print(f"FATAL pandas/numpy: {e}"); sys.exit(2)
try: import yfinance as yf
except Exception: yf=None
try: from nsepython import nse_eq
except Exception: nse_eq=None

def ema(s,n): return s.ewm(span=n,adjust=False).mean()
def rsi(s,n=14):
    d=s.diff(); up=d.clip(lower=0).rolling(n).mean()
    dn=(-d.clip(upper=0)).rolling(n).mean()
    rs=up/dn.replace(0,np.nan); return 100-100/(1+rs)
def atr(df,n=14):
    h,l,c=df["High"],df["Low"],df["Close"]
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.rolling(n).mean()
def stoch_k(df,n=14):
    h,l,c=df["High"],df["Low"],df["Close"]
    ll=l.rolling(n).min(); hh=h.rolling(n).max()
    return 100*(c-ll)/(hh-ll).replace(0,np.nan)
def bbands(s,n=20,k=2):
    m=s.rolling(n).mean(); sd=s.rolling(n).std()
    return m, m+k*sd, m-k*sd

def fetch_full_nse_universe():
    try:
        import requests
        r=requests.get("https://archives.nseindia.com/content/equities/EQUITY_L.csv",
                       headers={"User-Agent":"Mozilla/5.0"},timeout=20)
        if r.status_code==200:
            syms=[ln.split(",")[0].strip() for ln in r.text.splitlines()[1:] if ln.strip()]
            syms=[s for s in syms if s]
            log(f"Loaded {len(syms)} symbols from EQUITY_L.csv")
            return syms
    except Exception as e:
        log(f"EQUITY_L fetch failed: {e}")
    log("Falling back to curated 70-symbol list")
    return ["RELIANCE","TCS","INFY","HDFCBANK","ICICIBANK","SBIN","ITC","LT","HINDUNILVR",
            "BHARTIARTL","KOTAKBANK","AXISBANK","BAJFINANCE","MARUTI","ONGC","COALINDIA",
            "NTPC","POWERGRID","TATAMOTORS","TATASTEEL","JSWSTEEL","HINDALCO","WIPRO",
            "HCLTECH","TECHM","SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","BAJAJFINSV",
            "ADANIENT","ADANIPORTS","TITAN","NESTLEIND","BRITANNIA","ASIANPAINT","ULTRACEMCO",
            "GRASIM","EICHERMOT","HEROMOTOCO","M&M","BAJAJ-AUTO","BPCL","IOC","GAIL",
            "PNB","BANKBARODA","CANBK","IDFCFIRSTB","FEDERALBNK","IDEA","YESBANK","SUZLON",
            "BHEL","HAL","BEL","MAZDOCK","BDL","GRSE","COCHINSHIP","IRFC","RVNL","NHPC",
            "SJVN","IREDA","NBCC","RAILTEL","IRCTC","NMDC","SAIL","VEDL","DLF"]

def nse_live_price(sym):
    if nse_eq is None: return None
    try:
        q=nse_eq(sym); ltp=q.get("priceInfo",{}).get("lastPrice")
        return float(ltp) if ltp else None
    except Exception: return None

def yf_history(sym,days=HIST_DAYS):
    if yf is None: return None
    try:
        df=yf.Ticker(sym+".NS").history(period=f"{days+30}d",interval="1d",auto_adjust=False)
        if df is None or df.empty or len(df)<30: return None
        return df.tail(days).rename(columns=str.title)
    except Exception: return None

def score_stock(sym,df,ltp,news_hit,sentiment,W):
    try:
        close=df["Close"]; vol=df["Volume"]; op=df["Open"]
        if close.isna().any() or len(close)<30: return None
        last=float(close.iloc[-1])
        price=ltp if ltp else last
        if not (MIN_PRICE<=price<=MAX_PRICE): return None
        avg20=float(vol.tail(20).mean() or 0)
        if avg20<MIN_AVG_VOL: return None
        e20=ema(close,20).iloc[-1]; e50=ema(close,50).iloc[-1]
        r14=float(rsi(close,14).iloc[-1]); a14=float(atr(df,14).iloc[-1])
        hi20=float(close.tail(20).max()); lo20=float(close.tail(20).min())
        ret5=(last/close.iloc[-6]-1)*100 if len(close)>6 else 0
        ret20=(last/close.iloc[-21]-1)*100 if len(close)>21 else 0
        vr=float(vol.iloc[-1])/(avg20 or 1)
        k14=float(stoch_k(df,14).iloc[-1]) if len(df)>14 else 50
        bm,bu,bl=bbands(close,20,2)
        bm_v=float(bm.iloc[-1]); bu_v=float(bu.iloc[-1]); bl_v=float(bl.iloc[-1])
        bb_pos=(last-bl_v)/max(bu_v-bl_v,1e-9)  # 0=lower, 1=upper
        gap_pct=(float(op.iloc[-1])-float(close.iloc[-2]))/float(close.iloc[-2])*100 if len(close)>1 else 0

        # component scores
        trend=100 if (e20>e50 and last>e20) else (50 if last>e50 else 10)
        mom=max(0,min(100,50+ret5*4+ret20*1.5))
        vols=max(0,min(100,40+(vr-1)*50))
        brk=100 if last>=hi20*0.995 else (60 if last>=hi20*0.97 else 25)
        volat=100 if (a14 and 0.8<(a14/last*100)<4.5) else 40
        liq=max(0,min(100,math.log10(avg20+1)*15))
        news_s=100 if news_hit else 0
        # Stochastic: reward bullish zone but not overbought
        stoch_s=100 if 40<k14<80 else (60 if k14<=40 else 30)
        # Bollinger: reward upper half but not at extreme
        bb_s=100 if 0.55<bb_pos<0.95 else (50 if bb_pos>=0.95 else 30)
        # Gap: reward gap-up 0.5-3%, penalize huge gaps or gap-down
        gap_s=100 if 0.5<gap_pct<3 else (60 if 0<=gap_pct<=0.5 else (20 if gap_pct<0 else 40))
        sent_s=max(0,min(100,50+sentiment*25))  # sentiment in [-2,+2]

        score=(W["trend"]*trend+W["momentum"]*mom+W["volume"]*vols+W["breakout"]*brk+
               W["volatility"]*volat+W["liquidity"]*liq+W["news"]*news_s+
               W.get("stoch",0)*stoch_s+W.get("bbands",0)*bb_s+
               W.get("gap",0)*gap_s+W.get("sentiment",0)*sent_s)

        sl=round(price-ATR_SL_MULT*a14,2); tgt=round(price+RR*ATR_SL_MULT*a14,2)
        rps=max(price-sl,0.01); qty=max(1,int(RISK_PER_TRADE/rps))
        cap=round(qty*price,2)

        # strategy tag
        tags=[]
        if last>=hi20*0.995: tags.append("BREAKOUT")
        if ret5>3 and vr>1.3: tags.append("MOMENTUM")
        if abs(gap_pct)>=0.7: tags.append("GAP-AND-GO")
        if a14/last*100<1.2: tags.append("SCALP")
        strategy="/".join(tags) if tags else "SWING-INTRADAY"

        # cost-aware net R:R
        cost=groww_roundtrip_cost(price,qty)
        gross_profit=(tgt-price)*qty
        net_profit=round(gross_profit-cost,2)
        gross_loss=(price-sl)*qty
        net_loss=round(gross_loss+cost,2)
        net_rr=round(net_profit/max(net_loss,0.01),2)
        # require cost < 25% of gross profit — else skip (costs eat edge)
        if cost>0.25*gross_profit: return None

        return {"symbol":sym,"price":round(price,2),
                "entry_zone":f"{round(price*0.998,2)} - {round(price*1.004,2)}",
                "stop_loss":sl,"target":tgt,"qty":qty,"capital_needed":cap,
                "fits_budget":cap<=CAPITAL,"score":round(score,1),
                "strategy":strategy,
                "rsi":round(r14,1),"stoch_k":round(k14,1),
                "bb_position":round(bb_pos,2),"gap_pct":round(gap_pct,2),
                "atr_pct":round(a14/price*100,2),"vol_ratio":round(vr,2),
                "ret5d_pct":round(ret5,2),"ret20d_pct":round(ret20,2),
                "near_20d_high":bool(last>=hi20*0.995),
                "news_catalyst":news_hit or None,
                "sentiment_score":round(sentiment,2),
                "cost_roundtrip":cost,"net_profit":net_profit,
                "net_loss":net_loss,"net_rr":net_rr,
                "source":"nse_live+yf_hist" if ltp else "yf_only"}
    except Exception: return None

def main():
    log("=== NSE Picks Generator v3 ===")
    now=dt.datetime.now()
    today=now.date()
    # IST market closes at 15:30. If run before market close, picks are for TODAY's session.
    # If run after market close, picks are for the next trading day.
    market_close=now.replace(hour=15,minute=30,second=0,microsecond=0)
    if now<market_close and today.weekday()<5:
        trade_for=today
        data_as_of=prev_trading_day(today)
        log(f"Pre-market run: picks for today's session ({trade_for}), data from prev close ({data_as_of})")
    else:
        trade_for=next_trading_day(today)
        data_as_of=today
        log(f"Post-market run: picks for next session ({trade_for}), data from today's close ({data_as_of})")
    W=load_json(WEIGHTS_FILE,DEFAULT_WEIGHTS)
    news=load_json(NEWS_FILE,{"items":[],"fetched_at":None})
    news_map={(i.get("symbol") or "").upper():i.get("headline","") for i in news.get("items",[]) if i.get("symbol")}
    sent_map={(i.get("symbol") or "").upper():float(i.get("sentiment",0)) for i in news.get("items",[]) if i.get("symbol")}
    log(f"Weights: {W}")
    log(f"News-tagged tickers: {len(news_map)}")
    universe=fetch_full_nse_universe()
    log(f"Universe: {len(universe)}  (this will take ~8-15 min)")
    picks=[]; skipped=0; t0=time.time()
    for i,sym in enumerate(universe,1):
        if i%50==0:
            log(f"  {i}/{len(universe)}  kept={len(picks)} skipped={skipped} elapsed={int(time.time()-t0)}s")
        df=yf_history(sym)
        if df is None: skipped+=1; continue
        ltp=nse_live_price(sym)
        p=score_stock(sym,df,ltp,news_map.get(sym.upper()),sent_map.get(sym.upper(),0),W)
        if p: picks.append(p)
        else: skipped+=1
    picks.sort(key=lambda x:x["score"],reverse=True)
    top=[p for p in picks if p["fits_budget"]][:TOP_N]
    stretch=[p for p in picks if not p["fits_budget"]][:TOP_N]
    out={"generated_at":dt.datetime.now().isoformat(timespec="seconds"),
         "data_as_of":data_as_of.isoformat(),"trade_for":trade_for.isoformat(),
         "universe_size":len(universe),"scored":len(picks),"skipped":skipped,
         "weights":W,"news_count":len(news_map),
         "top_picks":top,"stretch_picks":stretch,
         "disclaimer":"Paper-trading only. Not investment advice. ~70% of NSE intraday traders lose money (SEBI)."}
    PICKS_FILE.write_text(json.dumps(out,indent=2),encoding="utf-8")
    log(f"Wrote {PICKS_FILE}  top={len(top)} stretch={len(stretch)} trade_for={trade_for}")
    # Inject data into dashboard.html so it works from file:// (no fetch needed)
    dash=HERE/"dashboard.html"
    if dash.exists():
        html=dash.read_text(encoding="utf-8")
        import re
        replacement=f"// %%PICKS_DATA_START%%\nconst LIVE_DATA = {json.dumps(out)};\n// %%PICKS_DATA_END%%"
        html=re.sub(r"// %%PICKS_DATA_START%%.*?// %%PICKS_DATA_END%%",lambda _: replacement,html,flags=re.DOTALL)
        dash.write_text(html,encoding="utf-8")
        log("Injected picks into dashboard.html")

if __name__=="__main__":
    try: main()
    except Exception:
        traceback.print_exc(); sys.exit(1)

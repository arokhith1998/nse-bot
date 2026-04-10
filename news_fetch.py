"""
news_fetch.py
=============
Fetches latest India + global market headlines from free RSS feeds,
extracts NSE tickers mentioned, writes news.json consumed by generate_picks.py.

Sources (all RSS, no API key):
  - Moneycontrol top news
  - Economic Times markets
  - LiveMint markets
  - Reuters business
  - Business Standard markets

Ticker matching: scans headline+summary for known NSE symbols & company names.
Run nightly before generate_picks.py.
"""
from __future__ import annotations
import json, re, sys, datetime as dt
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

HERE=Path(__file__).parent
OUT=HERE/"news.json"

FEEDS=[
    ("Moneycontrol","https://www.moneycontrol.com/rss/MCtopnews.xml"),
    ("ET Markets","https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("LiveMint Markets","https://www.livemint.com/rss/markets"),
    ("Business Standard","https://www.business-standard.com/rss/markets-106.rss"),
    ("Reuters Business","https://feeds.reuters.com/reuters/businessNews"),
]

# alias -> NSE symbol
ALIASES={
    "reliance":"RELIANCE","ril":"RELIANCE","tcs":"TCS","infosys":"INFY","infy":"INFY",
    "hdfc bank":"HDFCBANK","icici":"ICICIBANK","sbi":"SBIN","state bank":"SBIN",
    "itc":"ITC","l&t":"LT","larsen":"LT","hul":"HINDUNILVR","hindustan unilever":"HINDUNILVR",
    "airtel":"BHARTIARTL","bharti":"BHARTIARTL","kotak":"KOTAKBANK","axis bank":"AXISBANK",
    "bajaj finance":"BAJFINANCE","maruti":"MARUTI","ongc":"ONGC","coal india":"COALINDIA",
    "ntpc":"NTPC","powergrid":"POWERGRID","power grid":"POWERGRID","tata motors":"TMPV",
    "tata steel":"TATASTEEL","jsw steel":"JSWSTEEL","hindalco":"HINDALCO","wipro":"WIPRO",
    "hcl":"HCLTECH","tech mahindra":"TECHM","sun pharma":"SUNPHARMA","dr reddy":"DRREDDY",
    "cipla":"CIPLA","divis":"DIVISLAB","bajaj finserv":"BAJAJFINSV","adani enterprises":"ADANIENT",
    "adani ports":"ADANIPORTS","titan":"TITAN","nestle":"NESTLEIND","britannia":"BRITANNIA",
    "asian paints":"ASIANPAINT","ultratech":"ULTRACEMCO","grasim":"GRASIM","eicher":"EICHERMOT",
    "hero motocorp":"HEROMOTOCO","m&m":"M&M","mahindra":"M&M","bajaj auto":"BAJAJ-AUTO",
    "bpcl":"BPCL","ioc":"IOC","indian oil":"IOC","gail":"GAIL","pnb":"PNB","punjab national":"PNB",
    "bank of baroda":"BANKBARODA","canara":"CANBK","federal bank":"FEDERALBNK",
    "vodafone idea":"IDEA","vi ":"IDEA","yes bank":"YESBANK","suzlon":"SUZLON","bhel":"BHEL",
    "hal":"HAL","hindustan aeronautics":"HAL","bel":"BEL","bharat electronics":"BEL",
    "mazagon":"MAZDOCK","bharat dynamics":"BDL","cochin shipyard":"COCHINSHIP","irfc":"IRFC",
    "rvnl":"RVNL","nhpc":"NHPC","sjvn":"SJVN","ireda":"IREDA","nbcc":"NBCC","railtel":"RAILTEL",
    "irctc":"IRCTC","nmdc":"NMDC","sail":"SAIL","vedanta":"VEDL","dlf":"DLF","lodha":"LODHA",
    "nuclear":"NTPC","pfbr":"NTPC","kalpakkam":"NTPC",  # nuclear-theme proxy
    "defence":"HAL","defense":"HAL",
}

def fetch_rss(url, timeout=15):
    try:
        req=Request(url,headers={"User-Agent":"Mozilla/5.0"})
        with urlopen(req,timeout=timeout) as r: data=r.read()
        root=ET.fromstring(data)
        items=[]
        for it in root.iter("item"):
            t=(it.findtext("title") or "").strip()
            d=(it.findtext("description") or "").strip()
            items.append(t+" — "+d)
        return items
    except Exception as e:
        print(f"[news] {url} failed: {e}"); return []

POS_WORDS=["surge","jump","rally","gain","beat","upgrade","record","profit","growth","bullish","outperform","buy","boost","strong","soar","rise","win","approval","expansion","hike"]
NEG_WORDS=["plunge","fall","drop","miss","downgrade","loss","weak","bearish","sell","probe","fine","penalty","fraud","decline","slump","cut","lay off","layoff","crash","raid","default"]

def score_sentiment(text):
    t=text.lower()
    pos=sum(1 for w in POS_WORDS if w in t)
    neg=sum(1 for w in NEG_WORDS if w in t)
    if pos==0 and neg==0: return 0.0
    return max(-2.0,min(2.0,(pos-neg)))

def match_tickers(text):
    t=text.lower(); hits=set()
    for alias,sym in ALIASES.items():
        if alias in t: hits.add(sym)
    return hits

def main():
    all_items=[]; per_ticker={}
    for name,url in FEEDS:
        headlines=fetch_rss(url)
        print(f"[news] {name}: {len(headlines)} headlines")
        for h in headlines:
            s=score_sentiment(h)
            for sym in match_tickers(h):
                per_ticker.setdefault(sym,[]).append({"source":name,"headline":h[:240],"sentiment":s})
    items=[]
    for sym,lst in per_ticker.items():
        avg_sent=sum(x["sentiment"] for x in lst)/len(lst)
        items.append({"symbol":sym,"headline":lst[0]["headline"],"source":lst[0]["source"],
                      "count":len(lst),"sentiment":round(avg_sent,2)})
    out={"fetched_at":dt.datetime.now().isoformat(timespec="seconds"),"items":items}
    OUT.write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(f"[news] wrote {OUT}  tickers_tagged={len(items)}")

if __name__=="__main__":
    try: main()
    except Exception as e:
        import traceback; traceback.print_exc(); sys.exit(0)

"""
refresh_news.py
===============
Lightweight Monday-morning script:
  1. Re-fetches latest news (catches weekend headlines)
  2. Re-scores existing picks with updated news/sentiment
  3. Re-injects into dashboard.html

Run this instead of the full 90-min scan when you already have
Friday evening's picks and just want to update news catalysts.
"""
from __future__ import annotations
import json, re, datetime as dt
from pathlib import Path

HERE = Path(__file__).parent
PICKS_FILE = HERE / "picks.json"
NEWS_FILE  = HERE / "news.json"
DASH_FILE  = HERE / "dashboard.html"

def log(m): print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

def main():
    log("=== News Refresh (quick update) ===")

    # Step 1: re-fetch news
    log("Fetching latest news...")
    import subprocess, sys
    rc = subprocess.call([sys.executable, str(HERE / "news_fetch.py")])
    if rc != 0:
        log("WARNING: news_fetch.py had errors, continuing with whatever was saved")

    # Step 2: load existing picks and fresh news
    if not PICKS_FILE.exists():
        log("ERROR: picks.json not found. Run run.bat first for a full scan.")
        return
    picks = json.loads(PICKS_FILE.read_text(encoding="utf-8"))
    news = json.loads(NEWS_FILE.read_text(encoding="utf-8")) if NEWS_FILE.exists() else {"items":[]}

    news_map = {(i.get("symbol") or "").upper(): i.get("headline","") for i in news.get("items",[]) if i.get("symbol")}
    sent_map = {(i.get("symbol") or "").upper(): float(i.get("sentiment",0)) for i in news.get("items",[]) if i.get("symbol")}
    log(f"News-tagged tickers: {len(news_map)}")

    # Step 3: update news_catalyst and sentiment in existing picks
    updated = 0
    for pick_list in [picks.get("top_picks",[]), picks.get("stretch_picks",[])]:
        for p in pick_list:
            sym = p["symbol"].upper()
            old_cat = p.get("news_catalyst")
            new_cat = news_map.get(sym) or None
            new_sent = sent_map.get(sym, 0)
            if new_cat != old_cat or new_sent != p.get("sentiment_score", 0):
                p["news_catalyst"] = new_cat
                p["sentiment_score"] = round(new_sent, 2)
                updated += 1

    # Update metadata
    now = dt.datetime.now()
    today = now.date()
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    if now < market_close and today.weekday() < 5:
        picks["trade_for"] = today.isoformat()
    picks["news_count"] = len(news_map)
    picks["news_refreshed_at"] = now.isoformat(timespec="seconds")

    # Step 4: save updated picks
    PICKS_FILE.write_text(json.dumps(picks, indent=2), encoding="utf-8")
    log(f"Updated {updated} picks with fresh news/sentiment")

    # Step 5: re-inject into dashboard.html
    if DASH_FILE.exists():
        html = DASH_FILE.read_text(encoding="utf-8")
        replacement = f"// %%PICKS_DATA_START%%\nconst LIVE_DATA = {json.dumps(picks)};\n// %%PICKS_DATA_END%%"
        html = re.sub(r"// %%PICKS_DATA_START%%.*?// %%PICKS_DATA_END%%", lambda _: replacement, html, flags=re.DOTALL)
        DASH_FILE.write_text(html, encoding="utf-8")
        log("Injected into dashboard.html")

    log("Done! Open dashboard.html to see updated picks with weekend news.")

if __name__ == "__main__":
    try: main()
    except Exception:
        import traceback; traceback.print_exc()

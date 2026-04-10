# NSE Paper-Trading Bot — v3

**Paper trading only. Not investment advice. ~70% of NSE intraday traders lose money (SEBI).**

## What it does
1. **Grades** yesterday's picks against today's OHLC (journal.csv) and nudges `weights.json` toward what worked — the bot learns.
2. **Fetches news** from Moneycontrol, ET Markets, LiveMint, Business Standard, Reuters RSS feeds, matches NSE tickers in headlines, writes `news.json`.
3. **Scans the full NSE equity universe** (~2000 symbols via EQUITY_L.csv) using yfinance for history and `nsepython` for **live LTP** (matches Groww to the paise).
4. **Scores** each stock on trend, momentum, volume, breakout, volatility, liquidity, and news catalyst (weights from the learning loop).
5. **Outputs** `picks.json` labelled with:
   - `data_as_of` = today's close
   - `trade_for`  = next trading session (what you actually trade)
6. **Dashboard** (`dashboard.html`) auto-loads picks.json and shows top 6 that fit ₹1,000 capital + 6 stretch picks.

## Daily run
Double-click **run.bat** after 7 PM IST (EOD data settled). Full run takes 8–15 minutes.

Steps run in order: `grade_results.py → news_fetch.py → generate_picks.py → open dashboard.html`

## Files
| File | Purpose |
|------|---------|
| `generate_picks.py` | Main scanner/scorer |
| `grade_results.py` | Learning loop — grades prior picks, updates weights |
| `news_fetch.py` | Pulls RSS headlines, tags tickers |
| `picks.json` | Latest picks (consumed by dashboard) |
| `news.json` | Latest news-tagged tickers |
| `weights.json` | Current scoring weights (auto-tuned) |
| `journal.csv` | Append-only trade log with outcomes |
| `picks_history.jsonl` | Every historical picks snapshot |
| `dashboard.html` | Interactive viewer |
| `run.bat` | One-click runner |

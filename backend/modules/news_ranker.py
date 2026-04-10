"""
news_ranker.py
==============
Advanced news scoring engine for the NSE Market Intelligence platform.

Replaces the binary news-hit approach with a weighted multi-factor impact score
that decays over time and adjusts based on price follow-through.

Preserves the original RSS feed sources from ``news_fetch.py`` and layers
structured scoring on top.

Usage:
    from backend.modules.news_ranker import NewsRanker

    ranker = NewsRanker()
    news   = ranker.fetch_all_news()
    impact = ranker.rank_news_for_symbol("RELIANCE", news)
"""
from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FRESHNESS_HALF_LIFE_HOURS = 4.0
PRICE_FOLLOW_THROUGH_THRESHOLD_PCT = 0.5
PRICE_FOLLOW_THROUGH_WINDOW_HOURS = 2.0

# ---------------------------------------------------------------------------
# Source quality scores  (0.0 - 1.0)
# ---------------------------------------------------------------------------

SOURCE_QUALITY: Dict[str, float] = {
    "Reuters Business": 1.0,
    "Bloomberg": 1.0,
    "Moneycontrol": 0.80,
    "ET Markets": 0.75,
    "LiveMint Markets": 0.72,
    "Business Standard": 0.70,
    "CNBC-TV18": 0.75,
    "NDTV Profit": 0.65,
    "Zee Business": 0.55,
    "unknown": 0.40,
}

# ---------------------------------------------------------------------------
# Event type weights  (0.0 - 1.0)
# ---------------------------------------------------------------------------

EVENT_TYPE_PATTERNS: List[Tuple[str, float]] = [
    # (regex pattern, weight)
    (r"\bm&a\b|\bmerger\b|\bacquisition\b|\btakeover\b|\bbuyout\b", 0.95),
    (r"\bearnings?\b|\bquarterly results?\b|\bq[1-4]\b|\bprofit\b|\bnet income\b", 0.90),
    (r"\bregulat\w+\b|\bsebi\b|\brbi\b|\bcompliance\b|\bpolicy\b|\bban\b", 0.85),
    (r"\bdividend\b|\bbuyback\b|\bbonus\b|\bsplit\b", 0.80),
    (r"\bupgrade\b|\bdowngrade\b|\btarget price\b|\brating\b", 0.78),
    (r"\bipo\b|\blisting\b|\boffer for sale\b|\bofs\b", 0.75),
    (r"\bcontract\b|\border\b|\bdeal\b|\baward\b", 0.72),
    (r"\bexpansion\b|\bcapex\b|\bnew plant\b|\bcapacity\b", 0.68),
    (r"\bfraud\b|\braid\b|\barrest\b|\bscam\b|\bdefault\b", 0.92),
    (r"\bglobal\b|\bfed\b|\bwall street\b|\bus market\b|\bchina\b", 0.50),
    (r"\bsector\b|\bindustry\b", 0.55),
]

# ---------------------------------------------------------------------------
# RSS feeds (preserved from news_fetch.py)
# ---------------------------------------------------------------------------

FEEDS: List[Tuple[str, str]] = [
    ("Moneycontrol", "https://www.moneycontrol.com/rss/MCtopnews.xml"),
    ("ET Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("LiveMint Markets", "https://www.livemint.com/rss/markets"),
    ("Business Standard", "https://www.business-standard.com/rss/markets-106.rss"),
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
]

# ---------------------------------------------------------------------------
# Ticker aliases (preserved from news_fetch.py)
# ---------------------------------------------------------------------------

ALIASES: Dict[str, str] = {
    "reliance": "RELIANCE", "ril": "RELIANCE", "tcs": "TCS",
    "infosys": "INFY", "infy": "INFY", "hdfc bank": "HDFCBANK",
    "icici": "ICICIBANK", "sbi": "SBIN", "state bank": "SBIN",
    "itc": "ITC", "l&t": "LT", "larsen": "LT",
    "hul": "HINDUNILVR", "hindustan unilever": "HINDUNILVR",
    "airtel": "BHARTIARTL", "bharti": "BHARTIARTL",
    "kotak": "KOTAKBANK", "axis bank": "AXISBANK",
    "bajaj finance": "BAJFINANCE", "maruti": "MARUTI",
    "ongc": "ONGC", "coal india": "COALINDIA",
    "ntpc": "NTPC", "powergrid": "POWERGRID", "power grid": "POWERGRID",
    "tata motors": "TATAMOTORS", "tata steel": "TATASTEEL",
    "jsw steel": "JSWSTEEL", "hindalco": "HINDALCO", "wipro": "WIPRO",
    "hcl": "HCLTECH", "tech mahindra": "TECHM",
    "sun pharma": "SUNPHARMA", "dr reddy": "DRREDDY",
    "cipla": "CIPLA", "divis": "DIVISLAB", "bajaj finserv": "BAJAJFINSV",
    "adani enterprises": "ADANIENT", "adani ports": "ADANIPORTS",
    "titan": "TITAN", "nestle": "NESTLEIND", "britannia": "BRITANNIA",
    "asian paints": "ASIANPAINT", "ultratech": "ULTRACEMCO",
    "grasim": "GRASIM", "eicher": "EICHERMOT",
    "hero motocorp": "HEROMOTOCO", "m&m": "M&M", "mahindra": "M&M",
    "bajaj auto": "BAJAJ-AUTO", "bpcl": "BPCL",
    "ioc": "IOC", "indian oil": "IOC", "gail": "GAIL",
    "pnb": "PNB", "punjab national": "PNB",
    "bank of baroda": "BANKBARODA", "canara": "CANBK",
    "federal bank": "FEDERALBNK", "vodafone idea": "IDEA",
    "vi ": "IDEA", "yes bank": "YESBANK", "suzlon": "SUZLON",
    "bhel": "BHEL", "hal": "HAL", "hindustan aeronautics": "HAL",
    "bel": "BEL", "bharat electronics": "BEL",
    "mazagon": "MAZDOCK", "bharat dynamics": "BDL",
    "cochin shipyard": "COCHINSHIP", "irfc": "IRFC",
    "rvnl": "RVNL", "nhpc": "NHPC", "sjvn": "SJVN",
    "ireda": "IREDA", "nbcc": "NBCC", "railtel": "RAILTEL",
    "irctc": "IRCTC", "nmdc": "NMDC", "sail": "SAIL",
    "vedanta": "VEDL", "dlf": "DLF", "lodha": "LODHA",
}

# Sentiment words (from news_fetch.py)
POS_WORDS = [
    "surge", "jump", "rally", "gain", "beat", "upgrade", "record", "profit",
    "growth", "bullish", "outperform", "buy", "boost", "strong", "soar",
    "rise", "win", "approval", "expansion", "hike",
]
NEG_WORDS = [
    "plunge", "fall", "drop", "miss", "downgrade", "loss", "weak", "bearish",
    "sell", "probe", "fine", "penalty", "fraud", "decline", "slump", "cut",
    "lay off", "layoff", "crash", "raid", "default",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RankedNews:
    """A single news item with all scoring components."""
    headline: str
    source: str
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    matched_symbols: List[str] = field(default_factory=list)

    # scoring components (each 0.0 - 1.0 unless noted)
    source_quality: float = 0.5
    event_type_weight: float = 0.5
    sentiment_magnitude: float = 0.5   # raw sentiment in [-2,+2] scaled to [0,1]
    raw_sentiment: float = 0.0         # original [-2,+2]
    freshness_score: float = 1.0
    ticker_specificity: float = 0.5
    materiality: float = 0.5
    multi_source_score: float = 0.0

    weighted_impact: float = 0.0       # final composite
    price_follow_through: bool = True  # set to False if price didn't confirm
    decayed: bool = False              # True once intraday decay has been applied


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_rss(url: str, timeout: int = 15) -> List[Tuple[str, str]]:
    """Fetch RSS feed and return list of (title, description) tuples."""
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        root = ET.fromstring(data)
        items: List[Tuple[str, str]] = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            desc = (item.findtext("description") or "").strip()
            items.append((title, desc))
        return items
    except Exception as exc:
        logger.warning("RSS fetch failed for %s: %s", url, exc)
        return []


def _score_sentiment_raw(text: str) -> float:
    """Return raw sentiment in [-2, +2] (from news_fetch.py logic)."""
    t = text.lower()
    pos = sum(1 for w in POS_WORDS if w in t)
    neg = sum(1 for w in NEG_WORDS if w in t)
    if pos == 0 and neg == 0:
        return 0.0
    return max(-2.0, min(2.0, float(pos - neg)))


def _sentiment_to_0_1(raw: float) -> float:
    """Scale sentiment from [-2,+2] to [0,1]."""
    return max(0.0, min(1.0, (raw + 2.0) / 4.0))


def _match_tickers(text: str) -> List[str]:
    """Extract matched NSE ticker symbols from text."""
    t = text.lower()
    hits: set[str] = set()
    for alias, sym in ALIASES.items():
        if alias in t:
            hits.add(sym)
    return sorted(hits)


def _detect_event_type(text: str) -> float:
    """Return the highest event-type weight matched in text."""
    t = text.lower()
    best = 0.5  # default
    for pattern, weight in EVENT_TYPE_PATTERNS:
        if re.search(pattern, t):
            best = max(best, weight)
    return best


def _freshness(fetched_at: datetime) -> float:
    """Exponential decay freshness score with half-life of 4 hours."""
    now = datetime.now(timezone.utc)
    age_hours = max(0.0, (now - fetched_at).total_seconds() / 3600.0)
    return math.exp(-0.693 * age_hours / FRESHNESS_HALF_LIFE_HOURS)


def _ticker_specificity(symbols: List[str], text: str) -> float:
    """How specific is this news to a single company?

    - 1 symbol matched and company-name keyword => 1.0
    - 1 symbol, sector-level language => 0.7
    - 2-3 symbols => 0.6
    - 4+ symbols or no symbols => 0.3
    """
    n = len(symbols)
    if n == 0:
        return 0.3
    t = text.lower()
    has_sector = bool(re.search(r"\bsector\b|\bindustry\b|\bspace\b", t))
    has_macro = bool(re.search(r"\bmarket\b|\bglobal\b|\beconomy\b|\brbi\b|\bfed\b", t))
    if n == 1:
        if has_macro:
            return 0.5
        if has_sector:
            return 0.7
        return 1.0
    if n <= 3:
        return 0.6
    return 0.3


def _estimate_materiality(text: str) -> float:
    """Heuristic materiality estimate (proxy for expected % price impact).

    Returns a value in [0, 1].
    """
    t = text.lower()
    # High materiality triggers
    if re.search(r"\bfraud\b|\braid\b|\bscam\b|\bdefault\b|\barrest\b", t):
        return 0.95
    if re.search(r"\bm&a\b|\bmerger\b|\bacquisition\b|\btakeover\b", t):
        return 0.90
    if re.search(r"\bearnings?\b|\bquarterly\b|\bresults?\b", t):
        return 0.75
    if re.search(r"\bupgrade\b|\bdowngrade\b", t):
        return 0.65
    if re.search(r"\bdividend\b|\bbuyback\b|\bbonus\b", t):
        return 0.55
    if re.search(r"\border\b|\bcontract\b|\bdeal\b", t):
        return 0.50
    return 0.35


# ---------------------------------------------------------------------------
# NewsRanker
# ---------------------------------------------------------------------------

class NewsRanker:
    """Fetch, score, and rank market news for the trading pipeline.

    Parameters
    ----------
    feeds : list of (name, url) tuples, or None to use defaults.
    """

    def __init__(
        self,
        feeds: Optional[List[Tuple[str, str]]] = None,
    ) -> None:
        self._feeds = feeds or FEEDS
        self._cache: List[RankedNews] = []
        self._cache_ts: float = 0.0
        self._cache_ttl: float = 300.0  # 5 min

    # -- public API ----------------------------------------------------------

    def fetch_all_news(self, force: bool = False) -> List[RankedNews]:
        """Fetch and score all news from configured RSS feeds.

        Uses a 5-minute in-memory cache unless *force* is True.
        """
        if not force and self._cache and (time.monotonic() - self._cache_ts < self._cache_ttl):
            return list(self._cache)

        all_items: List[RankedNews] = []
        # Track headlines across sources for multi-source detection
        headline_sources: Dict[str, List[str]] = {}

        for source_name, url in self._feeds:
            raw = _fetch_rss(url)
            logger.info("[news_ranker] %s: %d items", source_name, len(raw))
            for title, desc in raw:
                full_text = f"{title} -- {desc}"
                key = re.sub(r"\s+", " ", title.lower().strip()[:80])
                headline_sources.setdefault(key, []).append(source_name)

                symbols = _match_tickers(full_text)
                raw_sent = _score_sentiment_raw(full_text)

                item = RankedNews(
                    headline=full_text[:300],
                    source=source_name,
                    matched_symbols=symbols,
                    source_quality=SOURCE_QUALITY.get(source_name, SOURCE_QUALITY["unknown"]),
                    event_type_weight=_detect_event_type(full_text),
                    sentiment_magnitude=_sentiment_to_0_1(raw_sent),
                    raw_sentiment=raw_sent,
                    freshness_score=1.0,  # just fetched
                    ticker_specificity=_ticker_specificity(symbols, full_text),
                    materiality=_estimate_materiality(full_text),
                )
                all_items.append(item)

        # Compute multi-source scores
        for item in all_items:
            key = re.sub(r"\s+", " ", item.headline.split(" -- ")[0].lower().strip()[:80])
            n_sources = len(set(headline_sources.get(key, [])))
            # Scale: 1 source=0, 2=0.5, 3+=1.0
            item.multi_source_score = min(1.0, max(0.0, (n_sources - 1) / 2.0))

        # Compute weighted_impact
        for item in all_items:
            item.weighted_impact = self._compute_impact(item)

        # Sort by impact descending
        all_items.sort(key=lambda x: x.weighted_impact, reverse=True)

        self._cache = all_items
        self._cache_ts = time.monotonic()
        return list(all_items)

    def rank_news_for_symbol(
        self,
        symbol: str,
        news_items: Optional[List[RankedNews]] = None,
    ) -> float:
        """Return the aggregate weighted impact for *symbol*.

        If multiple news items mention the symbol, we take the max impact
        (not sum) to avoid double-counting correlated stories, but add a
        small bonus (+0.05 per additional story, capped).
        """
        if news_items is None:
            news_items = self.fetch_all_news()

        relevant = [n for n in news_items if symbol in n.matched_symbols]
        if not relevant:
            return 0.0

        impacts = sorted([n.weighted_impact for n in relevant], reverse=True)
        base = impacts[0]
        bonus = min(0.15, 0.05 * (len(impacts) - 1))
        return round(min(1.0, base + bonus), 4)

    def apply_intraday_decay(
        self,
        symbol: str,
        price_change_pct: float,
        hours_since_news: float,
        news_items: Optional[List[RankedNews]] = None,
    ) -> List[RankedNews]:
        """Apply intraday decay: if price hasn't moved > 0.5% in the direction
        of the news within 2 hours, reduce impact by 50%.

        Returns updated news items for the symbol.
        """
        if news_items is None:
            news_items = self.fetch_all_news()

        relevant = [n for n in news_items if symbol in n.matched_symbols and not n.decayed]

        if hours_since_news < PRICE_FOLLOW_THROUGH_WINDOW_HOURS:
            return relevant  # too early to judge

        for item in relevant:
            expected_direction = 1.0 if item.raw_sentiment >= 0 else -1.0
            actual_direction = 1.0 if price_change_pct >= 0 else -1.0

            moved_enough = abs(price_change_pct) >= PRICE_FOLLOW_THROUGH_THRESHOLD_PCT
            same_direction = expected_direction == actual_direction

            if not (moved_enough and same_direction):
                item.weighted_impact *= 0.5
                item.price_follow_through = False
                item.decayed = True

        return relevant

    # -- internal ------------------------------------------------------------

    @staticmethod
    def _compute_impact(item: RankedNews) -> float:
        """
        weighted_impact = (
            source_quality     * 0.15 +
            event_type_weight  * 0.20 +
            sentiment_magnitude* 0.15 +
            freshness_score    * 0.15 +
            ticker_specificity * 0.15 +
            materiality        * 0.10 +
            multi_source       * 0.10
        )
        """
        return round(
            item.source_quality * 0.15
            + item.event_type_weight * 0.20
            + item.sentiment_magnitude * 0.15
            + item.freshness_score * 0.15
            + item.ticker_specificity * 0.15
            + item.materiality * 0.10
            + item.multi_source_score * 0.10,
            4,
        )

    def refresh_freshness(self, news_items: List[RankedNews]) -> None:
        """Recompute freshness scores and weighted_impact for all items."""
        for item in news_items:
            item.freshness_score = _freshness(item.fetched_at)
            item.weighted_impact = self._compute_impact(item)

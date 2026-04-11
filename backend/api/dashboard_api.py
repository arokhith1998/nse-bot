"""
NSE Market Intelligence Platform - Dashboard API
=================================================
FastAPI router exposing all REST endpoints and a WebSocket feed for
the live dashboard.  Every endpoint returns typed Pydantic response
models and uses the async SQLAlchemy session provided by ``get_db``.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models import (
    LearningRecord,
    NewsItem,
    RegimeSnapshot,
    Signal,
    Trade,
    UniverseMember,
    UserSettings,
    WeightsHistory,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboard"])


# =====================================================================
# Pydantic response schemas
# =====================================================================

# -- Picks -------------------------------------------------------------

class ScoreBreakdown(BaseModel):
    """Individual feature contribution to the composite score."""
    feature: str
    value: float
    weight: float
    contribution: float


class PickResponse(BaseModel):
    id: int
    timestamp: dt.datetime
    symbol: str
    instrument_type: str
    direction: str
    score: float
    strategy: str
    regime_at_entry: Optional[str] = None
    source: str
    entry_zone_low: float
    entry_zone_high: float
    stop_loss: float
    target1: float
    target2: Optional[float] = None
    trailing_rule: Optional[str] = None
    confidence: float
    position_size_pct: float
    do_not_enter_after: Optional[dt.datetime] = None
    best_exit_window: Optional[str] = None
    explanation: Optional[str] = None
    status: str
    score_breakdown: List[ScoreBreakdown] = Field(default_factory=list)


class PicksListResponse(BaseModel):
    picks: List[PickResponse]
    count: int
    generated_at: dt.datetime


# -- Trades ------------------------------------------------------------

class ActiveTradeResponse(BaseModel):
    id: int
    signal_id: int
    symbol: str
    entry_price: float
    entry_time: dt.datetime
    qty: int
    status: str
    direction: str = "long"
    strategy: str = ""
    current_price: Optional[float] = None
    unrealised_pnl: Optional[float] = None
    unrealised_pnl_pct: Optional[float] = None
    stop_loss: Optional[float] = None
    target1: Optional[float] = None
    target2: Optional[float] = None
    exit_prompt: Optional[str] = None


class ActiveTradesResponse(BaseModel):
    trades: List[ActiveTradeResponse]
    count: int
    total_unrealised_pnl: float


class ClosedTradeResponse(BaseModel):
    id: int
    signal_id: int
    symbol: str
    entry_price: float
    entry_time: dt.datetime
    exit_price: Optional[float] = None
    exit_time: Optional[dt.datetime] = None
    qty: int
    gross_pnl: Optional[float] = None
    net_pnl: Optional[float] = None
    cost: Optional[float] = None
    status: str
    exit_reason: Optional[str] = None
    strategy: str = ""
    direction: str = "long"


class TradeHistoryResponse(BaseModel):
    trades: List[ClosedTradeResponse]
    count: int
    total_net_pnl: float
    win_count: int
    loss_count: int


# -- Regime ------------------------------------------------------------

class RegimeResponse(BaseModel):
    id: int
    timestamp: dt.datetime
    vix: float
    advance_decline: float
    breadth_pct: float
    nifty_trend: str
    bank_nifty_trend: str
    regime_label: str
    sub_regime: Optional[str] = None
    confidence: float
    scoring_modifiers: Dict[str, float] = Field(default_factory=dict)


class RegimeHistoryResponse(BaseModel):
    snapshots: List[RegimeResponse]
    count: int


# -- Performance -------------------------------------------------------

class SetupPerformance(BaseModel):
    strategy: str
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: float
    avg_pnl: float
    avg_pnl_pct: float
    total_pnl: float
    best_trade: float
    worst_trade: float


class SetupPerformanceResponse(BaseModel):
    setups: List[SetupPerformance]
    total_trades: int


class FeatureWeightSnapshot(BaseModel):
    timestamp: dt.datetime
    weights: Dict[str, float]
    trigger: str
    notes: Optional[str] = None


class FeatureImportanceResponse(BaseModel):
    history: List[FeatureWeightSnapshot]
    current_weights: Dict[str, float]


# -- News --------------------------------------------------------------

class NewsResponse(BaseModel):
    id: int
    timestamp: dt.datetime
    symbol: Optional[str] = None
    headline: str
    source: str
    source_quality: float
    event_type: Optional[str] = None
    sentiment_score: float
    relevance_score: float
    freshness_hours: float
    ticker_specificity: float
    materiality: float
    multi_source_count: int
    weighted_impact: float
    confirmed_by_price: bool


class NewsListResponse(BaseModel):
    news: List[NewsResponse]
    count: int


# -- Overview ----------------------------------------------------------

class MarketOverview(BaseModel):
    nifty50: Optional[float] = None
    nifty50_change_pct: Optional[float] = None
    banknifty: Optional[float] = None
    banknifty_change_pct: Optional[float] = None
    india_vix: Optional[float] = None
    breadth_pct: Optional[float] = None
    advance_count: Optional[int] = None
    decline_count: Optional[int] = None
    advance_decline_ratio: Optional[float] = None
    regime_label: Optional[str] = None
    open_positions: int = 0
    total_unrealised_pnl: float = 0.0
    as_of: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))


# -- ETF Universe -----------------------------------------------------

class ETFResponse(BaseModel):
    id: int
    symbol: str
    name: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    index_membership: Optional[str] = None
    market_cap_cr: Optional[float] = None
    avg_volume_20d: Optional[float] = None
    is_active: bool


class ETFUniverseResponse(BaseModel):
    etfs: List[ETFResponse]
    count: int


# -- Settings ----------------------------------------------------------

class SettingsResponse(BaseModel):
    capital: float
    risk_per_trade_pct: float
    max_open_positions: int
    max_sector_concentration_pct: float
    market_open: str
    market_close: str
    scan_interval_min: int
    news_refresh_interval_min: int
    default_provider: str
    market_data_providers: List[str]


class SettingsUpdateRequest(BaseModel):
    capital: Optional[float] = None
    risk_per_trade_pct: Optional[float] = None
    max_open_positions: Optional[int] = None
    max_sector_concentration_pct: Optional[float] = None
    scan_interval_min: Optional[int] = None
    news_refresh_interval_min: Optional[int] = None


# =====================================================================
# WebSocket connection manager
# =====================================================================

class ConnectionManager:
    """Manages active WebSocket connections and broadcasts events."""

    def __init__(self) -> None:
        self._connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)
        logger.info("WebSocket client connected (%d total)", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self._connections:
                self._connections.remove(ws)
        logger.info("WebSocket client disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, event_type: str, data: Any) -> None:
        """Send a typed event to every connected client.

        Payload format::

            {"event": "<event_type>", "data": <data>, "ts": "<ISO timestamp>"}

        Supported event types:
            pick_update, trade_opened, trade_closed,
            regime_change, exit_prompt, news_alert
        """
        if not self._connections:
            return

        message = json.dumps(
            {
                "event": event_type,
                "data": data if isinstance(data, (dict, list, str, int, float, bool, type(None))) else str(data),
                "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
            default=str,
        )

        stale: List[WebSocket] = []
        async with self._lock:
            for ws in self._connections:
                try:
                    await ws.send_text(message)
                except Exception:
                    stale.append(ws)

            for ws in stale:
                self._connections.remove(ws)

        if stale:
            logger.info("Removed %d stale WebSocket connections", len(stale))

    @property
    def active_count(self) -> int:
        return len(self._connections)


# Module-level singleton so other parts of the app can import and broadcast.
ws_manager = ConnectionManager()


# =====================================================================
# Helper: regime scoring modifiers
# =====================================================================

def _regime_scoring_modifiers(regime_label: str) -> Dict[str, float]:
    """Return score multipliers based on the current regime."""
    modifiers: Dict[str, Dict[str, float]] = {
        "risk_on": {"momentum": 1.2, "breakout": 1.1, "mean_reversion": 0.8},
        "risk_off": {"momentum": 0.7, "breakout": 0.6, "mean_reversion": 1.2},
        "trending_bull": {"momentum": 1.3, "breakout": 1.2, "mean_reversion": 0.7},
        "trending_bear": {"momentum": 0.8, "breakout": 0.6, "mean_reversion": 1.1},
        "choppy": {"momentum": 0.6, "breakout": 0.5, "mean_reversion": 1.3},
    }
    return modifiers.get(regime_label, {"momentum": 1.0, "breakout": 1.0, "mean_reversion": 1.0})


# =====================================================================
# REST Endpoints
# =====================================================================

# -- Picks -------------------------------------------------------------

@router.get("/api/picks/live", response_model=PicksListResponse)
async def get_live_picks(db: AsyncSession = Depends(get_db)) -> PicksListResponse:
    """Current scored picks with full score breakdowns."""
    result = await db.execute(
        select(Signal)
        .where(Signal.status.in_(["pending", "active"]))
        .order_by(desc(Signal.score))
    )
    signals = result.scalars().all()

    picks: List[PickResponse] = []
    for sig in signals:
        # Attempt to build score breakdown from the latest learning record
        # that references a trade for this signal, or return empty.
        breakdown: List[ScoreBreakdown] = []
        lr_result = await db.execute(
            select(LearningRecord)
            .join(Trade, Trade.id == LearningRecord.trade_id)
            .where(Trade.signal_id == sig.id)
            .order_by(desc(LearningRecord.timestamp))
            .limit(1)
        )
        lr = lr_result.scalar_one_or_none()
        if lr and lr.feature_contributions_json:
            try:
                contribs = json.loads(lr.feature_contributions_json)
                for feat, val in contribs.items():
                    breakdown.append(
                        ScoreBreakdown(
                            feature=feat,
                            value=val,
                            weight=1.0,
                            contribution=val,
                        )
                    )
            except (json.JSONDecodeError, TypeError):
                pass

        picks.append(
            PickResponse(
                id=sig.id,
                timestamp=sig.timestamp,
                symbol=sig.symbol,
                instrument_type=sig.instrument_type,
                direction=sig.direction,
                score=sig.score,
                strategy=sig.strategy,
                regime_at_entry=sig.regime_at_entry,
                source=sig.source,
                entry_zone_low=sig.entry_zone_low,
                entry_zone_high=sig.entry_zone_high,
                stop_loss=sig.stop_loss,
                target1=sig.target1,
                target2=sig.target2,
                trailing_rule=sig.trailing_rule,
                confidence=sig.confidence,
                position_size_pct=sig.position_size_pct,
                do_not_enter_after=sig.do_not_enter_after,
                best_exit_window=sig.best_exit_window,
                explanation=sig.explanation,
                status=sig.status,
                score_breakdown=breakdown,
            )
        )

    return PicksListResponse(
        picks=picks,
        count=len(picks),
        generated_at=dt.datetime.now(dt.timezone.utc),
    )


# -- Trades (active) ---------------------------------------------------

@router.get("/api/trades/active", response_model=ActiveTradesResponse)
async def get_active_trades(db: AsyncSession = Depends(get_db)) -> ActiveTradesResponse:
    """Open positions with live P&L and exit prompts."""
    result = await db.execute(
        select(Trade, Signal)
        .join(Signal, Signal.id == Trade.signal_id)
        .where(Trade.status.in_(["open", "partial"]))
        .order_by(desc(Trade.entry_time))
    )
    rows = result.all()

    trades: List[ActiveTradeResponse] = []
    total_pnl = 0.0

    for trade, signal in rows:
        # In a production system we would fetch the live price here.
        # For now we surface the entry price as current_price placeholder.
        current_price: Optional[float] = None
        unrealised_pnl: Optional[float] = None
        unrealised_pnl_pct: Optional[float] = None
        exit_prompt: Optional[str] = None

        try:
            from backend.modules.market_data_provider import CompositeProvider
            provider = CompositeProvider()
            quote = provider.get_quote(trade.symbol)
            if quote and quote.ltp > 0:
                current_price = quote.ltp
                direction_mult = 1.0 if signal.direction == "long" else -1.0
                unrealised_pnl = direction_mult * (current_price - trade.entry_price) * trade.qty
                unrealised_pnl_pct = direction_mult * ((current_price - trade.entry_price) / trade.entry_price) * 100
                total_pnl += unrealised_pnl or 0.0

                # Generate exit prompt if price is near stop or target
                if signal.direction == "long":
                    if current_price <= signal.stop_loss:
                        exit_prompt = f"STOP HIT: Price {current_price:.2f} <= SL {signal.stop_loss:.2f}. Exit immediately."
                    elif current_price >= signal.target1 and (signal.target2 is None or current_price < signal.target2):
                        exit_prompt = f"TARGET 1 HIT: Price {current_price:.2f} >= T1 {signal.target1:.2f}. Consider booking partial."
                    elif signal.target2 and current_price >= signal.target2:
                        exit_prompt = f"TARGET 2 HIT: Price {current_price:.2f} >= T2 {signal.target2:.2f}. Book full profit."
                else:
                    if current_price >= signal.stop_loss:
                        exit_prompt = f"STOP HIT: Price {current_price:.2f} >= SL {signal.stop_loss:.2f}. Exit immediately."
                    elif current_price <= signal.target1:
                        exit_prompt = f"TARGET 1 HIT: Price {current_price:.2f} <= T1 {signal.target1:.2f}. Consider booking partial."
        except Exception:
            # Market data not available; leave prices as None.
            pass

        trades.append(
            ActiveTradeResponse(
                id=trade.id,
                signal_id=trade.signal_id,
                symbol=trade.symbol,
                entry_price=trade.entry_price,
                entry_time=trade.entry_time,
                qty=trade.qty,
                status=trade.status,
                direction=signal.direction,
                strategy=signal.strategy,
                current_price=current_price,
                unrealised_pnl=unrealised_pnl,
                unrealised_pnl_pct=unrealised_pnl_pct,
                stop_loss=signal.stop_loss,
                target1=signal.target1,
                target2=signal.target2,
                exit_prompt=exit_prompt,
            )
        )

    return ActiveTradesResponse(
        trades=trades,
        count=len(trades),
        total_unrealised_pnl=total_pnl,
    )


# -- Trades (history) --------------------------------------------------

@router.get("/api/trades/history", response_model=TradeHistoryResponse)
async def get_trade_history(
    days: int = Query(default=30, ge=1, le=365),
    setup: Optional[str] = Query(default=None),
    regime: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> TradeHistoryResponse:
    """Closed trades with optional filters by setup type and regime."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)

    stmt = (
        select(Trade, Signal)
        .join(Signal, Signal.id == Trade.signal_id)
        .where(Trade.status == "closed")
        .where(Trade.exit_time >= cutoff)
    )

    if setup:
        stmt = stmt.where(Signal.strategy == setup)
    if regime:
        stmt = stmt.where(Signal.regime_at_entry == regime)

    stmt = stmt.order_by(desc(Trade.exit_time))

    result = await db.execute(stmt)
    rows = result.all()

    trades: List[ClosedTradeResponse] = []
    total_net_pnl = 0.0
    win_count = 0
    loss_count = 0

    for trade, signal in rows:
        net = trade.net_pnl or 0.0
        total_net_pnl += net
        if net > 0:
            win_count += 1
        elif net < 0:
            loss_count += 1

        trades.append(
            ClosedTradeResponse(
                id=trade.id,
                signal_id=trade.signal_id,
                symbol=trade.symbol,
                entry_price=trade.entry_price,
                entry_time=trade.entry_time,
                exit_price=trade.exit_price,
                exit_time=trade.exit_time,
                qty=trade.qty,
                gross_pnl=trade.gross_pnl,
                net_pnl=trade.net_pnl,
                cost=trade.cost,
                status=trade.status,
                exit_reason=trade.exit_reason,
                strategy=signal.strategy,
                direction=signal.direction,
            )
        )

    return TradeHistoryResponse(
        trades=trades,
        count=len(trades),
        total_net_pnl=total_net_pnl,
        win_count=win_count,
        loss_count=loss_count,
    )


# -- Regime ------------------------------------------------------------

@router.get("/api/regime/current", response_model=RegimeResponse)
async def get_current_regime(db: AsyncSession = Depends(get_db)) -> RegimeResponse:
    """Latest regime snapshot with scoring modifiers."""
    result = await db.execute(
        select(RegimeSnapshot).order_by(desc(RegimeSnapshot.timestamp)).limit(1)
    )
    snap = result.scalar_one_or_none()
    if snap is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No regime snapshot available. Run the regime scanner first.",
        )

    return RegimeResponse(
        id=snap.id,
        timestamp=snap.timestamp,
        vix=snap.vix,
        advance_decline=snap.advance_decline,
        breadth_pct=snap.breadth_pct,
        nifty_trend=snap.nifty_trend,
        bank_nifty_trend=snap.bank_nifty_trend,
        regime_label=snap.regime_label,
        sub_regime=snap.sub_regime,
        confidence=snap.confidence,
        scoring_modifiers=_regime_scoring_modifiers(snap.regime_label),
    )


@router.get("/api/regime/history", response_model=RegimeHistoryResponse)
async def get_regime_history(
    days: int = Query(default=20, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> RegimeHistoryResponse:
    """Regime timeline for the last N days."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)

    result = await db.execute(
        select(RegimeSnapshot)
        .where(RegimeSnapshot.timestamp >= cutoff)
        .order_by(desc(RegimeSnapshot.timestamp))
    )
    snapshots = result.scalars().all()

    items = [
        RegimeResponse(
            id=s.id,
            timestamp=s.timestamp,
            vix=s.vix,
            advance_decline=s.advance_decline,
            breadth_pct=s.breadth_pct,
            nifty_trend=s.nifty_trend,
            bank_nifty_trend=s.bank_nifty_trend,
            regime_label=s.regime_label,
            sub_regime=s.sub_regime,
            confidence=s.confidence,
            scoring_modifiers=_regime_scoring_modifiers(s.regime_label),
        )
        for s in snapshots
    ]

    return RegimeHistoryResponse(snapshots=items, count=len(items))


# -- Performance -------------------------------------------------------

@router.get("/api/performance/setups", response_model=SetupPerformanceResponse)
async def get_setup_performance(db: AsyncSession = Depends(get_db)) -> SetupPerformanceResponse:
    """Win rate, avg P&L, count grouped by strategy tag."""
    result = await db.execute(
        select(Trade, Signal)
        .join(Signal, Signal.id == Trade.signal_id)
        .where(Trade.status == "closed")
        .order_by(Signal.strategy)
    )
    rows = result.all()

    # Group by strategy
    from collections import defaultdict
    grouped: Dict[str, List[Trade]] = defaultdict(list)
    for trade, signal in rows:
        # Attach strategy as a transient attribute for grouping
        trade._strategy = signal.strategy  # type: ignore[attr-defined]
        grouped[signal.strategy].append(trade)

    setups: List[SetupPerformance] = []
    total_trades = 0

    for strat, trades_list in sorted(grouped.items()):
        pnls = [t.net_pnl or 0.0 for t in trades_list]
        pnl_pcts = [
            ((t.net_pnl or 0.0) / (t.entry_price * t.qty) * 100) if (t.entry_price * t.qty) > 0 else 0.0
            for t in trades_list
        ]
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        count = len(trades_list)
        total_trades += count

        setups.append(
            SetupPerformance(
                strategy=strat,
                trade_count=count,
                win_count=wins,
                loss_count=losses,
                win_rate=(wins / count * 100) if count > 0 else 0.0,
                avg_pnl=sum(pnls) / count if count > 0 else 0.0,
                avg_pnl_pct=sum(pnl_pcts) / count if count > 0 else 0.0,
                total_pnl=sum(pnls),
                best_trade=max(pnls) if pnls else 0.0,
                worst_trade=min(pnls) if pnls else 0.0,
            )
        )

    return SetupPerformanceResponse(setups=setups, total_trades=total_trades)


@router.get("/api/performance/features", response_model=FeatureImportanceResponse)
async def get_feature_importance(db: AsyncSession = Depends(get_db)) -> FeatureImportanceResponse:
    """Feature importance weights over time."""
    result = await db.execute(
        select(WeightsHistory).order_by(desc(WeightsHistory.timestamp)).limit(50)
    )
    records = result.scalars().all()

    history: List[FeatureWeightSnapshot] = []
    current_weights: Dict[str, float] = {}

    for rec in records:
        try:
            weights = json.loads(rec.weights_json)
        except (json.JSONDecodeError, TypeError):
            weights = {}

        if not current_weights:
            current_weights = weights

        history.append(
            FeatureWeightSnapshot(
                timestamp=rec.timestamp,
                weights=weights,
                trigger=rec.trigger,
                notes=rec.notes,
            )
        )

    # If no history in DB, try loading from the weights.json file
    if not current_weights:
        try:
            weights_path = settings.project_root / "weights.json"
            if weights_path.exists():
                current_weights = json.loads(weights_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    return FeatureImportanceResponse(history=history, current_weights=current_weights)


# -- News --------------------------------------------------------------

@router.get("/api/news/latest", response_model=NewsListResponse)
async def get_latest_news(
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> NewsListResponse:
    """Recent news with weighted impact scores."""
    result = await db.execute(
        select(NewsItem)
        .order_by(desc(NewsItem.timestamp))
        .limit(limit)
    )
    items = result.scalars().all()

    news = [
        NewsResponse(
            id=n.id,
            timestamp=n.timestamp,
            symbol=n.symbol,
            headline=n.headline,
            source=n.source,
            source_quality=n.source_quality,
            event_type=n.event_type,
            sentiment_score=n.sentiment_score,
            relevance_score=n.relevance_score,
            freshness_hours=n.freshness_hours,
            ticker_specificity=n.ticker_specificity,
            materiality=n.materiality,
            multi_source_count=n.multi_source_count,
            weighted_impact=n.weighted_impact,
            confirmed_by_price=n.confirmed_by_price,
        )
        for n in items
    ]

    return NewsListResponse(news=news, count=len(news))


# -- Overview ----------------------------------------------------------

@router.get("/api/overview", response_model=MarketOverview)
async def get_market_overview(db: AsyncSession = Depends(get_db)) -> MarketOverview:
    """Market overview: Nifty, BankNifty, VIX, breadth, advance/decline."""
    # Pull latest regime snapshot for market-level data
    regime_result = await db.execute(
        select(RegimeSnapshot).order_by(desc(RegimeSnapshot.timestamp)).limit(1)
    )
    regime = regime_result.scalar_one_or_none()

    # Count open positions and unrealised P&L
    trade_result = await db.execute(
        select(Trade).where(Trade.status.in_(["open", "partial"]))
    )
    open_trades = trade_result.scalars().all()

    overview = MarketOverview(
        open_positions=len(open_trades),
        as_of=dt.datetime.now(dt.timezone.utc),
    )

    if regime:
        overview.india_vix = regime.vix
        overview.breadth_pct = regime.breadth_pct
        overview.advance_decline_ratio = regime.advance_decline
        overview.regime_label = regime.regime_label

        # Derive advance/decline counts from ratio (approximate)
        if regime.advance_decline > 0:
            # Assume 500-stock universe (Nifty 500)
            total = 500
            overview.advance_count = int(total * regime.advance_decline / (1 + regime.advance_decline))
            overview.decline_count = total - overview.advance_count

    # Attempt to fetch live index data
    try:
        from backend.modules.market_data_provider import CompositeProvider
        provider = CompositeProvider()

        nifty_quote = provider.get_quote("NIFTY 50")
        if nifty_quote and nifty_quote.ltp > 0:
            overview.nifty50 = nifty_quote.ltp
            if nifty_quote.close > 0:
                overview.nifty50_change_pct = ((nifty_quote.ltp - nifty_quote.close) / nifty_quote.close) * 100

        bn_quote = provider.get_quote("NIFTY BANK")
        if bn_quote and bn_quote.ltp > 0:
            overview.banknifty = bn_quote.ltp
            if bn_quote.close > 0:
                overview.banknifty_change_pct = ((bn_quote.ltp - bn_quote.close) / bn_quote.close) * 100
    except Exception:
        pass

    return overview


# -- ETF Universe ------------------------------------------------------

@router.get("/api/universe/etfs", response_model=ETFUniverseResponse)
async def get_etf_universe(db: AsyncSession = Depends(get_db)) -> ETFUniverseResponse:
    """ETF universe with categories."""
    result = await db.execute(
        select(UniverseMember)
        .where(UniverseMember.instrument_type == "etf")
        .where(UniverseMember.is_active == True)  # noqa: E712
        .order_by(UniverseMember.symbol)
    )
    members = result.scalars().all()

    etfs = [
        ETFResponse(
            id=m.id,
            symbol=m.symbol,
            name=m.name,
            sector=m.sector,
            industry=m.industry,
            index_membership=m.index_membership,
            market_cap_cr=m.market_cap_cr,
            avg_volume_20d=m.avg_volume_20d,
            is_active=m.is_active,
        )
        for m in members
    ]

    return ETFUniverseResponse(etfs=etfs, count=len(etfs))


# -- Settings ----------------------------------------------------------

@router.get("/api/settings", response_model=SettingsResponse)
async def get_settings() -> SettingsResponse:
    """Current platform configuration."""
    return SettingsResponse(
        capital=settings.capital,
        risk_per_trade_pct=settings.risk_per_trade_pct,
        max_open_positions=settings.max_open_positions,
        max_sector_concentration_pct=settings.max_sector_concentration_pct,
        market_open=settings.market_open,
        market_close=settings.market_close,
        scan_interval_min=settings.scan_interval_min,
        news_refresh_interval_min=settings.news_refresh_interval_min,
        default_provider=settings.default_provider,
        market_data_providers=settings.market_data_providers,
    )


@router.put("/api/settings", response_model=SettingsResponse)
async def update_settings(
    update: SettingsUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> SettingsResponse:
    """Update configuration (capital, risk params, etc.).

    Capital is persisted to the database so it survives restarts.
    Other settings remain in-memory only.
    """
    if update.capital is not None:
        if update.capital <= 0:
            raise HTTPException(status_code=422, detail="Capital must be positive.")
        settings.capital = update.capital
        # Persist capital to DB
        from sqlalchemy.dialects.sqlite import insert as sqlite_upsert
        stmt = sqlite_upsert(UserSettings).values(
            key="capital", value=str(update.capital),
        ).on_conflict_do_update(
            index_elements=["key"],
            set_={"value": str(update.capital)},
        )
        await db.execute(stmt)

    if update.risk_per_trade_pct is not None:
        if not (0.1 <= update.risk_per_trade_pct <= 10.0):
            raise HTTPException(status_code=422, detail="risk_per_trade_pct must be between 0.1 and 10.0.")
        settings.risk_per_trade_pct = update.risk_per_trade_pct

    if update.max_open_positions is not None:
        if not (1 <= update.max_open_positions <= 30):
            raise HTTPException(status_code=422, detail="max_open_positions must be between 1 and 30.")
        settings.max_open_positions = update.max_open_positions

    if update.max_sector_concentration_pct is not None:
        if not (5.0 <= update.max_sector_concentration_pct <= 100.0):
            raise HTTPException(status_code=422, detail="max_sector_concentration_pct must be between 5 and 100.")
        settings.max_sector_concentration_pct = update.max_sector_concentration_pct

    if update.scan_interval_min is not None:
        if update.scan_interval_min < 1:
            raise HTTPException(status_code=422, detail="scan_interval_min must be >= 1.")
        settings.scan_interval_min = update.scan_interval_min

    if update.news_refresh_interval_min is not None:
        if update.news_refresh_interval_min < 5:
            raise HTTPException(status_code=422, detail="news_refresh_interval_min must be >= 5.")
        settings.news_refresh_interval_min = update.news_refresh_interval_min

    logger.info("Settings updated: %s", update.model_dump(exclude_none=True))

    return await get_settings()


# =====================================================================
# Groww Cost Calculator
# =====================================================================


class CostCalcRequest(BaseModel):
    """Input for the Groww brokerage calculator."""

    instrument_type: str = Field("stock", description="stock or etf")
    buy_price: float = Field(..., gt=0, description="Buy price per unit (INR)")
    sell_price: float = Field(..., gt=0, description="Sell price per unit (INR)")
    quantity: int = Field(..., gt=0, description="Number of shares/units")


class ChargeLineItem(BaseModel):
    label: str
    buy_side: float
    sell_side: float
    total: float


class CostCalcResponse(BaseModel):
    buy_price: float
    sell_price: float
    quantity: int
    instrument_type: str

    buy_value: float
    sell_value: float

    # Itemised charges
    brokerage: ChargeLineItem
    stt: ChargeLineItem
    exchange_txn: ChargeLineItem
    gst: ChargeLineItem
    sebi: ChargeLineItem
    stamp: ChargeLineItem
    dp_charge: ChargeLineItem

    total_charges: float
    gross_pnl: float
    net_pnl: float
    return_pct: float
    breakeven_sell_price: float


@router.post("/api/calculator/groww", response_model=CostCalcResponse)
async def groww_calculator(req: CostCalcRequest) -> CostCalcResponse:
    """Calculate exact Groww intraday charges and net P&L.

    Handles stocks and ETFs with correct STT rates.
    Equity Intraday (MIS): STT 0.025% on sell side.
    ETF: same STT treatment as equity for intraday.
    """
    buy_val = req.buy_price * req.quantity
    sell_val = req.sell_price * req.quantity

    # ── Brokerage: Groww flat Rs 20 per executed order ──
    brok_buy = 20.0
    brok_sell = 20.0

    # ── STT: 0.025% on sell side (intraday equity/ETF) ──
    stt_buy = 0.0
    stt_sell = round(sell_val * 0.00025, 4)

    # ── Exchange transaction: NSE 0.00345% each side ──
    exch_buy = round(buy_val * 0.0000345, 4)
    exch_sell = round(sell_val * 0.0000345, 4)

    # ── SEBI turnover fee: Rs 10 per crore (0.0001%) ──
    sebi_buy = round(buy_val * 0.000001, 4)
    sebi_sell = round(sell_val * 0.000001, 4)

    # ── Stamp duty: 0.003% on buy side only ──
    stamp_buy = round(buy_val * 0.00003, 4)
    stamp_sell = 0.0

    # ── GST: 18% on (brokerage + exchange txn + SEBI) per side ──
    gst_buy = round((brok_buy + exch_buy + sebi_buy) * 0.18, 4)
    gst_sell = round((brok_sell + exch_sell + sebi_sell) * 0.18, 4)

    # ── DP charge: Rs 0 for intraday (no delivery) ──
    dp_buy = 0.0
    dp_sell = 0.0

    total_charges = round(
        brok_buy + brok_sell
        + stt_buy + stt_sell
        + exch_buy + exch_sell
        + gst_buy + gst_sell
        + sebi_buy + sebi_sell
        + stamp_buy + stamp_sell
        + dp_buy + dp_sell,
        2,
    )

    gross_pnl = round(sell_val - buy_val, 2)
    net_pnl = round(gross_pnl - total_charges, 2)
    return_pct = round((net_pnl / buy_val) * 100, 4) if buy_val > 0 else 0.0

    # Breakeven sell price: the sell price at which net P&L = 0
    # Solve: (sell_be * qty) - buy_val - charges_at(sell_be) = 0
    # Approximate: breakeven ~ buy_price + (total_charges / qty)
    breakeven_sell = round(req.buy_price + (total_charges / req.quantity), 2)

    return CostCalcResponse(
        buy_price=req.buy_price,
        sell_price=req.sell_price,
        quantity=req.quantity,
        instrument_type=req.instrument_type,
        buy_value=round(buy_val, 2),
        sell_value=round(sell_val, 2),
        brokerage=ChargeLineItem(
            label="Brokerage (flat Rs 20/order)",
            buy_side=brok_buy, sell_side=brok_sell,
            total=round(brok_buy + brok_sell, 2),
        ),
        stt=ChargeLineItem(
            label="STT (0.025% sell side)",
            buy_side=stt_buy, sell_side=stt_sell,
            total=round(stt_buy + stt_sell, 4),
        ),
        exchange_txn=ChargeLineItem(
            label="Exchange Txn (0.00345%)",
            buy_side=exch_buy, sell_side=exch_sell,
            total=round(exch_buy + exch_sell, 4),
        ),
        gst=ChargeLineItem(
            label="GST (18%)",
            buy_side=gst_buy, sell_side=gst_sell,
            total=round(gst_buy + gst_sell, 4),
        ),
        sebi=ChargeLineItem(
            label="SEBI Fee (Rs 10/Cr)",
            buy_side=sebi_buy, sell_side=sebi_sell,
            total=round(sebi_buy + sebi_sell, 4),
        ),
        stamp=ChargeLineItem(
            label="Stamp Duty (0.003% buy)",
            buy_side=stamp_buy, sell_side=stamp_sell,
            total=round(stamp_buy + stamp_sell, 4),
        ),
        dp_charge=ChargeLineItem(
            label="DP Charge (intraday = 0)",
            buy_side=dp_buy, sell_side=dp_sell,
            total=0.0,
        ),
        total_charges=total_charges,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        return_pct=return_pct,
        breakeven_sell_price=breakeven_sell,
    )


# =====================================================================
# WebSocket endpoint
# =====================================================================

@router.websocket("/ws/live")
async def websocket_live(ws: WebSocket) -> None:
    """Live event stream for the dashboard.

    Pushes events with types:
        pick_update, trade_opened, trade_closed,
        regime_change, exit_prompt, news_alert
    """
    await ws_manager.connect(ws)
    try:
        while True:
            # Keep the connection alive; listen for client messages
            # (heartbeat pings, subscription filters, etc.)
            data = await ws.receive_text()
            # Echo back as acknowledgment
            await ws.send_text(json.dumps({"event": "ack", "data": data}))
    except WebSocketDisconnect:
        await ws_manager.disconnect(ws)
    except Exception:
        await ws_manager.disconnect(ws)

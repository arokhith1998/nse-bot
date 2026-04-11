"""
NSE Market Intelligence Platform - ORM Models
==============================================
All domain tables are defined here via SQLAlchemy 2.0 declarative mapping.
Every model inherits from a shared ``Base`` so that ``init_db()`` can create
them in one shot.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Boolean,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    """Shared declarative base for every ORM model."""
    pass


# ── Enums (stored as VARCHAR for portability) ────────────────────────────

class DirectionEnum(str):
    LONG = "long"
    SHORT = "short"


class InstrumentTypeEnum(str):
    STOCK = "stock"
    ETF = "etf"


class SignalStatusEnum(str):
    PENDING = "pending"
    ACTIVE = "active"
    FILLED = "filled"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class TradeStatusEnum(str):
    OPEN = "open"
    PARTIAL = "partial"
    CLOSED = "closed"
    CANCELLED = "cancelled"


# ── Signal ───────────────────────────────────────────────────────────────

class Signal(Base):
    """A trading signal produced by the scanning pipeline."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )
    symbol: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    instrument_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="stock",
        comment="stock | etf",
    )
    direction: Mapped[str] = mapped_column(
        String(10), nullable=False, default="long",
        comment="long | short",
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    strategy: Mapped[str] = mapped_column(
        String(80), nullable=False,
        comment="E.g. BREAKOUT, MOMENTUM, GAP-AND-GO, SWING-INTRADAY",
    )
    regime_at_entry: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True,
        comment="Market regime label at the time the signal was created.",
    )
    source: Mapped[str] = mapped_column(
        String(60), nullable=False, default="scanner",
        comment="scanner | tradingview | manual",
    )

    # ── Price levels ─────────────────────────────────────────────────
    entry_zone_low: Mapped[float] = mapped_column(Float, nullable=False)
    entry_zone_high: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    target1: Mapped[float] = mapped_column(Float, nullable=False)
    target2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trailing_rule: Mapped[Optional[str]] = mapped_column(
        String(120), nullable=True,
        comment="Human-readable trailing-stop rule, e.g. 'Move SL to cost after T1 hit'.",
    )

    # ── Meta ─────────────────────────────────────────────────────────
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="Model confidence 0-1.",
    )
    position_size_pct: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="Suggested position size as percent of capital.",
    )
    do_not_enter_after: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Signal expiry time – do not enter after this.",
    )
    best_exit_window: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True,
        comment="E.g. '14:30-15:00 IST'.",
    )
    explanation: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Human-readable reasoning for the signal.",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
        comment="pending | active | filled | expired | cancelled",
    )

    # ── Relationships ────────────────────────────────────────────────
    trades: Mapped[list["Trade"]] = relationship(
        back_populates="signal", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Signal(id={self.id}, symbol={self.symbol!r}, "
            f"direction={self.direction!r}, score={self.score})>"
        )


# ── Trade ────────────────────────────────────────────────────────────────

class Trade(Base):
    """A paper trade linked to a signal."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("signals.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    symbol: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    entry_time: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_time: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    gross_pnl: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="Raw P&L before transaction costs.",
    )
    net_pnl: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="P&L after brokerage, STT, GST, stamp, etc.",
    )
    cost: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="Round-trip transaction cost (Groww MIS model).",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open",
        comment="open | partial | closed | cancelled",
    )
    exit_reason: Mapped[Optional[str]] = mapped_column(
        String(60), nullable=True,
        comment="E.g. stop_loss | target1 | target2 | trailing | manual | eod_square_off",
    )

    # ── Relationships ────────────────────────────────────────────────
    signal: Mapped["Signal"] = relationship(back_populates="trades")
    learning_records: Mapped[list["LearningRecord"]] = relationship(
        back_populates="trade", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Trade(id={self.id}, symbol={self.symbol!r}, "
            f"status={self.status!r}, net_pnl={self.net_pnl})>"
        )


# ── Regime Snapshot ──────────────────────────────────────────────────────

class RegimeSnapshot(Base):
    """Point-in-time snapshot of the market regime (VIX, breadth, trends)."""

    __tablename__ = "regime_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )
    vix: Mapped[float] = mapped_column(Float, nullable=False, comment="India VIX level.")
    advance_decline: Mapped[float] = mapped_column(
        Float, nullable=False,
        comment="Advance-decline ratio (advances / declines).",
    )
    breadth_pct: Mapped[float] = mapped_column(
        Float, nullable=False,
        comment="Percent of Nifty 500 stocks above their 20-DMA.",
    )
    nifty_trend: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="up | down | sideways",
    )
    bank_nifty_trend: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="up | down | sideways",
    )
    regime_label: Mapped[str] = mapped_column(
        String(40), nullable=False,
        comment="E.g. risk_on, risk_off, choppy, trending_bull, trending_bear",
    )
    sub_regime: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True,
        comment="Finer-grained regime tag.",
    )
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="Regime classification confidence 0-1.",
    )
    nifty_close: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, default=0.0,
        comment="Nifty 50 closing price.",
    )
    nifty_change_pct: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, default=0.0,
        comment="Nifty 50 daily change percent.",
    )
    sensex_close: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, default=0.0,
        comment="BSE Sensex closing price.",
    )
    sensex_change_pct: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, default=0.0,
        comment="BSE Sensex daily change percent.",
    )

    def __repr__(self) -> str:
        return (
            f"<RegimeSnapshot(id={self.id}, regime={self.regime_label!r}, "
            f"vix={self.vix})>"
        )


# ── Universe Member ──────────────────────────────────────────────────────

class UniverseMember(Base):
    """A tradeable instrument in the platform's watchlist universe."""

    __tablename__ = "universe_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        String(30), nullable=False, unique=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    sector: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    instrument_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="stock",
        comment="stock | etf",
    )
    index_membership: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="Comma-separated index names, e.g. 'NIFTY50,NIFTY100'.",
    )
    market_cap_cr: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="Market cap in crores INR.",
    )
    avg_volume_20d: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="20-day average daily volume.",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        comment="False = delisted or removed from scan universe.",
    )
    added_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<UniverseMember(symbol={self.symbol!r}, sector={self.sector!r})>"


# ── News Item ────────────────────────────────────────────────────────────

class NewsItem(Base):
    """A single news event, enriched with NLP-derived scores."""

    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )
    symbol: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True, index=True,
        comment="NULL for macro / sector-level news.",
    )
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(
        String(60), nullable=False,
        comment="E.g. Moneycontrol, ET, Reuters, BSE filing",
    )
    source_quality: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5,
        comment="Source reliability score 0-1.",
    )
    event_type: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True,
        comment="E.g. earnings, order_win, rating_change, macro, sector_move",
    )
    sentiment_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="Sentiment in [-1, +1] range.",
    )
    relevance_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="How relevant the news is to the ticker 0-1.",
    )
    freshness_hours: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="Age of the news in hours at time of ingest.",
    )
    ticker_specificity: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="1.0 = company-specific, 0.0 = broad market.",
    )
    materiality: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="Expected impact magnitude 0-1.",
    )
    multi_source_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="Number of independent sources reporting same event.",
    )
    weighted_impact: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="Final composite news impact score.",
    )
    confirmed_by_price: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="True if price action has confirmed the news direction.",
    )

    def __repr__(self) -> str:
        return (
            f"<NewsItem(id={self.id}, symbol={self.symbol!r}, "
            f"sentiment={self.sentiment_score})>"
        )


# ── Weights History ──────────────────────────────────────────────────────

class WeightsHistory(Base):
    """Audit trail of every weights.json mutation."""

    __tablename__ = "weights_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )
    weights_json: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Full JSON snapshot of the weights dict.",
    )
    trigger: Mapped[str] = mapped_column(
        String(40), nullable=False, default="manual",
        comment="What caused the update: eod_learning | manual | rollback",
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Free-form annotation.",
    )

    def __repr__(self) -> str:
        return f"<WeightsHistory(id={self.id}, trigger={self.trigger!r})>"


# ── Learning Record ──────────────────────────────────────────────────────

class LearningRecord(Base):
    """Per-trade feature attribution used by the self-learning loop."""

    __tablename__ = "learning_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("trades.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    feature_contributions_json: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="JSON dict mapping feature names to their contribution to the signal score.",
    )
    regime: Mapped[str] = mapped_column(
        String(40), nullable=False,
        comment="Regime label at the time of the trade.",
    )
    setup_type: Mapped[str] = mapped_column(
        String(40), nullable=False,
        comment="E.g. BREAKOUT, MOMENTUM, GAP-AND-GO.",
    )
    time_window: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment="E.g. 'morning_first_hour', 'midday', 'closing'.",
    )
    outcome_pnl_pct: Mapped[float] = mapped_column(
        Float, nullable=False,
        comment="Trade outcome as percent P&L.",
    )
    learned_adjustments_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="JSON dict of weight deltas the learning loop derived from this trade.",
    )

    # ── Relationships ────────────────────────────────────────────────
    trade: Mapped["Trade"] = relationship(back_populates="learning_records")

    def __repr__(self) -> str:
        return (
            f"<LearningRecord(id={self.id}, trade_id={self.trade_id}, "
            f"outcome={self.outcome_pnl_pct:.2f}%)>"
        )

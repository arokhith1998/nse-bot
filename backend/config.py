"""
NSE Market Intelligence Platform - Configuration
=================================================
Centralised settings loaded from environment variables / .env file.
Uses pydantic-settings so every knob is typed, validated, and documented.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """All tuneable knobs for the platform.

    Values are loaded (in priority order) from:
      1. Explicit environment variables
      2. A ``.env`` file in the project root
      3. The defaults declared below
    """

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_prefix="NSE_",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Paths ────────────────────────────────────────────────────────────
    db_path: str = Field(
        default="data/nse_bot.db",
        description="SQLite database file path (relative to project root).",
    )
    data_dir: str = Field(
        default="data",
        description="Directory for all persistent artefacts (DB, exports, etc.).",
    )

    # ── API Server ───────────────────────────────────────────────────────
    api_port: int = Field(default=8000, ge=1, le=65535)
    api_host: str = Field(default="0.0.0.0")

    # ── Capital & Risk ───────────────────────────────────────────────────
    capital: float = Field(
        default=100_000.0,
        description="Total paper-trading capital in INR.",
    )
    risk_per_trade_pct: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="Maximum capital risked on a single trade (percent).",
    )
    max_open_positions: int = Field(
        default=6,
        ge=1,
        le=30,
        description="Maximum simultaneous open positions.",
    )
    max_sector_concentration_pct: float = Field(
        default=40.0,
        ge=5.0,
        le=100.0,
        description="Maximum allocation to any single sector (percent).",
    )

    # ── Market Hours (IST) ───────────────────────────────────────────────
    market_open: str = Field(
        default="09:15",
        description="NSE opening bell in HH:MM IST.",
    )
    market_close: str = Field(
        default="15:30",
        description="NSE closing bell in HH:MM IST.",
    )

    # ── Scheduler Intervals ──────────────────────────────────────────────
    scan_interval_min: int = Field(
        default=15,
        ge=1,
        description="Minutes between intraday signal scans.",
    )
    news_refresh_interval_min: int = Field(
        default=30,
        ge=5,
        description="Minutes between news-feed refreshes.",
    )

    # ── Integrations ─────────────────────────────────────────────────────
    tradingview_webhook_secret: str = Field(
        default="",
        description="Shared secret for TradingView webhook authentication.",
    )
    market_data_providers: List[str] = Field(
        default=["yfinance", "nsepython"],
        description="Ordered list of market-data providers to try.",
    )
    default_provider: str = Field(
        default="yfinance",
        description="Primary market-data provider.",
    )

    # ── Derived helpers (not loaded from env) ────────────────────────────

    @property
    def project_root(self) -> Path:
        return _PROJECT_ROOT

    @property
    def resolved_db_path(self) -> Path:
        """Return an absolute path to the SQLite database file."""
        p = Path(self.db_path)
        if not p.is_absolute():
            p = _PROJECT_ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def resolved_data_dir(self) -> Path:
        p = Path(self.data_dir)
        if not p.is_absolute():
            p = _PROJECT_ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def risk_per_trade_abs(self) -> float:
        """Absolute INR risk per trade."""
        return self.capital * self.risk_per_trade_pct / 100.0

    @field_validator("market_open", "market_close")
    @classmethod
    def _validate_time_format(cls, v: str) -> str:
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError(f"Expected HH:MM format, got '{v}'")
        hh, mm = int(parts[0]), int(parts[1])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError(f"Invalid time '{v}'")
        return v


# Singleton – import this everywhere.
settings = Settings()

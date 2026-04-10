"""
NSE Market Intelligence Platform - TradingView Webhook Routes
=============================================================
Receives TradingView alerts via HTTP POST, validates the shared secret,
normalises into an internal Signal, and routes it through the pipeline.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.config import settings
from backend.database import get_db_ctx
from backend.models import Signal as SignalORM

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


# =====================================================================
# Request / response models
# =====================================================================

class TVWebhookPayload(BaseModel):
    """Expected JSON body from a TradingView alert webhook."""
    ticker: str = Field(..., description="E.g. 'NSE:RELIANCE' or 'RELIANCE'")
    action: str = Field(..., description="buy | sell | close")
    price: float = Field(..., gt=0)
    strategy: str = Field(default="TradingView Alert", description="Strategy name from PineScript")
    interval: Optional[str] = Field(default=None, description="E.g. '15', '1H', '1D'")
    time: Optional[str] = Field(default=None, description="Alert timestamp from TV")
    message: Optional[str] = Field(default=None, description="Free-form message body")
    # Additional fields TradingView may send
    exchange: Optional[str] = Field(default=None)
    volume: Optional[float] = Field(default=None)
    open: Optional[float] = Field(default=None)
    high: Optional[float] = Field(default=None)
    low: Optional[float] = Field(default=None)
    close: Optional[float] = Field(default=None)
    # Webhook secret can also be embedded in the body
    secret: Optional[str] = Field(default=None, description="Webhook secret for body-level auth")


class WebhookAck(BaseModel):
    """Acknowledgment response for a processed webhook."""
    status: str = "ok"
    signal_id: Optional[int] = None
    symbol: str = ""
    action: str = ""
    message: str = ""


# =====================================================================
# Endpoint
# =====================================================================

@router.post(
    "/api/webhook/tradingview",
    response_model=WebhookAck,
    status_code=status.HTTP_201_CREATED,
    summary="Receive TradingView alert webhook",
)
async def tradingview_webhook(
    payload: TVWebhookPayload,
    request: Request,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
) -> WebhookAck:
    """Process an incoming TradingView webhook alert.

    Authentication:
        The shared secret can be provided either as:
        - ``X-Webhook-Secret`` HTTP header, or
        - ``secret`` field in the JSON body.

    Flow:
        1. Validate webhook secret.
        2. Parse and normalise the TradingView alert.
        3. Create an internal Signal record.
        4. Broadcast to WebSocket clients.
        5. Return acknowledgment.
    """
    # -- Log the raw incoming webhook -----------------------------------
    client_ip = request.client.host if request.client else "unknown"
    logger.info(
        "TradingView webhook received from %s: ticker=%s action=%s price=%s strategy=%s",
        client_ip,
        payload.ticker,
        payload.action,
        payload.price,
        payload.strategy,
    )

    # -- Validate secret ------------------------------------------------
    configured_secret = settings.tradingview_webhook_secret
    if configured_secret:
        provided_secret = x_webhook_secret or payload.secret
        if not provided_secret or provided_secret != configured_secret:
            logger.warning(
                "Webhook authentication failed from %s (ticker=%s)",
                client_ip,
                payload.ticker,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing webhook secret.",
            )

    # -- Parse via the tradingview_webhook module -----------------------
    from backend.modules.tradingview_webhook import (
        normalize_to_signal,
        parse_tv_alert,
    )

    try:
        tv_alert = parse_tv_alert(payload.model_dump())
    except ValueError as exc:
        logger.error("Failed to parse TradingView alert: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid alert payload: {exc}",
        )

    # Fetch the current regime for signal normalisation
    current_regime: Optional[str] = None
    try:
        from backend.models import RegimeSnapshot
        from sqlalchemy import desc, select

        async with get_db_ctx() as db:
            result = await db.execute(
                select(RegimeSnapshot).order_by(desc(RegimeSnapshot.timestamp)).limit(1)
            )
            snap = result.scalar_one_or_none()
            if snap:
                current_regime = snap.regime_label
    except Exception:
        logger.debug("Could not fetch current regime for webhook normalisation.")

    signal_data = normalize_to_signal(tv_alert, regime=current_regime)

    # -- Persist the signal ---------------------------------------------
    signal_id: Optional[int] = None
    try:
        async with get_db_ctx() as db:
            sig = SignalORM(
                symbol=signal_data["symbol"],
                instrument_type=signal_data.get("instrument_type", "stock"),
                direction=signal_data["direction"],
                score=signal_data.get("score", 50.0),
                strategy=signal_data["strategy"],
                regime_at_entry=signal_data.get("regime_at_entry"),
                source="tradingview",
                entry_zone_low=signal_data["entry_zone_low"],
                entry_zone_high=signal_data["entry_zone_high"],
                stop_loss=signal_data["stop_loss"],
                target1=signal_data["target1"],
                target2=signal_data.get("target2"),
                confidence=signal_data.get("confidence", 0.5),
                position_size_pct=signal_data.get("position_size_pct", 0.0),
                explanation=signal_data.get("explanation"),
                status="pending",
            )
            db.add(sig)
            await db.flush()
            signal_id = sig.id

        logger.info(
            "TradingView signal persisted: id=%s symbol=%s direction=%s",
            signal_id,
            signal_data["symbol"],
            signal_data["direction"],
        )
    except Exception:
        logger.exception("Failed to persist TradingView signal for %s", signal_data.get("symbol"))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Signal created but failed to persist to database.",
        )

    # -- Broadcast via WebSocket ----------------------------------------
    try:
        from backend.api.dashboard_api import ws_manager

        await ws_manager.broadcast(
            "pick_update",
            {
                "signal_id": signal_id,
                "symbol": signal_data["symbol"],
                "direction": signal_data["direction"],
                "strategy": signal_data["strategy"],
                "price": payload.price,
                "source": "tradingview",
            },
        )
    except Exception:
        logger.debug("WebSocket broadcast failed (no clients connected?).")

    return WebhookAck(
        status="ok",
        signal_id=signal_id,
        symbol=signal_data["symbol"],
        action=payload.action,
        message=f"Signal created from TradingView alert ({payload.strategy}).",
    )

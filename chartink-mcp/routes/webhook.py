"""Chartink alert webhook receiver."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from loguru import logger
from pydantic import BaseModel

from app.config import get_settings
from app.dependencies import RepositoryDep

router = APIRouter(prefix="/webhook", tags=["webhook"])


class ChartinkWebhookPayload(BaseModel):
    stocks: str = ""
    trigger_prices: str = ""
    triggered_at: str = ""
    scan_name: str = ""
    scan_url: str = ""
    alert_name: str = ""
    webhook_url: str = ""


@router.post("/chartink")
async def chartink_webhook(
    payload: ChartinkWebhookPayload,
    repository: RepositoryDep,
    x_webhook_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    settings = get_settings()
    if settings.webhook_secret and x_webhook_secret != settings.webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    logger.info(
        "Chartink webhook received: scan={} alert={} stocks={}",
        payload.scan_name,
        payload.alert_name,
        payload.stocks,
    )

    stock_list = [s.strip() for s in payload.stocks.split(",") if s.strip()]
    price_list = [p.strip() for p in payload.trigger_prices.split(",") if p.strip()]

    alert_record = {
        "name": payload.alert_name or f"Webhook: {payload.scan_name}",
        "scan_name": payload.scan_name,
        "scan_slug": payload.scan_url,
        "scan_url": f"https://chartink.com/screener/{payload.scan_url}",
        "webhook_url": payload.webhook_url,
        "is_active": True,
        "last_triggered_at": datetime.now(timezone.utc).isoformat(),
        "triggered_stocks": stock_list,
        "trigger_prices": price_list,
        "triggered_at_label": payload.triggered_at,
        "raw_payload": payload.model_dump(),
    }

    existing = repository.list_alerts()
    updated = [a for a in existing if a.scan_name != payload.scan_name]
    repository.replace_alerts(
        [
            {
                "id": a.external_id,
                "name": a.name,
                "scan_name": a.scan_name,
                "scan_slug": a.scan_slug,
                "scan_url": a.scan_url,
                "webhook_url": a.webhook_url,
                "is_active": a.is_active,
            }
            for a in updated
        ]
        + [alert_record]
    )

    return {
        "received": True,
        "stocks_count": len(stock_list),
        "scan_name": payload.scan_name,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }

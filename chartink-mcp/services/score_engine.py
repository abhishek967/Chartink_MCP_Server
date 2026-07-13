"""Provider-agnostic stock scoring engine."""

from __future__ import annotations

from typing import Any

from providers.base import StockObservation


def calculate_stock_score(stock: StockObservation) -> dict[str, Any]:
    """
    Score a normalized stock observation.

    Components are independent of Chartink vs MarketSmith; optional MS fields
    boost technical_score when present.
    """
    scan_count = max(0, int(stock.scan_count or len(stock.triggered_scans)))
    per_chg = float(stock.per_chg or 0.0)
    volume = float(stock.volume or 0.0)

    # Confluence: more scan hits → higher score (cap at 5 scans = 100)
    confluence_score = round(min(100.0, scan_count * 20.0), 2)

    # Momentum from day change
    if per_chg >= 5:
        momentum_score = 100.0
    elif per_chg >= 3:
        momentum_score = 80.0
    elif per_chg >= 1:
        momentum_score = 60.0
    elif per_chg >= 0:
        momentum_score = 40.0
    elif per_chg >= -2:
        momentum_score = 20.0
    else:
        momentum_score = 0.0

    # Volume heuristic (absolute volume bands; Chartink units vary)
    if volume >= 1_000_000:
        volume_score = 100.0
    elif volume >= 500_000:
        volume_score = 80.0
    elif volume >= 100_000:
        volume_score = 60.0
    elif volume > 0:
        volume_score = 40.0
    else:
        volume_score = 20.0

    # Trend proxy from close + positive momentum
    close = float(stock.close_price or 0.0)
    if close > 0 and per_chg > 0:
        trend_score = min(100.0, 50.0 + per_chg * 5.0)
    elif close > 0:
        trend_score = max(0.0, 40.0 + per_chg * 5.0)
    else:
        trend_score = 0.0
    trend_score = round(trend_score, 2)

    # Technical base from available Chartink fields
    technical_score = round(
        (momentum_score * 0.4) + (volume_score * 0.3) + (trend_score * 0.3),
        2,
    )

    # Optional MarketSmith boost (no-op when fields are None)
    ms_bonus = 0.0
    ms_parts: dict[str, Any] = {}
    if stock.rs_rating is not None:
        ms_parts["rs_rating"] = stock.rs_rating
        ms_bonus += min(10.0, max(0, stock.rs_rating) / 10.0)
    if stock.eps_rating is not None:
        ms_parts["eps_rating"] = stock.eps_rating
        ms_bonus += min(10.0, max(0, stock.eps_rating) / 10.0)
    if stock.composite_rating is not None:
        ms_parts["composite_rating"] = stock.composite_rating
        ms_bonus += min(10.0, max(0, stock.composite_rating) / 10.0)

    final_score = round(
        min(
            100.0,
            (confluence_score * 0.35)
            + (technical_score * 0.35)
            + (momentum_score * 0.15)
            + (volume_score * 0.10)
            + (trend_score * 0.05)
            + ms_bonus,
        ),
        2,
    )

    breakdown = {
        "technical_score": technical_score,
        "confluence_score": confluence_score,
        "volume_score": volume_score,
        "momentum_score": momentum_score,
        "trend_score": trend_score,
        "marketsmith_bonus": round(ms_bonus, 2),
        "marketsmith_inputs": ms_parts,
        "scan_count": scan_count,
        "triggered_scans": list(stock.triggered_scans),
        "per_chg": per_chg,
        "volume": volume,
        "close_price": close,
    }

    return {
        "technical_score": technical_score,
        "confluence_score": confluence_score,
        "volume_score": volume_score,
        "momentum_score": momentum_score,
        "trend_score": trend_score,
        "final_score": final_score,
        "score_breakdown": breakdown,
    }

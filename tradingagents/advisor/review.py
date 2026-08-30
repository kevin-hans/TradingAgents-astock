"""决策纪律巡检（spec §7 P3）。零 LLM，纯函数检查 + 可注入数据源。"""
import calendar
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel

from tradingagents.advisor.scenario_io import ScenarioArtifact
from tradingagents.advisor.types import InvestorVector
from tradingagents.agents.schemas import ScenarioBucket


FRESHNESS_THRESHOLD = 0.05


class BucketCheck(BaseModel):
    horizon_months: int
    stop_triggered: bool
    target_hit: bool
    horizon_expired: bool
    fresh_warning: Optional[bool]
    w_star_hint: Optional[float] = None


class ReviewItem(BaseModel):
    ticker: str
    date: str
    rating: str
    price: float
    p0: Optional[float]
    checks: list[BucketCheck]
    falsification: list[str]


class SkippedItem(BaseModel):
    ticker: str
    date: str
    reason: Literal["quote_failed", "no_scenario"]


class ReviewReport(BaseModel):
    generated_at: str
    items: list[ReviewItem]
    skipped: list[SkippedItem]
    manual_checklist: list[str]


def _add_months(d: date, months: int) -> date:
    """自然月加法，月末 clamp（1-31 + 1月 = 2-28）。"""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def check_bucket(
    bucket: ScenarioBucket,
    price: float,
    today: date,
    analysis_date: date,
    p0: Optional[float],
) -> BucketCheck:
    """单桶四项检查：止损 / 目标 / 期限 / 新鲜度。w* 由上层补。"""
    kl = bucket.key_levels
    stop_triggered = price <= kl.stop
    target_hit = price >= kl.target

    expiry = _add_months(analysis_date, bucket.horizon_months)
    horizon_expired = today > expiry

    if p0 is not None and p0 > 0:
        fresh_warning = abs(price - p0) / p0 > FRESHNESS_THRESHOLD
    else:
        fresh_warning = None

    return BucketCheck(
        horizon_months=bucket.horizon_months,
        stop_triggered=stop_triggered,
        target_hit=target_hit,
        horizon_expired=horizon_expired,
        fresh_warning=fresh_warning,
    )


def build_review_item(
    entry: dict,
    artifact: ScenarioArtifact,
    price: float,
    p0: Optional[float],
    today: date,
) -> ReviewItem:
    """把 pending 决策 + scenario 制品 + 现价组装成 ReviewItem（每桶一查）。"""
    analysis_date = date.fromisoformat(artifact.trade_date)
    checks = [
        check_bucket(b, price=price, today=today,
                     analysis_date=analysis_date, p0=p0)
        for b in artifact.scenario_buckets
    ]
    falsification = (
        list(artifact.falsification.conditions) if artifact.falsification else []
    )
    return ReviewItem(
        ticker=entry["ticker"],
        date=entry["date"],
        rating=entry["rating"],
        price=price,
        p0=p0,
        checks=checks,
        falsification=falsification,
    )


def _memory_config() -> dict:
    import os
    return {"memory_log_path": os.environ.get(
        "TRADINGAGENTS_MEMORY_LOG_PATH",
        os.path.join(os.path.expanduser("~"), ".tradingagents",
                     "memory", "trading_memory.md"),
    )}


def _default_quotes(codes):
    from tradingagents.dataflows.a_stock import _tencent_quote
    return _tencent_quote(codes)


def _default_p0(ticker, trade_date):
    from tradingagents.agents.utils.scenario_check import fetch_p0
    return fetch_p0(ticker, trade_date)


def run_review(
    quotes_provider=None,
    p0_provider=None,
    vector: Optional[InvestorVector] = None,
    today: Optional[date] = None,
) -> ReviewReport:
    """扫 pending 决策 → 拉现价/p0 → 逐条检查。

    quotes/p0 provider 缺省走真数据源（tencent / fetch_p0），测试注入 fake。
    skipped: quote_failed（行情拉不到）或 no_scenario（无 scenario 制品）。
    """
    from tradingagents.agents.utils.memory import TradingMemoryLog

    from tradingagents.advisor.engine import advise as _engine_advise
    from tradingagents.advisor.scenario_io import (
        ScenarioNotFoundError,
        load_scenario,
    )
    from tradingagents.advisor.types import AdvisorConfig

    today = today or date.today()
    quotes_fn = quotes_provider or _default_quotes
    p0_fn = p0_provider or _default_p0

    log = TradingMemoryLog(_memory_config())
    pending = log.get_pending_entries()
    if not pending:
        return ReviewReport(generated_at=today.isoformat(), items=[],
                            skipped=[], manual_checklist=[])

    tickers = sorted({e["ticker"] for e in pending})
    try:
        quotes = quotes_fn(tickers)
    except Exception:
        quotes = {}

    items: list[ReviewItem] = []
    skipped: list[SkippedItem] = []
    checklist: list[str] = []

    for entry in pending:
        ticker, entry_date = entry["ticker"], entry["date"]
        try:
            artifact = load_scenario(ticker, date=entry_date)
        except ScenarioNotFoundError:
            skipped.append(SkippedItem(ticker=ticker, date=entry_date,
                                       reason="no_scenario"))
            continue
        q = quotes.get(ticker)
        if not q or not q.get("price"):
            skipped.append(SkippedItem(ticker=ticker, date=entry_date,
                                       reason="quote_failed"))
            continue
        p0 = p0_fn(ticker, entry_date)
        item = build_review_item(entry, artifact, price=q["price"], p0=p0, today=today)
        if vector is not None:
            for i, bucket in enumerate(artifact.scenario_buckets):
                if item.checks[i].stop_triggered:
                    result = _engine_advise(
                        bucket, vector, AdvisorConfig(),
                        ticker=ticker, date=entry_date, rating=artifact.rating,
                    )
                    item.checks[i].w_star_hint = result.trace.w_star
        items.append(item)
        checklist.extend(item.falsification)

    return ReviewReport(
        generated_at=today.isoformat(),
        items=items, skipped=skipped, manual_checklist=checklist,
    )

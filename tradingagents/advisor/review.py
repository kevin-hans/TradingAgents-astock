"""决策纪律巡检（spec §7 P3）。零 LLM，纯函数检查 + 可注入数据源。"""
import calendar
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel

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

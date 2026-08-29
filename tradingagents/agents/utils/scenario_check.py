# tradingagents/agents/utils/scenario_check.py
"""Deterministic validation for the PM scenario tree (spec §4.2-4.3).

All arithmetic/anchoring/direction rules live here so the retry message can
name the exact violation. Structural typing is enforced by pydantic; anything
this module returns is a semantic violation list (empty == valid).
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from tradingagents.agents.schemas import PortfolioDecision, PortfolioRating

logger = logging.getLogger(__name__)

REQUIRED_HORIZONS = (6, 12)
BASE_PROB_RANGE = (0.35, 0.55)
ANCHOR_TOL = 0.05
BEARISH_RATINGS = {
    PortfolioRating.HOLD, PortfolioRating.UNDERWEIGHT, PortfolioRating.SELL,
}

_HORIZON_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:months?|个月|月|years?|年)", re.IGNORECASE)


def parse_horizon_months(text: Optional[str]) -> int:
    """Parse horizon text to months.

    Rule: Match the number immediately followed by a unit.
    - '3-6 months' → 6 (the 6 is attached to 'months')
    - '6-12个月' → 12 (the 12 is attached to '个月')
    - '1-2 years' → 24 (the 2 is attached to 'years', then ×12)
    - '6 months' → 6 (single number with unit)
    - '1 year' → 12 (single number with unit, years ×12)
    - Invalid/empty → default 6

    This implements the 'number-adjacent-to-unit' semantics as specified in
    the task description. Test expectations were updated accordingly.
    """
    if not text:
        return 6
    m = _HORIZON_RE.search(str(text))
    if not m:
        return 6
    value = float(m.group(1))
    # Check if the matched unit indicates years
    if re.search(r"year|年", m.group(0), re.IGNORECASE):
        value *= 12
    return max(1, int(value))


def _main_bucket(decision: PortfolioDecision, buckets):
    target = parse_horizon_months(decision.time_horizon)
    return min(buckets, key=lambda b: abs(b.horizon_months - target))


def validate_scenario_tree(decision: PortfolioDecision, p0: Optional[float]) -> list[str]:
    """Return a list of human-readable violations; empty list means valid.

    ``p0`` is the analysis-date close. When None, anchor checks are skipped
    (the artifact is later flagged ``unanchored``).
    """
    buckets = decision.scenario_buckets
    if not buckets:
        return ["scenario tree missing"]

    violations: list[str] = []
    horizons = sorted(b.horizon_months for b in buckets)
    if horizons != list(REQUIRED_HORIZONS):
        violations.append(
            f"expected exactly two buckets with horizons 6 and 12 months, got {horizons}"
        )

    bearish = decision.rating in BEARISH_RATINGS
    main = _main_bucket(decision, buckets)

    for b in buckets:
        tag = f"{b.horizon_months}M"
        names = sorted(s.name for s in b.scenarios)
        if names != ["base", "bear", "bull"]:
            violations.append(f"{tag}: scenarios must be exactly bull/base/bear, got {names}")
            continue
        s = {x.name: x for x in b.scenarios}

        total = sum(x.prob for x in b.scenarios)
        if not 0.99 <= total <= 1.01:
            violations.append(f"{tag}: probabilities sum to {total:.3f}, expected 1.0")
        if not BASE_PROB_RANGE[0] <= s["base"].prob <= BASE_PROB_RANGE[1]:
            violations.append(
                f"{tag}: base prob {s['base'].prob:.2f} outside [0.35, 0.55]"
            )
        if not s["bull"].expected_return > s["base"].expected_return > s["bear"].expected_return:
            violations.append(f"{tag}: returns must be strictly bull > base > bear")
        if bearish and s["bull"].prob > s["bear"].prob:
            violations.append(
                f"{tag}: rating {decision.rating.value} requires P(bear) ≥ P(bull)"
            )

        kl = b.key_levels
        if not kl.stop < kl.entry_low <= kl.entry_high < kl.target:
            violations.append(
                f"{tag}: key levels must satisfy stop < entry_low ≤ entry_high < target"
            )

        if p0 is not None:
            bear_anchor = kl.stop / p0 - 1
            bull_anchor = kl.target / p0 - 1
            if abs(s["bear"].expected_return - bear_anchor) > ANCHOR_TOL:
                violations.append(
                    f"{tag}: bear return {s['bear'].expected_return:+.1%} not anchored "
                    f"to stop ({bear_anchor:+.1%}, tol ±5pp)"
                )
            if abs(s["bull"].expected_return - bull_anchor) > ANCHOR_TOL:
                violations.append(
                    f"{tag}: bull return {s['bull'].expected_return:+.1%} not anchored "
                    f"to target ({bull_anchor:+.1%}, tol ±5pp)"
                )

        if b is main:
            mu = sum(x.prob * x.expected_return for x in b.scenarios)
            if bearish and mu > 0.02:
                violations.append(
                    f"main bucket ({tag}) mean return {mu:+.1%} contradicts rating "
                    f"{decision.rating.value} (≤ Hold expects μ ≤ +2%)"
                )
            if not bearish and mu <= 0:
                violations.append(
                    f"main bucket ({tag}) mean return {mu:+.1%} contradicts rating "
                    f"{decision.rating.value} (≥ Overweight expects μ > 0)"
                )
    return violations


def fetch_p0(ticker: str, trade_date: str) -> Optional[float]:
    """Analysis-date close for anchor checks; None on any failure → unanchored."""
    try:
        import pandas as pd

        from tradingagents.dataflows.a_stock import _sina_kline_fallback

        df = _sina_kline_fallback(ticker)
        if df is None or df.empty:
            return None
        ts = pd.to_datetime(trade_date)
        df = df[df["Date"] <= ts]
        if df.empty:
            return None
        return float(df.iloc[-1]["Close"])
    except Exception as exc:  # 数据拿不到不是错误路径：降级为 unanchored
        logger.info("fetch_p0 failed for %s@%s: %s", ticker, trade_date, exc)
        return None

"""Pydantic schemas used by agents that produce structured output.

The framework's primary artifact is still prose: each agent's natural-language
reasoning is what users read in the saved markdown reports and what the
downstream agents read as context.  Structured output is layered onto the
three decision-making agents (Research Manager, Trader, Portfolio Manager)
so that:

- Their outputs follow consistent section headers across runs and providers
- Each provider's native structured-output mode is used (json_schema for
  OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic)
- Schema field descriptions become the model's output instructions, freeing
  the prompt body to focus on context and the rating-scale guidance
- A render helper turns the parsed Pydantic instance back into the same
  markdown shape the rest of the system already consumes, so display,
  memory log, and saved reports keep working unchanged
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared rating types
# ---------------------------------------------------------------------------


class PortfolioRating(str, Enum):
    """5-tier rating used by the Research Manager and Portfolio Manager."""

    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class TraderAction(str, Enum):
    """3-tier transaction direction used by the Trader.

    The Trader's job is to translate the Research Manager's investment plan
    into a concrete transaction proposal: should the desk execute a Buy, a
    Sell, or sit on Hold this round.  Position sizing and the nuanced
    Overweight / Underweight calls happen later at the Portfolio Manager.
    """

    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"


# ---------------------------------------------------------------------------
# Research Manager
# ---------------------------------------------------------------------------


class ResearchPlan(BaseModel):
    """Structured investment plan produced by the Research Manager.

    Hand-off to the Trader: the recommendation pins the directional view,
    the rationale captures which side of the bull/bear debate carried the
    argument, and the strategic actions translate that into concrete
    instructions the trader can execute against.
    """

    recommendation: PortfolioRating = Field(
        description=(
            "The investment recommendation. Exactly one of Buy / Overweight / "
            "Hold / Underweight / Sell. Reserve Hold for situations where the "
            "evidence on both sides is genuinely balanced; otherwise commit to "
            "the side with the stronger arguments."
        ),
    )
    rationale: str = Field(
        description=(
            "Conversational summary of the key points from both sides of the "
            "debate, ending with which arguments led to the recommendation. "
            "Speak naturally, as if to a teammate."
        ),
    )
    strategic_actions: str = Field(
        description=(
            "Concrete steps for the trader to implement the recommendation, "
            "consistent with the rating."
        ),
    )


def render_research_plan(plan: ResearchPlan) -> str:
    """Render a ResearchPlan to markdown for storage and the trader's prompt context."""
    return "\n".join([
        f"**Recommendation**: {plan.recommendation.value}",
        "",
        f"**Rationale**: {plan.rationale}",
        "",
        f"**Strategic Actions**: {plan.strategic_actions}",
    ])


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------


class TraderProposal(BaseModel):
    """Structured transaction proposal produced by the Trader.

    The trader reads the Research Manager's investment plan and the analyst
    reports, then states a direction and the reasoning behind it.

    It deliberately carries **no executable price levels** — no entry price,
    no stop-loss, no position size. This project is a research and education
    implementation of the upstream TradingAgents framework, and concrete trade
    levels for a named security are what turn a research tool into an
    investment-advisory product. The capability is not shipped here; a
    downstream fork that wants it can add it under its own responsibility.
    """

    action: TraderAction = Field(
        description="The transaction direction. Exactly one of Buy / Hold / Sell.",
    )
    reasoning: str = Field(
        description=(
            "The case for this action, anchored in the analysts' reports and "
            "the research plan. Two to four sentences. Do not quote specific "
            "entry, stop-loss or position-size levels."
        ),
    )


def render_trader_proposal(proposal: TraderProposal) -> str:
    """Render a TraderProposal to markdown.

    The trailing ``FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`` line is
    preserved for backward compatibility with the analyst stop-signal text
    and any external code that greps for it.
    """
    return "\n".join([
        f"**Action**: {proposal.action.value}",
        "",
        f"**Reasoning**: {proposal.reasoning}",
        "",
        f"FINAL TRANSACTION PROPOSAL: **{proposal.action.value.upper()}**",
    ])


# ---------------------------------------------------------------------------
# Portfolio Manager
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Scenario tree (P1 of the scenario-vector advisor; spec §4.1)
# ---------------------------------------------------------------------------


class Scenario(BaseModel):
    """One outcome of a horizon bucket, anchored to the debate evidence."""

    name: Literal["bull", "base", "bear"] = Field(
        description="Exactly one of bull / base / bear.",
    )
    thesis: str = Field(
        description=(
            "One sentence citing the SPECIFIC bull/bear debate argument this "
            "scenario rests on. Generic filler like 'market sentiment improves' "
            "is not acceptable."
        ),
    )
    expected_return: float = Field(
        description=(
            "Expected TOTAL return from the analysis-date close to the end of "
            "the bucket horizon, as a decimal fraction (0.25 = +25%, -0.18 = -18%). "
            "Anchor to the key levels of the same bucket: bear ≈ stop/close − 1, "
            "bull ≈ target/close − 1."
        ),
    )
    prob: float = Field(
        description=(
            "Probability as a decimal fraction. The three probabilities of a "
            "bucket must sum to 1.0. Base sits in [0.35, 0.55]. When the final "
            "rating is Hold or below, P(bear) ≥ P(bull); when Overweight or "
            "above, P(bull) ≥ P(bear)."
        ),
    )


class KeyLevels(BaseModel):
    """Reference price levels for one horizon bucket (fork decision: shipped)."""

    stop: float = Field(description="Invalidation/stop level, below analysis-date context.")
    entry_low: float = Field(description="Lower bound of the suggested entry zone.")
    entry_high: float = Field(description="Upper bound of the suggested entry zone.")
    target: float = Field(description="Price target for the bucket horizon.")


class ScenarioBucket(BaseModel):
    """Scenario tree for one horizon (v1 ships the 6- and 12-month buckets)."""

    horizon_months: int = Field(description="Bucket horizon in months; v1 uses 6 or 12.")
    scenarios: list[Scenario] = Field(
        description="Exactly three scenarios: bull, base, bear.",
    )
    key_levels: KeyLevels = Field(
        description="Price levels for this bucket; must satisfy stop < entry_low ≤ entry_high < target.",
    )


class Falsification(BaseModel):
    """Concrete, checkable conditions that would falsify the decision (spec §4)."""

    conditions: list[str] = Field(
        description=(
            "1-3 conditions, each checkable against later data: price levels "
            "(e.g. 'daily close below 1450 on volume'), fundamental thresholds "
            "(e.g. 'receivables turnover days > 90'), or events."
        ),
    )


class PortfolioDecision(BaseModel):
    """Structured output produced by the Portfolio Manager.

    The model fills every field as part of its primary LLM call; no separate
    extraction pass is required. Field descriptions double as the model's
    output instructions, so the prompt body only needs to convey context and
    the rating-scale guidance.

    Like :class:`TraderProposal` this stays level-free in its prose fields, but
    this fork (kevin-hans, 2026-08-29) DOES ship executable levels inside the
    structured ``scenario_buckets`` — the upstream docstring explicitly left
    that to a downstream fork's responsibility. Every artifact and consumer
    built on it carries the research-tool disclaimer (spec §13).
    """

    rating: PortfolioRating = Field(
        description=(
            "The final position rating. Exactly one of Buy / Overweight / Hold / "
            "Underweight / Sell, picked based on the analysts' debate."
        ),
    )
    executive_summary: str = Field(
        description=(
            "A concise summary of what drove the rating and the main "
            "considerations on each side. Two to four sentences. Do not quote "
            "specific entry, stop-loss, position-size or target-price levels."
        ),
    )
    investment_thesis: str = Field(
        description=(
            "Detailed reasoning anchored in specific evidence from the analysts' "
            "debate. If prior lessons are referenced in the prompt context, "
            "incorporate them; otherwise rely solely on the current analysis."
        ),
    )
    time_horizon: Optional[str] = Field(
        default=None,
        description="Optional analysis horizon, e.g. '3-6 months'.",
    )
    scenario_buckets: list[ScenarioBucket] = Field(
        default_factory=list,
        description=(
            "Scenario tree for the reusable advisory artifact. Provide exactly "
            "two buckets (horizon_months 6 and 12). Follow the anchoring and "
            "probability rules of each nested field exactly."
        ),
    )
    falsification: Optional[Falsification] = Field(
        default=None,
        description="1-3 concrete conditions that, if met, falsify this decision.",
    )


def render_pm_decision(decision: PortfolioDecision) -> str:
    """Render a PortfolioDecision back to the markdown shape the rest of the system expects.

    Memory log, CLI display, and saved report files all read this markdown,
    so the rendered output preserves the exact section headers (``**Rating**``,
    ``**Executive Summary**``, ``**Investment Thesis**``) that downstream
    parsers and the report writers already handle.
    """
    parts = [
        f"**Rating**: {decision.rating.value}",
        "",
        f"**Executive Summary**: {decision.executive_summary}",
        "",
        f"**Investment Thesis**: {decision.investment_thesis}",
    ]
    if decision.time_horizon:
        parts.extend(["", f"**Time Horizon**: {decision.time_horizon}"])
    if decision.scenario_buckets:
        parts.append("")
        parts.append("**Scenario Tree**:")
        for b in decision.scenario_buckets:
            summary = " / ".join(
                f"{s.name} {s.expected_return:+.0%}@{s.prob:.0%}"
                for s in b.scenarios
            )
            parts.append(f"- {b.horizon_months}M: {summary}")
            kl = b.key_levels
            parts.append(
                f"  levels: stop {kl.stop}, entry {kl.entry_low}-{kl.entry_high}, target {kl.target}"
            )
    if decision.falsification:
        parts.append("")
        parts.append("**Falsification**:")
        for cond in decision.falsification.conditions:
            parts.append(f"- {cond}")
    return "\n".join(parts)

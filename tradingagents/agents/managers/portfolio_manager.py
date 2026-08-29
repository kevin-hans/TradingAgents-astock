"""Portfolio Manager: synthesises the risk-analyst debate into the final decision.

Uses LangChain's ``with_structured_output`` so the LLM produces a typed
``PortfolioDecision`` directly, in a single call.  The result is rendered
back to markdown for storage in ``final_trade_decision`` so memory log,
CLI display, and saved reports continue to consume the same shape they do
today.  When a provider does not expose structured output, the agent falls
back gracefully to free-text generation.
"""

from __future__ import annotations

import logging

from tradingagents.agents.schemas import PortfolioDecision, render_pm_decision
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
)
from tradingagents.agents.utils.scenario_check import fetch_p0, validate_scenario_tree
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext_typed,
)

logger = logging.getLogger(__name__)


# Fork decision (2026-08-29): executable levels ARE shipped, but only inside
# the structured scenario fields — prose sections stay level-free so the
# memory log and report readers keep their current shape.
_LEVELS_RULE = (
    "\n- State entry/stop/target levels ONLY inside the structured scenario "
    "fields; keep the prose summary and thesis free of specific levels."
)


def create_portfolio_manager(llm):
    structured_llm = bind_structured(llm, PortfolioDecision, "Portfolio Manager")

    def portfolio_manager_node(state) -> dict:
        instrument_context = build_instrument_context(state["company_of_interest"])

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        research_plan = state["investment_plan"]
        trader_plan = state["trader_investment_plan"]

        past_context = state.get("past_context", "")
        lessons_line = (
            f"- Lessons from prior decisions and outcomes:\n{past_context}\n"
            if past_context
            else ""
        )

        prompt = f"""As the Portfolio Manager, synthesize the risk analysts' debate and deliver the final trading decision.

{instrument_context}

---

**A-Stock Trading Constraints** (must factor into your decision):
- T+1 settlement: shares bought today cannot be sold until the next trading day
- Daily price limits: main board ±10%, STAR/ChiNext ±20%, Beijing Stock Exchange ±30%.
  Risk-warning stocks (ST/*ST) do NOT get a narrower band: since 2026-07-06 main-board
  ST/*ST moved from ±5% to ±10% (same as ordinary main-board shares), and STAR/ChiNext
  ST/*ST have always been ±20%.
- Newly listed stocks have NO price limit for their first 5 trading days (first day only
  on the Beijing Stock Exchange) — this matters most for recently-IPO'd names.
- Minimum lot size: 100 shares (1 手) on main board and ChiNext, in 100-share multiples;
  STAR board is 200 shares minimum, incrementing by 1 share; Beijing Stock Exchange is
  100 shares minimum, incrementing by 1 share.
- Trading hours (Beijing time): opening call auction 09:15-09:25, continuous trading
  09:30-11:30 and 13:00-14:57, closing call auction 14:57-15:00. Since 2026-07-06 the
  after-hours fixed-price session (15:05-15:30, traded at the closing price) covers all
  A-shares and ETFs.
- ST/delisting risk: ST or *ST status signals regulatory warning; factor into position sizing
- Margin eligibility: not all A-shares are margin-eligible; assume cash-only unless stated

---

**Rating Scale** (use exactly one):
- **Buy**: Strong conviction to enter or add to position
- **Overweight**: Favorable outlook, gradually increase exposure
- **Hold**: Maintain current position, no action needed
- **Underweight**: Reduce exposure, take partial profits
- **Sell**: Exit position or avoid entry

**Context:**
- Research Manager's investment plan: **{research_plan}**
- Trader's transaction proposal: **{trader_plan}**
{lessons_line}
**Risk Analysts Debate History:**
{history}

---

Be decisive and ground every conclusion in specific evidence from the analysts.{_LEVELS_RULE}{get_language_instruction()}"""

        markdown, decision = invoke_structured_or_freetext_typed(
            structured_llm,
            llm,
            prompt,
            render_pm_decision,
            "Portfolio Manager",
        )

        scenario_meta = {"available": False}
        scenario_tree = None
        if decision is not None:
            try:
                if decision.scenario_buckets:
                    p0 = fetch_p0(state["company_of_interest"], state["trade_date"])
                    violations = validate_scenario_tree(decision, p0)
                    if violations:
                        retry_prompt = (
                            prompt
                            + "\n\n---\nYour structured scenario tree violated these rules; "
                            "fix them and answer again:\n"
                            + "\n".join(f"- {v}" for v in violations)
                        )
                        try:
                            decision = structured_llm.invoke(retry_prompt)
                            markdown = render_pm_decision(decision)
                            violations = validate_scenario_tree(decision, p0)
                        except Exception:
                            violations = ["structured retry invocation failed"]
                    if violations:
                        logger.warning(
                            "Portfolio Manager: scenario tree degraded after retry: %s",
                            violations,
                        )
                        decision.scenario_buckets = []
                        decision.falsification = None
                        markdown = render_pm_decision(decision)
                        scenario_meta["degraded"] = violations
                    else:
                        scenario_meta["available"] = True
                        if p0 is None:
                            scenario_meta["unanchored"] = True
                scenario_tree = {
                    "decision": decision.model_dump(mode="json"),
                    "scenario_meta": scenario_meta,
                }
            except Exception as exc:
                # 情景附属功能绝不能阻塞主管线：任何意外异常都降级为无树。
                logger.warning(
                    "Portfolio Manager: scenario tree failed unexpectedly (%s); degrading",
                    exc,
                )
                decision.scenario_buckets = []
                decision.falsification = None
                markdown = render_pm_decision(decision)
                scenario_meta = {"available": False, "degraded": [f"unexpected error: {exc}"]}
                scenario_tree = {
                    "decision": decision.model_dump(mode="json"),
                    "scenario_meta": scenario_meta,
                }

        new_risk_debate_state = {
            "judge_decision": markdown,
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state["current_aggressive_response"],
            "current_conservative_response": risk_debate_state["current_conservative_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": markdown,
            "scenario_tree": scenario_tree,
        }

    return portfolio_manager_node

"""Optional LLM layer: a small tool-calling agent over the Service.

Design rules (the interview-worthy part):
  • The LLM never decides amounts. Every number comes from a tool that calls
    the deterministic engine; the model only routes questions and explains.
  • Tools are read-only, except `propose_buy`, which only *proposes*: the bot
    shows a confirm button and nothing is written until the human taps it.
  • Provider-agnostic: any OpenAI-compatible endpoint. Groq and Gemini have
    free tiers, and Ollama runs locally for $0.
  • If no key is configured, the bot falls back to the rule-based intent parser.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

import httpx

from pda.config import normalize_ticker
from pda.service import Service

log = logging.getLogger(__name__)

PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "GROQ_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash", "GEMINI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct:free", "OPENROUTER_API_KEY"),
    "ollama": ("http://localhost:11434/v1", "llama3.1", None),
}

def system_prompt(strategy) -> str:
    """Describe the user's own plan to the model, built from their strategy file."""
    g = strategy.guardrails
    rules = ["never sell", "rebalance only with new money"]
    if g.max_single_stock_pct is not None:
        rules.append(f"no single stock above {g.max_single_stock_pct:g}%")
    rules += [f"{t} max {c:g}%" for t, c in g.per_ticker_caps.items()]
    if g.has_core_ratio:
        rules.append(f"{g.core_ticker} at least {g.core_min_multiple:g}x {g.core_versus}")
    if g.cushions:
        rules.append(f"{' and '.join(g.cushions)} are the biggest defensive buys")
    if strategy.mode == "auto":
        how = "each month the money goes to whatever is furthest below target"
    else:
        how = "a fixed monthly split"
        if strategy.slot_amount:
            how += " plus a stock slot for the candidate furthest below target"
    cur = strategy.currency
    return f"""You are the assistant inside a personal, buy-only investing bot.
The user's plan "{strategy.name}": invest {cur}{strategy.monthly_amount:,.0f}/month toward a goal of
{cur}{strategy.goal_value:,.0f}; {how}. Guardrails: {"; ".join(rules)}.

Rules:
- Get every number from a tool. Never invent prices, amounts or returns.
- Never recommend selling. If the user wants to sell in a drop, remind them the plan
  is buy-only and show them the stress test or the drawdown context.
- To record a purchase the user says they made, call propose_buy. The user confirms it with a button.
- Don't give personalized advice beyond this plan. If asked about new stocks or timing the
  market, explain how it would fit the plan's rules.
- Be brief: plain text, at most ~8 lines, amounts in {cur}."""


TOOLS = [
    {"type": "function", "function": {
        "name": "get_portfolio",
        "description": "Current value, gain, and every ticker's actual vs target %.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_monthly_plan",
        "description": "This month's buy list with reasons and guardrail adjustments.",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "number", "description": "Dollars to invest; default is the monthly amount."}}}}},
    {"type": "function", "function": {
        "name": "get_extra_cash_plan",
        "description": "How to deploy one-off extra cash (bonus, refund) into the biggest gaps vs target.",
        "parameters": {"type": "object", "properties": {"amount": {"type": "number"}}, "required": ["amount"]}}},
    {"type": "function", "function": {
        "name": "check_guardrails",
        "description": "Status of every guardrail rule against the current portfolio.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "project_goal",
        "description": "Months until the portfolio reaches the goal, at 4%/7%/10% annual returns.",
        "parameters": {"type": "object", "properties": {
            "monthly": {"type": "number", "description": "Monthly contribution to assume."}}}}},
    {"type": "function", "function": {
        "name": "stress_test",
        "description": "Paper losses under AI sell-off / bear market / correction scenarios.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "propose_buy",
        "description": "Propose recording a purchase the user says they made. Requires user confirmation.",
        "parameters": {"type": "object", "properties": {
            "ticker": {"type": "string"},
            "dollars": {"type": "number"},
            "price": {"type": "number", "description": "Fill price per share if the user gave one."}},
            "required": ["ticker", "dollars"]}}},
]


@dataclass
class AgentReply:
    text: str
    proposed_buys: list[tuple[str, float, float | None]] = field(default_factory=list)


class LLMClient:
    def __init__(self, provider: str, base_url: str, model: str, api_key: str | None):
        self.provider, self.base_url, self.model, self.api_key = provider, base_url.rstrip("/"), model, api_key

    @classmethod
    def from_env(cls) -> LLMClient | None:
        provider = os.getenv("LLM_PROVIDER", "groq").lower()
        if provider in ("", "none", "off"):
            return None
        base, model, key_env = PROVIDERS.get(provider, (None, None, None))
        base = os.getenv("LLM_BASE_URL", base or "")
        model = os.getenv("LLM_MODEL", model or "")
        key = os.getenv(key_env) if key_env else os.getenv("LLM_API_KEY")
        if not base or not model or (key_env and not key):
            return None
        return cls(provider, base, model, key)

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body: dict = {"model": self.model, "messages": messages, "temperature": 0.2}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]


class Advisor:
    """Tool-calling loop: the model asks for tools, we run them on the Service."""

    def __init__(self, client: LLMClient, service: Service, max_rounds: int = 4):
        self.client, self.service, self.max_rounds = client, service, max_rounds

    def _run_tool(self, name: str, args: dict, reply: AgentReply) -> dict:
        s = self.service
        if name == "get_portfolio":
            snap = s.snapshot()
            return {
                "total_value": round(snap.total_value), "gain": round(snap.gain), "gain_pct": round(snap.gain_pct, 1),
                "goal": s.strategy.goal_value, "ai_heavy_pct": round(snap.ai_pct(), 1),
                "positions": [
                    {"ticker": p.ticker, "value": round(p.value), "actual_pct": p.actual_pct, "target_pct": p.target_pct}
                    for p in snap.positions.values() if p.value > 0 or p.target_pct > 0
                ],
            }
        if name in ("get_monthly_plan", "get_extra_cash_plan"):
            amount = args.get("amount")
            plan, _ = s.plan(amount) if name == "get_monthly_plan" else s.extra(float(amount))
            return {"buys": [{"ticker": ln.ticker, "dollars": ln.amount, "why": ln.reason} for ln in plan.lines],
                    "guardrail_notes": [n.message for n in plan.notes]}
        if name == "check_guardrails":
            return {"rules": [{"rule": c.name, "status": c.status, "detail": c.detail} for c in s.guardrails()]}
        if name == "project_goal":
            monthly = args.get("monthly") or s.strategy.monthly_amount
            return {"monthly": monthly, "goal": s.strategy.goal_value,
                    "projections": [{"annual_return": p.annual_return, "months": p.months} for p in s.goal(monthly=monthly)]}
        if name == "stress_test":
            return {"scenarios": [{"name": r.name, "paper_loss": round(r.loss), "pct": round(r.loss_pct, 1)} for r in s.stress()]}
        if name == "propose_buy":
            ticker = normalize_ticker(str(args["ticker"]))
            dollars = float(args["dollars"])
            if dollars <= 0:
                return {"error": "dollars must be positive"}
            reply.proposed_buys.append((ticker, dollars, args.get("price")))
            return {"status": "pending_user_confirmation", "ticker": ticker, "dollars": dollars}
        return {"error": f"unknown tool {name}"}

    async def answer(self, question: str, history: list[dict] | None = None) -> AgentReply:
        import asyncio

        reply = AgentReply(text="")
        messages = [{"role": "system", "content": system_prompt(self.service.strategy)}, *(history or [])[-6:],
                    {"role": "user", "content": question}]
        for _ in range(self.max_rounds):
            msg = await self.client.chat(messages, TOOLS)
            calls = msg.get("tool_calls") or []
            if not calls:
                reply.text = (msg.get("content") or "").strip()
                return reply
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
            for call in calls:
                fn = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                    result = await asyncio.to_thread(self._run_tool, fn, args, reply)
                except Exception as exc:  # noqa: BLE001 - surface tool errors to the model
                    log.warning("Tool %s failed: %s", fn, exc)
                    result = {"error": str(exc)}
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
        reply.text = "I couldn't finish that. Try /plan, /portfolio or /goal."
        return reply

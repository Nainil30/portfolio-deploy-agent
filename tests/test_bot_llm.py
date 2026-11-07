"""Bot wiring + LLM tool loop, tested without network."""

import asyncio

from pda import formatting as fmt
from pda.bot import Bot
from pda.llm import Advisor


def test_bot_builds_with_handlers_and_jobs(service):
    app = Bot(service, "123456:TEST-token", chat_id=42).build()
    names = {j.name for j in app.job_queue.jobs()}
    assert {"monthly", "daily", "weekly"} <= names
    assert sum(len(g) for g in app.handlers.values()) >= 17


def test_bot_without_chat_id_has_no_jobs(service):
    app = Bot(service, "123456:TEST-token", chat_id=None).build()
    assert not app.job_queue.jobs()


def test_messages_fit_telegram_limit(service):
    plan, snap = service.plan()
    for html in (
        fmt.fmt_plan(plan, snap), fmt.fmt_portfolio(snap, service.strategy), fmt.fmt_drift(snap),
        fmt.fmt_guardrails(service.guardrails()), fmt.HELP,
    ):
        assert len(html) < 4096


class FakeLLM:
    """Scripted model: first asks for a tool, then answers using its output."""

    provider = "fake"

    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    async def chat(self, messages, tools=None):
        self.seen.append(messages[-1])
        return self.script.pop(0)


def _call(name, args="{}"):
    return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": name, "arguments": args}}]}


def test_advisor_uses_tool_results(service):
    llm = FakeLLM([_call("get_monthly_plan"), {"content": "Buy VOO $750 this month."}])
    reply = asyncio.run(Advisor(llm, service).answer("what do I buy?"))
    assert reply.text == "Buy VOO $750 this month."
    assert llm.seen[-1]["role"] == "tool" and "VOO" in llm.seen[-1]["content"]


def test_advisor_propose_buy_does_not_write(service):
    before = service.ledger.holdings()["VOO"].shares
    llm = FakeLLM([_call("propose_buy", '{"ticker": "voo", "dollars": 650}'), {"content": "Recorded once you confirm."}])
    reply = asyncio.run(Advisor(llm, service).answer("I bought 650 of voo"))
    assert reply.proposed_buys == [("VOO", 650.0, None)]
    assert service.ledger.holdings()["VOO"].shares == before  # nothing written until the human confirms

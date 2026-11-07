"""Drive bot handlers with fake Telegram objects (no network)."""

import asyncio
from types import SimpleNamespace

import pytest

from pda.bot import Bot

CHAT = 42


class FakeMessage:
    def __init__(self, text="", document=None):
        self.text = text
        self.document = document
        self.replies = []

    async def reply_text(self, text, **kw):
        self.replies.append(text)


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answered = False

    async def answer(self, *a, **kw):
        self.answered = True

    async def edit_message_reply_markup(self, *a, **kw):
        pass


def make_update(text="", chat=CHAT, query=None, document=None):
    msg = FakeMessage(text, document)
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat, send_action=_noop),
        effective_message=msg,
        callback_query=query,
    ), msg


async def _noop(*a, **kw):
    return None


@pytest.fixture
def bot(service):
    b = Bot(service, "1:x", chat_id=CHAT)
    b.sent = []

    async def capture(update, html, markup=None):
        b.sent.append((html, markup))

    b.send = capture
    return b


def ctx(args=None):
    return SimpleNamespace(args=args or [], chat_data={})


def run(coro):
    return asyncio.run(coro)


def test_stranger_is_rejected(bot):
    upd, msg = make_update("/plan", chat=999)
    run(bot.cmd_plan(upd, ctx()))
    assert not bot.sent and "private bot" in msg.replies[0]


def test_plan_then_button_records_buys(bot, service):
    upd, _ = make_update()
    run(bot.cmd_plan(upd, ctx()))
    html, markup = bot.sent[-1]
    assert "Monthly buy list" in html
    data = markup.inline_keyboard[0][0].callback_data
    assert data.startswith("exec:")

    upd2, _ = make_update(query=FakeQuery(data))
    run(bot.on_button(upd2, ctx()))
    assert "ledger updated" in bot.sent[-1][0]
    assert service.month_done()

    # Pressing again must not double-record.
    run(bot.on_button(upd2, ctx()))
    assert "Already recorded" in bot.sent[-1][0]


def test_plan_with_amount_arg(bot):
    upd, _ = make_update()
    run(bot.cmd_plan(upd, ctx(["3k"])))
    assert "$3,000" in bot.sent[-1][0]


@pytest.mark.parametrize("text,expect", [
    ("bought 400 of nvda", "Recorded"),
    ("how am I doing", "Portfolio"),
    ("I got a 5k bonus", "Extra-cash buy list"),
    ("should I sell?", "No selling"),
    ("🛡 Guardrails", "Guardrails"),
    ("when do I hit the goal", "Road to"),
    ("tell me a joke", "didn't catch"),
])
def test_free_text_routes(bot, text, expect):
    upd, _ = make_update(text)
    run(bot.on_text(upd, ctx()))
    assert expect in bot.sent[-1][0]


def test_bought_command_and_undo(bot, service):
    upd, _ = make_update()
    run(bot.cmd_bought(upd, ctx(["VHT", "250"])))
    assert "VHT" in service.ledger.holdings()
    run(bot.cmd_undo(upd, ctx()))
    assert "VHT" not in service.ledger.holdings()


def test_sold_requires_confirmation(bot, service):
    c = ctx(["VOO", "1"])
    upd, _ = make_update()
    run(bot.cmd_sold(upd, c))
    assert "buy-only" in bot.sent[-1][0]
    assert service.ledger.sell_count() == 0
    token = next(iter(c.chat_data["pending"]))
    run(bot.on_button(make_update(query=FakeQuery(f"no:{token}"))[0], c))
    assert service.ledger.sell_count() == 0


def test_document_import(bot, service):
    content = b"holdings:\n  - {ticker: VOO, shares: 2, avg_cost: 600}\n"

    class File:
        async def download_as_bytearray(self):
            return bytearray(content)

    doc = SimpleNamespace(file_size=len(content), file_name="holdings.yaml")

    async def get_file():
        return File()

    doc.get_file = get_file
    upd, _ = make_update(document=doc)
    run(bot.on_document(upd, ctx()))
    assert "Imported <b>1</b>" in bot.sent[-1][0]
    assert set(service.ledger.holdings()) == {"VOO"}

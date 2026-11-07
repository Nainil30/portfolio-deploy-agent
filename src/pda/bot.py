"""Telegram bot: commands, buttons, free-text, file import and scheduled jobs.

Runs with long polling, so there's no webhook or public URL to host. Any always-on
machine works (your PC, a Raspberry Pi, a free-tier VM).
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, time
from functools import wraps

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from pda import formatting as fmt
from pda import intents
from pda.llm import Advisor, LLMClient
from pda.service import Service, ServiceError

log = logging.getLogger(__name__)

KEYBOARD = ReplyKeyboardMarkup(
    [["📋 Plan", "💼 Portfolio", "🎯 Drift"], ["🛡 Guardrails", "🏁 Goal", "⚙️ Settings"]],
    resize_keyboard=True,
    is_persistent=True,
)

COMMANDS = [
    ("plan", "This month's buy list"),
    ("extra", "Deploy one-off cash, e.g. /extra 5000"),
    ("portfolio", "Value, buckets, goal progress"),
    ("drift", "Every ticker vs target"),
    ("guardrails", "Rule status"),
    ("goal", "Projection to your target"),
    ("stress", "Bad-year scenarios"),
    ("bought", "Record a buy: /bought VOO 650"),
    ("history", "Recent activity"),
    ("undo", "Undo the last record/import"),
    ("import", "How to import holdings"),
    ("settings", "Your plan and settings"),
    ("set", "Change: /set monthly 3000"),
    ("help", "How this works"),
]


class Bot:
    def __init__(self, service: Service, token: str, chat_id: int | None, llm: LLMClient | None = None):
        self.service = service
        self.token = token
        self.chat_id = chat_id
        self.advisor = Advisor(llm, service) if llm else None
        self._lock = asyncio.Lock()  # SQLite + yfinance calls are serialized

    # ── plumbing ───────────────────────────────────────────────────────
    async def run(self, fn, *args, **kwargs):
        async with self._lock:
            return await asyncio.to_thread(fn, *args, **kwargs)

    def authorized(self, update: Update) -> bool:
        chat = update.effective_chat
        return self.chat_id is not None and chat is not None and chat.id == self.chat_id

    @staticmethod
    def guarded(handler):
        @wraps(handler)
        async def wrapper(self: Bot, update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not self.authorized(update):
                if update.effective_message:
                    await update.effective_message.reply_text(
                        "This is a private bot. If it's yours, set TELEGRAM_CHAT_ID="
                        f"{update.effective_chat.id} in .env and restart."
                    )
                return
            try:
                await handler(self, update, context)
            except ServiceError as exc:
                await update.effective_message.reply_text(f"⚠️ {exc}")
        return wrapper

    async def send(self, update: Update, html: str, markup=None) -> None:
        await update.effective_message.reply_text(
            html, parse_mode=ParseMode.HTML, reply_markup=markup or KEYBOARD,
        )

    # ── commands ───────────────────────────────────────────────────────
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.authorized(update):
            await update.effective_message.reply_text(
                f"👋 Your chat id is {update.effective_chat.id}.\n"
                "Put it in .env as TELEGRAM_CHAT_ID and restart the bot. Only that chat can use it."
            )
            return
        holdings = await self.run(self.service.ledger.holdings)
        html = fmt.HELP
        if not holdings:
            html += ("\n\n<b>First step:</b> send me your broker's positions CSV "
                     "(e.g. Fidelity: Accounts → Positions → Download), or a holdings.yaml file. "
                     "Starting from zero? Just tap 📋 Plan.")
        await self.send(update, html)

    @guarded
    async def cmd_help(self, update, context):
        await self.send(update, fmt.HELP)

    @guarded
    async def cmd_plan(self, update, context, amount: float | None = None):
        if amount is None and context.args:
            amount = intents.parse_amount(context.args[0].lstrip("$").rstrip("kK"),
                                          "k" if context.args[0].lower().endswith("k") else None)
        plan, snap = await self.run(self.service.plan, amount)
        done = await self.run(self.service.month_done)
        await self.send(update, fmt.fmt_plan(plan, snap, done), self._plan_buttons(plan.id))

    @guarded
    async def cmd_extra(self, update, context, amount: float | None = None):
        if amount is None:
            if not context.args:
                await self.send(update, "How much? e.g. <code>/extra 5000</code>")
                return
            raw = context.args[0].lstrip("$")
            amount = intents.parse_amount(raw.rstrip("kK"), "k" if raw.lower().endswith("k") else None)
        plan, snap = await self.run(self.service.extra, amount)
        await self.send(update, fmt.fmt_plan(plan, snap), self._plan_buttons(plan.id))

    def _plan_buttons(self, plan_id: int | None) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ I bought these", callback_data=f"exec:{plan_id}"),
            InlineKeyboardButton("⏭ Skip", callback_data=f"skip:{plan_id}"),
        ]])

    @guarded
    async def cmd_portfolio(self, update, context):
        snap = await self.run(self.service.snapshot)
        dd = await self.run(self.service.drawdown, snap)
        await self.send(update, fmt.fmt_portfolio(snap, self.service.strategy, dd))

    @guarded
    async def cmd_drift(self, update, context):
        snap = await self.run(self.service.snapshot)
        await self.send(update, fmt.fmt_drift(snap))

    @guarded
    async def cmd_guardrails(self, update, context):
        checks = await self.run(self.service.guardrails)
        await self.send(update, fmt.fmt_guardrails(checks))

    @guarded
    async def cmd_goal(self, update, context):
        snap = await self.run(self.service.snapshot)
        monthly = self.service.strategy.monthly_amount
        if context.args:
            monthly = intents.parse_amount(context.args[0].lstrip("$"))
        proj = await self.run(self.service.goal, snap, monthly)
        await self.send(update, fmt.fmt_goal(snap, self.service.strategy, proj, monthly))

    @guarded
    async def cmd_stress(self, update, context):
        snap = await self.run(self.service.snapshot)
        res = await self.run(self.service.stress, snap)
        await self.send(update, fmt.fmt_stress(snap, res, self.service.strategy.monthly_amount))

    @guarded
    async def cmd_bought(self, update, context):
        intent = intents.parse("bought " + " ".join(context.args or []))
        if not intent or intent.name != "buy":
            await self.send(update, "Usage: <code>/bought VOO 650</code> · <code>/bought NVDA 2 sh @ 180</code>")
            return
        await self._record_buy(update, intent.args)

    async def _record_buy(self, update: Update, a: dict) -> None:
        rec = await self.run(
            self.service.record_buys, [(a["ticker"], a["qty"], a.get("price"))],
            "manual", a.get("shares", False),
        )
        await self.send(update, fmt.fmt_recorded(rec))

    @guarded
    async def cmd_sold(self, update, context):
        args = context.args or []
        if len(args) < 2:
            await self.send(update, "Usage: <code>/sold TICKER SHARES [@ price]</code>")
            return
        price = float(args[-1].lstrip("@$")) if len(args) >= 3 else None
        token = uuid.uuid4().hex[:8]
        context.chat_data.setdefault("pending", {})[token] = ("sell", args[0], float(args[1]), price)
        await self.send(
            update,
            "🛑 <b>The plan is buy-only.</b> In a drop, selling turns a paper loss into a real one.\n\n"
            "If you already sold and only want the ledger to match your broker, confirm below.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("I already sold, record it", callback_data=f"ok:{token}"),
                InlineKeyboardButton("Cancel", callback_data=f"no:{token}"),
            ]]),
        )

    @guarded
    async def cmd_settings(self, update, context):
        overrides = await self.run(self.service.ledger.settings)
        await self.send(update, fmt.fmt_settings(self.service.strategy, overrides))

    @guarded
    async def cmd_set(self, update, context):
        args = context.args or []
        if args and args[0].lower() == "reset":
            await self.run(self.service.reset_settings)
            self._reschedule(getattr(context, "application", None))
            await self.send(update, "↩️ Settings reset to strategy.yaml.\n\n"
                            + fmt.fmt_settings(self.service.strategy, {}))
            return
        if len(args) != 2:
            await self.send(update, "Usage: <code>/set monthly 3000</code> · <code>/set goal 250k</code> · "
                            "<code>/set day 15</code> · <code>/set return 6</code> · <code>/set reset</code>")
            return
        key, _ = await self.run(self.service.set_setting, args[0], args[1])
        if key == "reminder_day":
            self._reschedule(getattr(context, "application", None))
        overrides = await self.run(self.service.ledger.settings)
        await self.send(update, "✅ Saved.\n\n" + fmt.fmt_settings(self.service.strategy, overrides))

    @guarded
    async def cmd_history(self, update, context):
        txs = await self.run(self.service.history, 15)
        await self.send(update, fmt.fmt_history(txs))

    @guarded
    async def cmd_undo(self, update, context):
        txs = await self.run(self.service.undo)
        await self.send(update, fmt.fmt_undo(txs))

    @guarded
    async def cmd_import(self, update, context):
        await self.send(update, (
            "📥 <b>Import holdings</b>\n"
            "Download your positions as CSV from your broker and send the file here.\n"
            "• Fidelity: Accounts &amp; Trade → Portfolio → Positions → ⤓ Download\n"
            "• Schwab: Accounts → Positions → Export\n"
            "• Vanguard: Holdings → Download\n"
            "• Any broker: a CSV with columns <code>ticker,shares,avg_cost</code>\n"
            "Or send a <code>holdings.yaml</code> (see examples/holdings.example.yaml).\n\n"
            "An import <b>replaces</b> the ledger with the broker's numbers. /undo restores the previous state."
        ))

    @guarded
    async def on_document(self, update, context):
        doc = update.effective_message.document
        if doc.file_size and doc.file_size > 2_000_000:
            await self.send(update, "That file is too big for a positions export.")
            return
        data = bytes(await (await doc.get_file()).download_as_bytearray())
        rows = await self.run(self.service.import_holdings, doc.file_name or "upload.csv", data)
        snap = await self.run(self.service.snapshot)
        listing = ", ".join(f"{t} {s:g}" for t, s, _ in rows[:25])
        await self.send(update, (
            f"📥 Imported <b>{len(rows)}</b> positions: {fmt.esc(listing)}\n"
            f"Portfolio: <b>{fmt.money(snap.total_value)}</b>. Wrong file? /undo\n\nNext: tap 📋 Plan."
        ))

    # ── free text ──────────────────────────────────────────────────────
    @guarded
    async def on_text(self, update, context):
        text = update.effective_message.text or ""
        intent = intents.parse(text)
        if intent:
            await self._dispatch(intent, update, context)
            return
        if self.advisor:
            await update.effective_chat.send_action("typing")
            try:
                reply = await self.advisor.answer(text, context.chat_data.get("history"))
            except Exception as exc:  # noqa: BLE001
                log.warning("LLM failed: %s", exc)
                await self.send(update, "The AI helper is unavailable right now. Try /help for commands.")
                return
            hist = context.chat_data.setdefault("history", [])
            hist += [{"role": "user", "content": text}, {"role": "assistant", "content": reply.text}]
            del hist[:-8]
            markup = None
            if reply.proposed_buys:
                token = uuid.uuid4().hex[:8]
                context.chat_data.setdefault("pending", {})[token] = ("buys", reply.proposed_buys)
                summary = ", ".join(f"{t} ${d:,.0f}" for t, d, _ in reply.proposed_buys)
                reply.text += f"\n\nRecord: {summary}?"
                markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Record", callback_data=f"ok:{token}"),
                    InlineKeyboardButton("Cancel", callback_data=f"no:{token}"),
                ]])
            await self.send(update, fmt.md_to_html(reply.text), markup)
            return
        await self.send(update, "I didn't catch that. Try “bought 400 of VOO”, “I got a 5k bonus”, or /help.")

    async def _dispatch(self, intent: intents.Intent, update, context) -> None:
        context.args = []
        name = intent.name
        if name == "buy":
            await self._record_buy(update, intent.args)
        elif name == "plan":
            await self.cmd_plan.__wrapped__(self, update, context, intent.args.get("amount"))
        elif name == "extra":
            await self.cmd_extra.__wrapped__(self, update, context, intent.args["amount"])
        elif name == "sell":
            snap = await self.run(self.service.snapshot)
            res = await self.run(self.service.stress, snap)
            await self.send(update, "🛑 <b>No selling. That's the one rule the whole plan depends on.</b>\n\n"
                            + fmt.fmt_stress(snap, res, self.service.strategy.monthly_amount)
                            + "\n\nIf you already sold at the broker: /sold TICKER SHARES")
        else:
            handler = {
                "portfolio": self.cmd_portfolio, "drift": self.cmd_drift, "guardrails": self.cmd_guardrails,
                "goal": self.cmd_goal, "stress": self.cmd_stress, "history": self.cmd_history,
                "undo": self.cmd_undo, "help": self.cmd_help, "settings": self.cmd_settings,
            }[name]
            await handler.__wrapped__(self, update, context)

    # ── buttons ────────────────────────────────────────────────────────
    async def on_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        if not self.authorized(update):
            await q.answer("Not authorized", show_alert=True)
            return
        await q.answer()
        action, _, arg = (q.data or "").partition(":")
        try:
            if action == "exec":
                rec = await self.run(self.service.execute_plan, int(arg))
                await q.edit_message_reply_markup(None)
                await self.send(update, fmt.fmt_recorded(rec, "Bought, ledger updated") + "\n\nNice. See you next month 👋")
            elif action == "skip":
                await self.run(self.service.skip_plan, int(arg))
                await q.edit_message_reply_markup(None)
                await self.send(update, "Skipped. Send /plan whenever you're ready.")
            elif action in ("ok", "no"):
                pending = context.chat_data.get("pending", {}).pop(arg, None)
                await q.edit_message_reply_markup(None)
                if not pending or action == "no":
                    await self.send(update, "Cancelled." if pending else "That request expired.")
                    return
                if pending[0] == "buys":
                    rec = await self.run(self.service.record_buys, pending[1], "via assistant")
                else:
                    _, t, shares, price = pending
                    rec = await self.run(self.service.record_sell, t, shares, price)
                await self.send(update, fmt.fmt_recorded(rec))
        except ServiceError as exc:
            await self.send(update, f"⚠️ {fmt.esc(exc)}")

    # ── scheduled jobs ─────────────────────────────────────────────────
    async def job_monthly(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self.run(self.service.month_done):
            return
        plan, snap = await self.run(self.service.plan, None)
        await context.bot.send_message(
            self.chat_id, "💰 <b>Payday!</b>\n\n" + fmt.fmt_plan(plan, snap),
            parse_mode=ParseMode.HTML, reply_markup=self._plan_buttons(plan.id),
        )

    async def job_daily(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        snap = await self.run(self.service.snapshot)
        hit = await self.run(self.service.new_drawdown_alert, snap)
        if hit:
            level, dd = hit
            await context.bot.send_message(
                self.chat_id,
                fmt.fmt_drawdown_alert(level, dd, snap, self.service.strategy.monthly_amount,
                                       self.service.strategy.guardrails.cushions),
                parse_mode=ParseMode.HTML,
            )

    async def job_weekly(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        snap = await self.run(self.service.snapshot)
        dd = await self.run(self.service.drawdown, snap)
        text = "📬 <b>Weekly digest</b>\n\n" + fmt.fmt_portfolio(snap, self.service.strategy, dd)
        if not await self.run(self.service.month_done) and datetime.now().day >= self.service.strategy.reminder_day:
            text += "\n\n⏰ This month's buys aren't recorded yet. Tap 📋 Plan."
        await context.bot.send_message(self.chat_id, text, parse_mode=ParseMode.HTML)

    # ── wiring ─────────────────────────────────────────────────────────
    async def _post_init(self, app: Application) -> None:
        await app.bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS])

    async def _on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.exception("Unhandled error", exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("Something went wrong on my side. It's logged.")

    def build(self) -> Application:
        app = Application.builder().token(self.token).post_init(self._post_init).build()
        h = [
            ("help", self.cmd_help), ("plan", self.cmd_plan), ("extra", self.cmd_extra),
            ("portfolio", self.cmd_portfolio), ("drift", self.cmd_drift), ("guardrails", self.cmd_guardrails),
            ("goal", self.cmd_goal), ("stress", self.cmd_stress), ("bought", self.cmd_bought),
            ("sold", self.cmd_sold), ("history", self.cmd_history), ("undo", self.cmd_undo),
            ("import", self.cmd_import), ("settings", self.cmd_settings), ("set", self.cmd_set),
        ]
        app.add_handler(CommandHandler("start", self.cmd_start))
        for name, fn in h:
            app.add_handler(CommandHandler(name, fn))
        app.add_handler(CallbackQueryHandler(self.on_button))
        app.add_handler(MessageHandler(filters.Document.ALL, self.on_document))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        app.add_error_handler(self._on_error)

        self._schedule(app)
        return app

    def _schedule(self, app: Application) -> None:
        if self.chat_id is None or app.job_queue is None:
            return
        s = self.service.strategy
        tz = s.timezone
        jq = app.job_queue
        jq.run_monthly(self.job_monthly, when=_at(s.reminder_time, tz), day=s.reminder_day, name="monthly")
        jq.run_daily(self.job_daily, time=_at(s.daily_check_time, tz), days=(1, 2, 3, 4, 5), name="daily")
        if s.weekly_digest:
            jq.run_daily(self.job_weekly, time=_at(time(10, 0), tz), days=(0,), name="weekly")

    def _reschedule(self, app: Application | None) -> None:
        """Re-create jobs after /set day N so the new reminder day applies immediately."""
        if app is None or app.job_queue is None:
            return
        for job in app.job_queue.jobs():
            job.schedule_removal()
        self._schedule(app)


def _at(t: time, tz) -> time:
    return time(t.hour, t.minute, tzinfo=tz)


def run_bot(service: Service) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set. Create a bot with @BotFather and add it to .env.")
    raw_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    chat_id = int(raw_chat) if raw_chat.lstrip("-").isdigit() else None
    llm = LLMClient.from_env()
    log.info("Starting bot (chat_id=%s, llm=%s)", chat_id, llm.provider if llm else "off")
    if chat_id is None:
        log.warning("TELEGRAM_CHAT_ID not set: send /start to the bot to get it. Scheduled jobs are disabled.")
    Bot(service, token, chat_id, llm).build().run_polling(allowed_updates=Update.ALL_TYPES)

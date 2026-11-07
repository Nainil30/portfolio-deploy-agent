"""Command-line interface. Everything the bot does also works from a terminal.

    pda bot                     run the Telegram bot (long polling)
    pda plan [--amount 3000]    this month's buy list
    pda extra 5000              deploy one-off cash
    pda portfolio | drift | guardrails | goal | stress | history | undo
    pda import FILE             Fidelity CSV or holdings.yaml
    pda bought VOO 650 [--price 612.4] [--shares]
    pda send-plan               push the plan to Telegram once (for cron)
    pda ask "how far am I from the goal?"   (needs an LLM key)

Add --offline to use config/demo_prices.yaml instead of live prices.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from pda import formatting as fmt
from pda.config import DEFAULT_DB, DEFAULT_STRATEGY, ConfigError, load_strategy
from pda.ledger import Ledger
from pda.prices import StaticPrices, YahooPrices
from pda.service import Service, ServiceError


def build_service(args: argparse.Namespace) -> Service:
    strategy = load_strategy(args.strategy)
    prices = StaticPrices.from_yaml() if args.offline else YahooPrices(strategy.yahoo_aliases)
    return Service(strategy, Ledger(args.db), prices)


def out(html: str) -> None:
    text = fmt.to_plain(html)
    try:
        print(text)
    except UnicodeEncodeError:  # legacy Windows consoles
        print(text.encode(sys.stdout.encoding or "ascii", "replace").decode(sys.stdout.encoding or "ascii"))


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(prog="pda", description="Buy-only portfolio co-pilot")
    p.add_argument("--offline", action="store_true", help="use demo prices (no network)")
    p.add_argument("--db", default=os.getenv("PDA_DB", str(DEFAULT_DB)))
    p.add_argument("--strategy", default=str(DEFAULT_STRATEGY))
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("bot", help="run the Telegram bot")
    sp = sub.add_parser("plan", help="monthly buy list")
    sp.add_argument("--amount", type=float)
    se = sub.add_parser("extra", help="deploy one-off cash")
    se.add_argument("amount", type=float)
    for name in ("portfolio", "drift", "guardrails", "goal", "stress", "history", "undo", "send-plan", "validate"):
        sub.add_parser(name)
    si = sub.add_parser("import", help="import holdings (Fidelity CSV or YAML)")
    si.add_argument("file", type=Path)
    sb = sub.add_parser("bought", help="record a buy")
    sb.add_argument("ticker")
    sb.add_argument("qty", type=float, help="dollars (or shares with --shares)")
    sb.add_argument("--price", type=float)
    sb.add_argument("--shares", action="store_true")
    sa = sub.add_parser("ask", help="ask the AI assistant (needs an LLM key)")
    sa.add_argument("question", nargs="+")

    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    for noisy in ("httpx", "yfinance", "peewee", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    try:
        if args.cmd == "validate":
            s = load_strategy(args.strategy)
            print(f"OK: {len(s.targets)} targets = 100%, monthly ${s.monthly_amount:,.0f}, guardrails consistent.")
            return 0
        svc = build_service(args)
        return dispatch(args, svc)
    except (ConfigError, ServiceError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def dispatch(args: argparse.Namespace, svc: Service) -> int:
    s = svc.strategy
    if args.cmd == "bot":
        from pda.bot import run_bot
        run_bot(svc)
    elif args.cmd == "plan":
        plan, snap = svc.plan(args.amount)
        out(fmt.fmt_plan(plan, snap, svc.month_done()))
        print(f"\n(plan #{plan.id}: record it from Telegram, or `pda bought` each line)")
    elif args.cmd == "extra":
        plan, snap = svc.extra(args.amount)
        out(fmt.fmt_plan(plan, snap))
    elif args.cmd == "portfolio":
        snap = svc.snapshot()
        out(fmt.fmt_portfolio(snap, s, svc.drawdown(snap)))
    elif args.cmd == "drift":
        out(fmt.fmt_drift(svc.snapshot()))
    elif args.cmd == "guardrails":
        out(fmt.fmt_guardrails(svc.guardrails()))
    elif args.cmd == "goal":
        snap = svc.snapshot()
        out(fmt.fmt_goal(snap, s, svc.goal(snap), s.monthly_amount))
    elif args.cmd == "stress":
        snap = svc.snapshot()
        out(fmt.fmt_stress(snap, svc.stress(snap), s.monthly_amount))
    elif args.cmd == "history":
        out(fmt.fmt_history(svc.history(30)))
    elif args.cmd == "undo":
        out(fmt.fmt_undo(svc.undo()))
    elif args.cmd == "import":
        rows = svc.import_holdings(args.file.name, args.file.read_bytes())
        print(f"Imported {len(rows)} positions. Run `pda portfolio` to check.")
    elif args.cmd == "bought":
        rec = svc.record_buys([(args.ticker, args.qty, args.price)], "cli", args.shares)
        out(fmt.fmt_recorded(rec))
    elif args.cmd == "send-plan":
        return asyncio.run(_send_plan(svc))
    elif args.cmd == "ask":
        return asyncio.run(_ask(svc, " ".join(args.question)))
    return 0


async def _send_plan(svc: Service) -> int:
    """One-shot push for cron / Task Scheduler if you don't keep the bot running."""
    from telegram import Bot
    from telegram.constants import ParseMode

    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env", file=sys.stderr)
        return 1
    if svc.month_done():
        print("This month's plan is already recorded. Nothing sent.")
        return 0
    plan, snap = svc.plan()
    async with Bot(token) as bot:
        await bot.send_message(int(chat), fmt.fmt_plan(plan, snap), parse_mode=ParseMode.HTML)
    print("Sent.")
    return 0


async def _ask(svc: Service, question: str) -> int:
    from pda.llm import Advisor, LLMClient

    client = LLMClient.from_env()
    if not client:
        print("No LLM configured. Set GROQ_API_KEY (free at console.groq.com) or LLM_PROVIDER=ollama.")
        return 1
    reply = await Advisor(client, svc).answer(question)
    print(reply.text)
    if reply.proposed_buys:
        print("\nProposed (not recorded; use `pda bought` to record):", reply.proposed_buys)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

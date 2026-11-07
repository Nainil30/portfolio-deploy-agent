"""Command-line interface. Everything the bot does also works from a terminal.

    pda demo                    see it work instantly (example plan, demo prices)
    pda init                    create YOUR plan in a minute (setup wizard)
    pda doctor                  check the setup, with fixes
    pda bot                     run the Telegram bot (long polling)
    pda plan [--amount 3000]    this month's buy list
    pda extra 5000              deploy one-off cash
    pda portfolio | drift | guardrails | goal | stress | history | undo
    pda import FILE             Fidelity CSV or holdings.yaml
    pda bought VOO 650 [--price 612.4] [--shares]
    pda set monthly 3000        change monthly amount / goal / day / return
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
    sd = sub.add_parser("demo", help="see it work with an example plan (no setup)")
    sd.add_argument("--extra", type=float, default=5000, help="also show an extra-cash plan")
    sn = sub.add_parser("init", help="create your plan (setup wizard)")
    sn.add_argument("--preset", choices=["three_fund", "dividend_income", "core_plus_stock_slot", "india_index", "custom"])
    sn.add_argument("--monthly", help="e.g. 1500 or 1.5k")
    sn.add_argument("--goal", help="e.g. 400000 or 400k")
    sn.add_argument("--currency")
    sn.add_argument("--day", type=int)
    sn.add_argument("--force", action="store_true", help="overwrite an existing plan")
    sn.add_argument("--yes", action="store_true", help="non-interactive: accept defaults for anything not given")
    sdoc = sub.add_parser("doctor", help="check setup")
    sdoc.add_argument("--offline", dest="doctor_offline", action="store_true", help="skip network checks")
    sset = sub.add_parser("set", help="change a setting: monthly | goal | day | return")
    sset.add_argument("key")
    sset.add_argument("value")
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
        if args.cmd == "init":
            from pda.onboarding import run_wizard
            d = {}
            if args.yes:
                d = {"name": None, "currency": None, "monthly": None, "goal": None, "return": None,
                     "day": None, "timezone": None, "cap": None, "overwrite": "y" if args.force else "n"}
            for k in ("monthly", "goal", "currency", "day"):
                if getattr(args, k) is not None:
                    d[k] = getattr(args, k)
            run_wizard(path=Path(args.strategy), preset=args.preset, force=args.force, defaults=d)
            return 0
        if args.cmd == "doctor":
            from pda.onboarding import run_doctor
            return run_doctor(Path(args.strategy), Path(args.db), check_network=not args.doctor_offline)
        if args.cmd == "demo":
            from pda.onboarding import demo_service
            return demo(demo_service(), args.extra)
        if args.cmd == "validate":
            s = load_strategy(args.strategy)
            print(f"OK: '{s.name}' ({s.mode} mode), {len(s.targets)} targets = 100%, "
                  f"{s.currency}{s.monthly_amount:,.0f}/month, goal {s.currency}{s.goal_value:,.0f}.")
            return 0
        svc = build_service(args)
        return dispatch(args, svc)
    except (ConfigError, ServiceError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def demo(svc: Service, extra: float) -> int:
    """A guided tour on the example plan: what a recruiter or new user sees first."""
    s = svc.strategy
    bar = "═" * 64

    def section(title: str = "") -> None:
        print(f"\n{bar}" + (f"\n{title}\n" if title else "\n"))

    print(f"{bar}\n  DEMO: example plan '{s.name}' with demo prices (nothing is saved)\n{bar}\n")
    print("1) What the bot sends you on payday:\n")
    plan, snap = svc.plan()
    out(fmt.fmt_plan(plan, snap))
    section("2) /guardrails: how the portfolio stands against your rules:")
    out(fmt.fmt_guardrails(svc.guardrails(snap)))
    section("3) /goal: when you reach your money goal:")
    out(fmt.fmt_goal(snap, s, svc.goal(snap), s.monthly_amount))
    if extra:
        section(f"4) /extra {extra:g}: a bonus fills the biggest gaps first:")
        p2, _ = svc.extra(extra)
        out(fmt.fmt_plan(p2, snap))
    section("5) /stress: what a bad year looks like (and why you don't sell):")
    out(fmt.fmt_stress(snap, svc.stress(snap), s.monthly_amount))
    print(f"\n{bar}\nMake it yours:  pda init   ->   pda plan   ->   pda bot\n")
    return 0


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
    elif args.cmd == "set":
        key, value = svc.set_setting(args.key, args.value)
        print(f"Saved {key} = {value:g}. (Stored in the ledger; strategy.yaml is unchanged.)")
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

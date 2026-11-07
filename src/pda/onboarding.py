"""Onboarding for anyone: `pda init` (setup wizard), `pda demo`, `pda doctor`.

The wizard turns six plain questions into a validated config/strategy.yaml,
so nobody has to learn YAML to start. It takes an `ask` function so tests
can script the answers.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

import yaml

from pda.config import (
    DEFAULT_STRATEGY,
    DEMO_HOLDINGS,
    DEMO_STRATEGY,
    EXAMPLES_DIR,
    VALID_BUCKETS,
    ConfigError,
    load_strategy,
    normalize_ticker,
    parse_strategy,
)

Ask = Callable[[str], str]

PRESETS = {
    "three_fund": "Three-fund: VTI 60 / VXUS 30 / BND 10 (simplest)",
    "dividend_income": "Dividend income: SCHD, VIG, VYM + a few dividend stocks",
    "core_plus_stock_slot": "Core + stock slot: S&P core, sector ETFs, gold, stocks, all guardrails",
    "india_index": "India index (₹): Nifty 50, Next 50, Nasdaq 100, gold (NSE)",
}

HEADER = """\
# ─────────────────────────────────────────────────────────────────────────────
#  Your investing plan, created by `pda init`.
#  Edit freely, then run `pda validate`. Every field: docs/CONFIGURATION.md
#  This file is gitignored (personal). Holdings live in data/pda.db.
# ─────────────────────────────────────────────────────────────────────────────
"""


def _num(text: str) -> float:
    t = text.strip().replace(",", "").lstrip("$₹€£¥")
    mult = 1000 if t.lower().endswith("k") else 1_000_000 if t.lower().endswith("m") else 1
    return float(t.rstrip("kKmM")) * mult


def _prompt(ask: Ask, question: str, default: str | None = None, parse=str, check=None, out=print):
    suffix = f" [{default}]" if default is not None else ""
    while True:
        raw = ask(f"{question}{suffix}: ").strip()
        if not raw and default is not None:
            raw = default
        try:
            value = parse(raw)
            if check and not check(value):
                raise ValueError
            return value
        except (ValueError, TypeError):
            out("  ↳ That doesn't look right, try again.")


def scale_split(monthly: dict, new_amount: float) -> None:
    """Rescale a preset's fixed split (and stock slot) to a new monthly amount."""
    split = monthly.get("split") or {}
    slot = monthly.get("stock_slot") or {}
    base = sum(split.values()) + float(slot.get("amount", 0))
    if not base or abs(base - new_amount) < 0.01:
        monthly["amount"] = new_amount
        return
    k = new_amount / base
    for t in split:
        split[t] = round(split[t] * k)
    if slot:
        slot["amount"] = round(float(slot["amount"]) * k)
    residual = round(new_amount) - (sum(split.values()) + float(slot.get("amount", 0)))
    biggest = max(split, key=split.get)
    split[biggest] += residual
    monthly["amount"] = round(new_amount)


def parse_target_line(line: str) -> tuple[str, float, str]:
    """'VTI 60'  /  'NVDA 5 stock'  /  'GLD 10% gold'  ->  (ticker, pct, bucket)"""
    parts = re.split(r"[\s,]+", line.strip())
    if len(parts) < 2:
        raise ValueError("need TICKER PERCENT")
    ticker = normalize_ticker(parts[0])
    pct = float(parts[1].rstrip("%"))
    bucket = parts[2].lower() if len(parts) > 2 else "etf"
    if bucket not in VALID_BUCKETS:
        raise ValueError(f"type must be one of {', '.join(sorted(VALID_BUCKETS))}")
    if pct <= 0:
        raise ValueError("percent must be positive")
    return ticker, pct, bucket


def build_custom_targets(ask: Ask, out=print) -> dict:
    out("\nEnter your targets, one per line:  TICKER PERCENT [type]")
    out(f"  types: {', '.join(sorted(VALID_BUCKETS))} (default etf). 'stock' gets the single-stock cap.")
    out("  Examples:  VOO 60    VXUS 20 etf    BND 10 bond    AAPL 5 stock    BTC-USD 5 crypto")
    out("  Press Enter on an empty line when done.\n")
    targets: dict[str, dict] = {}
    while True:
        total = sum(t["pct"] for t in targets.values())
        line = ask(f"  ({total:g}% so far) > ").strip()
        if not line:
            if not targets:
                out("  ↳ Add at least one ticker.")
                continue
            break
        try:
            t, pct, bucket = parse_target_line(line)
        except ValueError as exc:
            out(f"  ↳ {exc}")
            continue
        targets[t] = {"pct": pct, "bucket": bucket}

    total = sum(t["pct"] for t in targets.values())
    if abs(total - 100) > 0.01:
        out(f"\nYour targets add up to {total:g}%. Scaling them proportionally to 100%.")
        scaled = {t: round(v["pct"] * 100 / total, 2) for t, v in targets.items()}
        biggest = max(scaled, key=scaled.get)
        scaled[biggest] = round(scaled[biggest] + 100 - sum(scaled.values()), 2)
        for t in targets:
            targets[t]["pct"] = scaled[t]
    # The biggest fund is the "core": it receives money freed by guardrails.
    biggest = max(targets, key=lambda t: targets[t]["pct"])
    if targets[biggest]["bucket"] == "etf":
        targets[biggest]["bucket"] = "core_etf"
    return targets


def run_wizard(
    ask: Ask = input,
    out=print,
    path: Path = DEFAULT_STRATEGY,
    preset: str | None = None,
    force: bool = False,
    defaults: dict | None = None,
) -> Path:
    """Interactive setup. `defaults` pre-answers questions (used by --non-interactive)."""
    d = defaults or {}

    def q(key, question, default, parse=str, check=None):
        if key in d:
            return parse(str(d[key])) if d[key] is not None else parse(default)
        return _prompt(ask, question, default, parse, check, out)

    out("\n📈 Portfolio Deploy Agent: set up your plan (about a minute)\n")
    if path.exists() and not force:
        if q("overwrite", f"{path} already exists. Overwrite it? (y/n)", "n").lower() not in ("y", "yes"):
            out("Kept your existing plan.")
            return path

    name = q("name", "Name for your plan", "My plan")
    currency = q("currency", "Currency symbol", "$")
    monthly = q("monthly", "How much do you invest each month?", "1000", _num, lambda v: v > 0)
    goal = q("goal", "Your money goal (portfolio value to reach)", "100000", _num, lambda v: v > 0)
    ret = q("return", "Yearly return to assume for projections, in %", "7", float, lambda v: -20 < v < 30)
    day = q("day", "Day of the month for your buy reminder (1–28)", "1", int, lambda v: 1 <= v <= 28)
    tz = q("timezone", "Your timezone", os.getenv("TZ", "America/New_York"))

    if preset is None:
        out("\nStart from:")
        keys = list(PRESETS)
        for i, k in enumerate(keys, 1):
            out(f"  {i}) {PRESETS[k]}")
        out(f"  {len(keys) + 1}) Custom: type your own tickers and %")
        choice = q("preset_choice", "Choose", str(len(keys) + 1), int, lambda v: 1 <= v <= len(keys) + 1)
        preset = keys[choice - 1] if choice <= len(keys) else "custom"

    if preset == "custom":
        targets = d.get("targets") or build_custom_targets(ask, out)
        cap = q("cap", "Max % for any single stock (blank = no cap)", "10",
                lambda s: None if s in ("", "none", "None") else float(s))
        biggest_stock = max((v["pct"] for v in targets.values() if v["bucket"] == "stock"), default=0)
        if cap is not None and biggest_stock > cap:
            out(f"  ↳ One of your stocks is targeted at {biggest_stock:g}%, so the cap is raised to {biggest_stock:g}%.")
            cap = biggest_stock
        raw = {
            "monthly": {"mode": "auto"},
            "targets": targets,
            "guardrails": {"never_sell": True, "max_single_stock_pct": cap},
            "alerts": {"drawdown_levels_pct": [10, 20, 30], "weekly_digest": True},
        }
    else:
        src = EXAMPLES_DIR / f"{preset}.yaml"
        if not src.exists():
            raise ConfigError(f"Unknown preset {preset!r}. Choose from: {', '.join(PRESETS)}")
        raw = yaml.safe_load(src.read_text(encoding="utf-8"))

    raw["profile"] = {"name": name, "currency": currency}
    raw["goal"] = {"target_value": goal, "expected_annual_return": round(ret / 100, 4)}
    m = raw.setdefault("monthly", {})
    m.update({"reminder_day": day, "timezone": tz})
    m.setdefault("reminder_time", "09:30")
    m.setdefault("min_buy", max(1, round(monthly * 0.0125)))
    if m.get("mode", "auto") == "fixed":
        scale_split(m, monthly)
    else:
        m["amount"] = monthly

    parse_strategy(raw)  # validate before writing anything
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {k: raw[k] for k in ("profile", "goal", "monthly", "targets", "guardrails", "alerts", "yahoo_aliases") if k in raw}
    path.write_text(HEADER + "\n" + yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True), encoding="utf-8")

    out(f"\n✅ Saved {path}")
    out("\nNext steps:")
    out("  1. pda plan              → see this month's buy list (live prices)")
    out("  2. pda import FILE       → load holdings (broker CSV or holdings.yaml), or skip if starting fresh")
    out("  3. Put TELEGRAM_BOT_TOKEN in .env, then: pda bot   (README → 'Connect Telegram')")
    out("  4. pda doctor            → checks everything is wired up")
    return path


# ── demo ────────────────────────────────────────────────────────────────
def demo_service():
    """A throwaway in-memory service on the example plan + demo prices. No setup needed."""
    from pda.importers import parse_file
    from pda.ledger import Ledger
    from pda.prices import StaticPrices
    from pda.service import Service

    svc = Service(load_strategy(DEMO_STRATEGY), Ledger(":memory:"), StaticPrices.from_yaml())
    svc.ledger.replace_with_import(parse_file(DEMO_HOLDINGS.name, DEMO_HOLDINGS.read_text(encoding="utf-8")))
    return svc


# ── doctor ──────────────────────────────────────────────────────────────
def run_doctor(strategy_path: Path, db_path: Path, check_network: bool = True, out=print) -> int:
    """Check every piece of the setup and say exactly how to fix what's missing."""
    problems = 0

    def ok(msg):
        out(f"✅ {msg}")

    def warn(msg, fix):
        out(f"⚠️  {msg}\n     → {fix}")

    def bad(msg, fix):
        nonlocal problems
        problems += 1
        out(f"❌ {msg}\n     → {fix}")

    out("🩺 pda doctor\n")
    try:
        s = load_strategy(strategy_path)
        ok(f"Strategy '{s.name}': {s.mode} mode, {len(s.targets)} targets, "
           f"{s.currency}{s.monthly_amount:,.0f}/month, goal {s.currency}{s.goal_value:,.0f}")
    except ConfigError as exc:
        bad(f"Strategy: {exc}", "run `pda init`")
        s = None

    from pda.ledger import Ledger
    if Path(db_path).exists():
        n = len(Ledger(db_path).holdings())
        if n:
            ok(f"Ledger: {n} positions in {db_path}")
        else:
            warn("Ledger is empty", "`pda import <broker.csv|holdings.yaml>`, or just start buying with the plan")
    else:
        warn(f"No ledger yet at {db_path}", "it's created on first use; import holdings with `pda import FILE`")

    if s and check_network:
        from pda.prices import YahooPrices
        prices = YahooPrices(s.yahoo_aliases).get_prices(list(s.targets))
        missing = [t for t, p in prices.items() if p is None]
        if missing:
            bad(f"No price for: {', '.join(missing)}",
                "check the symbol on finance.yahoo.com (e.g. RELIANCE.NS, VOD.L) or add yahoo_aliases")
        else:
            ok(f"Live prices for all {len(prices)} tickers")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not Path(".env").exists() and not token:
        warn("No .env file", "copy .env.example to .env (only needed for Telegram / AI)")
    if not token:
        warn("TELEGRAM_BOT_TOKEN not set", "Telegram → @BotFather → /newbot → paste token in .env (CLI works without it)")
    elif not re.fullmatch(r"\d+:[\w-]{30,}", token):
        bad("TELEGRAM_BOT_TOKEN looks malformed", "copy it again from @BotFather: it looks like 123456789:AA...")
    else:
        if check_network:
            try:
                import httpx
                r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
                if r.status_code == 200 and r.json().get("ok"):
                    ok(f"Telegram bot @{r.json()['result']['username']} reachable")
                else:
                    bad("Telegram rejected the token", "regenerate it with @BotFather → /token")
            except Exception as exc:  # noqa: BLE001
                warn(f"Couldn't reach Telegram ({exc.__class__.__name__})", "check your internet connection")
        if not re.fullmatch(r"-?\d+", chat):
            warn("TELEGRAM_CHAT_ID not set", "run `pda bot`, send /start to your bot, paste the id it replies with")
        else:
            ok("Telegram chat id set (only that chat can use the bot)")

    from pda.llm import LLMClient
    llm = LLMClient.from_env()
    if llm:
        ok(f"AI assistant: {llm.provider} / {llm.model}")
    else:
        warn("AI assistant off (optional)", "free key at console.groq.com → GROQ_API_KEY in .env; the bot works without it")

    out("\n" + ("All good. Run `pda bot`." if problems == 0 else f"{problems} problem(s) to fix above."))
    return 1 if problems else 0

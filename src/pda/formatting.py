"""Render service results as Telegram HTML (and plain text for the CLI)."""

from __future__ import annotations

import html
import re
from datetime import date

from pda.config import Strategy
from pda.insights import Drawdown, Projection, StressResult
from pda.ledger import Tx
from pda.models import Plan, RuleCheck, Snapshot
from pda.money import money
from pda.service import Recorded

DISCLAIMER = "<i>Personal planning tool, not financial advice.</i>"
BUCKET_NAMES = {
    "core_etf": "Core ETFs", "etf": "Other ETFs", "stock": "Stocks", "bond": "Bonds", "gold": "Gold",
    "reit": "REITs", "crypto": "Crypto", "cash": "Cash", "untargeted": "Untargeted",
}


def esc(x: object) -> str:
    return html.escape(str(x), quote=False)


def md_to_html(text: str) -> str:
    """LLM replies use light Markdown; Telegram HTML needs tags. Escape first, then
    convert **bold**, *italic* and `code`. Anything else stays as plain text."""
    out = esc(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out, flags=re.S)
    out = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", out)
    out = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", out)
    return out


def to_plain(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def bar(actual: float, target: float, width: int = 10) -> str:
    if target <= 0:
        return "·" * width
    filled = max(0, min(width, round(actual / target * width)))
    return "█" * filled + "░" * (width - filled)


# ── plans ──────────────────────────────────────────────────────────────
def fmt_plan(plan: Plan, snap: Snapshot, already_done: bool = False) -> str:
    title = "🗓 <b>Monthly buy list</b>" if plan.kind == "monthly" else "💵 <b>Extra-cash buy list</b>"
    out = [f"{title}: {money(plan.amount)}", f"Portfolio: {money(snap.total_value)}", ""]
    if already_done and plan.kind == "monthly":
        out.append("✅ <i>You already recorded this month's buys. This is a preview.</i>\n")
    rows = []
    for ln in plan.lines:
        shares = f"≈{ln.est_shares:.3f} sh" if ln.est_shares else "no price"
        rows.append(f"{ln.ticker:<6}{money(ln.amount):>7}  {shares}")
    out.append("<pre>" + esc("\n".join(rows)) + "</pre>")
    out.append("<b>Why</b>")
    for ln in plan.lines:
        out.append(f"• <b>{esc(ln.ticker)}</b>: {esc(ln.reason)}")
    if plan.notes:
        out.append("\n🛡 <b>Guardrails applied</b>")
        for n in plan.notes:
            out.append(f"• {esc(n.message)}")
    if snap.missing_prices:
        out.append(f"\n⚠️ No live price for: {esc(', '.join(snap.missing_prices))}")
    out += ["", "Place these as amount-based orders at your broker, then tap <b>✅ I bought these</b>.", DISCLAIMER]
    return "\n".join(out)


# ── portfolio ──────────────────────────────────────────────────────────
def fmt_portfolio(snap: Snapshot, strategy: Strategy, dd: Drawdown | None = None) -> str:
    out = [
        "💼 <b>Portfolio</b>",
        f"Value: <b>{money(snap.total_value)}</b>  ({money(snap.gain)} / {snap.gain_pct:+.1f}%)",
        f"Goal: {money(strategy.goal_value)}  →  {snap.total_value / strategy.goal_value * 100:.1f}% there",
    ]
    if dd and dd.dollars > 0:
        out.append(f"From peak: -{money(dd.dollars)} ({dd.pct(snap.total_cost):.1f}%)")
    out.append("")
    targets_by_bucket: dict[str, float] = {}
    for spec in strategy.targets.values():
        targets_by_bucket[spec.bucket] = targets_by_bucket.get(spec.bucket, 0) + spec.pct
    actual = snap.bucket_pcts()
    rows = [f"{'Bucket':<11}{'Now':>6}{'Goal':>6}"]
    for b in BUCKET_NAMES:
        if actual.get(b, 0) > 0 or targets_by_bucket.get(b, 0) > 0:
            rows.append(f"{BUCKET_NAMES[b]:<11}{actual.get(b, 0):>5.1f}%{targets_by_bucket.get(b, 0):>5.1f}%")
    if strategy.has_theme:
        rows.append(f"{'Theme-heavy':<11}{snap.ai_pct():>5.1f}%")
    out.append("<pre>" + esc("\n".join(rows)) + "</pre>")
    out.append("Send /drift for every ticker.")
    return "\n".join(out)


def fmt_drift(snap: Snapshot) -> str:
    rows = [f"{'Tkr':<6}{'Value':>8}{'Now':>6}{'Goal':>6}  "]
    ps = sorted(snap.positions.values(), key=lambda p: -p.gap_pct)
    for p in ps:
        flag = "▲" if p.gap_pct > 0.5 else ("▼" if p.gap_pct < -0.5 else "·")
        stale = "*" if p.price_is_stale else ""
        rows.append(f"{p.ticker + stale:<6}{money(p.value):>8}{p.actual_pct:>5.1f}%{p.target_pct:>5.1f}% {flag}")
    out = [
        "🎯 <b>Drift vs target</b> (▲ underweight, buy more · ▼ overweight, just don't add)",
        "<pre>" + esc("\n".join(rows)) + "</pre>",
    ]
    if snap.missing_prices:
        out.append("* valued at cost (no live price)")
    return "\n".join(out)


def fmt_guardrails(checks: list[RuleCheck]) -> str:
    out = ["🛡 <b>Guardrails</b>"]
    for c in checks:
        icon = "✅" if c.status == "ok" else "⚠️"
        out.append(f"{icon} <b>{esc(c.name)}</b>: {esc(c.detail)}")
    return "\n\n".join(out)


def fmt_goal(snap: Snapshot, strategy: Strategy, projections: list[Projection], monthly: float) -> str:
    out = [
        f"🏁 <b>Road to {money(strategy.goal_value)}</b>",
        f"Now: {money(snap.total_value)} · investing {money(monthly)}/mo",
        "",
    ]
    rows = []
    for p in projections:
        eta = p.eta(date.today())
        when = f"{p.months} mo ({eta:%b %Y})" if eta else "50+ years"
        rows.append(f"{p.annual_return * 100:>4.0f}%/yr → {when}")
    out.append("<pre>" + esc("\n".join(rows)) + "</pre>")
    out.append("Returns are assumptions, not forecasts. The part you control is the monthly buy.")
    return "\n".join(out)


def fmt_stress(snap: Snapshot, results: list[StressResult], monthly: float) -> str:
    out = ["🌧 <b>Stress test</b>: what a bad year could look like on paper", ""]
    rows = [f"{r.name[:24]:<24} {money(r.loss):>9} ({r.loss_pct:+.0f}%)" for r in results]
    out.append("<pre>" + esc("\n".join(rows)) + "</pre>")
    worst = min(results, key=lambda r: r.loss)
    out += [
        f"In the worst case your {money(monthly)} buys ~{worst.extra_shares_pct:.0f}% more shares than today.",
        "",
        "<b>The plan in a drop:</b> keep buying, don't sell, let the split and stock slot do the rebalancing.",
    ]
    return "\n".join(out)


def fmt_drawdown_alert(
    level: float, dd: Drawdown, snap: Snapshot, monthly: float, cushions: tuple[str, ...] = ()
) -> str:
    cushion_line = (f"• {', '.join(cushions)} are there to soften the drop." if cushions
                    else "• A diversified plan is built to ride out drops like this.")
    return "\n".join([
        f"🧘 <b>Hold the line</b>: the portfolio is down {dd.pct(snap.total_cost):.0f}% from its peak "
        f"({money(dd.dollars)} on paper).",
        "",
        "This is the scenario the plan was built for:",
        "• Nothing is sold, so nothing is lost yet.",
        f"• Your next {money(monthly)} buys more shares at lower prices.",
        cushion_line,
        "",
        "Action: <b>none</b>. Keep the monthly buy. /stress shows the bigger picture.",
    ])


def fmt_recorded(rec: Recorded, title: str = "Recorded") -> str:
    rows = [f"{t:<6}{money(a):>8}  {s:,.4f} @ {money(p, cents=True)}" for t, s, p, a in rec.rows]
    out = [f"📝 <b>{esc(title)}</b>", "<pre>" + esc("\n".join(rows)) + "</pre>"]
    out += [f"⚠️ {esc(w)}" for w in rec.warnings]
    out.append("Wrong? /undo")
    return "\n".join(out)


def fmt_history(txs: list[Tx]) -> str:
    if not txs:
        return "No transactions yet. Import holdings (send your broker's positions CSV) or record a buy with /bought."
    rows = [f"{tx.ts[:10]} {tx.kind:<6} {tx.ticker:<6}{money(tx.amount):>8}" for tx in txs]
    return "🧾 <b>Recent activity</b>\n<pre>" + esc("\n".join(rows)) + "</pre>"


def fmt_undo(txs: list[Tx]) -> str:
    if not txs:
        return "Nothing to undo."
    kinds = {tx.kind for tx in txs}
    what = "import (previous holdings restored)" if kinds == {"import"} else f"{len(txs)} transaction(s)"
    return f"↩️ Undid {what}: " + esc(", ".join(f"{tx.ticker} {money(tx.amount)}" for tx in txs[:12]))


def fmt_settings(strategy: Strategy, overrides: dict[str, str]) -> str:
    s = strategy
    g = s.guardrails
    rules = ["never sell"] if g.never_sell else []
    if g.max_single_stock_pct is not None:
        rules.append(f"no stock above {g.max_single_stock_pct:g}%")
    rules += [f"{t} ≤ {c:g}%" for t, c in g.per_ticker_caps.items()]
    if g.has_core_ratio:
        rules.append(f"{g.core_ticker} ≥ {g.core_min_multiple:g}x {g.core_versus}")
    if g.cushions:
        rules.append(f"cushions: {', '.join(g.cushions)}")
    targets = ", ".join(f"{t} {v.pct:g}%" for t, v in sorted(s.targets.items(), key=lambda kv: -kv[1].pct))
    mode = ("auto: each month fills the biggest gaps vs target" if s.mode == "auto"
            else f"fixed split + {money(s.slot_amount)} stock slot" if s.slot_amount else "fixed split")
    changed = f"\n<i>Changed via /set: {esc(', '.join(sorted(overrides)))}. /set reset to undo.</i>" if overrides else ""
    return "\n".join([
        f"⚙️ <b>{esc(s.name)}</b>",
        f"Monthly: <b>{money(s.monthly_amount)}</b> on day {s.reminder_day} at {s.reminder_time:%H:%M} ({esc(s.timezone.key)})",
        f"Goal: <b>{money(s.goal_value)}</b> · projections assume {s.expected_return * 100:g}%/yr",
        f"Mode: {esc(mode)}",
        f"Guardrails: {esc('; '.join(rules))}",
        f"Targets: {esc(targets)}",
        "",
        "Change: <code>/set monthly 3000</code> · <code>/set goal 250k</code> · <code>/set day 15</code> · <code>/set return 6</code>",
        "Change tickers/rules: edit config/strategy.yaml (or rerun <code>pda init</code>) and restart.",
    ]) + changed


HELP = """🤖 <b>Portfolio Deploy Agent</b>

<b>Monthly flow</b>
1. On your reminder day I send your buy list (or tap 📋 Plan).
2. Place the orders at your broker.
3. Tap <b>✅ I bought these</b>. Holdings update automatically.

<b>Commands</b>
/plan [amount]: this month's buy list (e.g. /plan 3000)
/extra 5000: deploy one-off cash into the biggest gaps
/portfolio: value, buckets, goal progress
/drift: every ticker vs target
/guardrails: rule status
/goal: when you hit your money goal
/stress: bad-year scenarios
/bought VOO 650 [@ 612.40]: record a buy (amount). Add "sh" for shares: /bought NVDA 2 sh
/history · /undo
/settings: your plan · /set monthly 3000 · /set goal 250k
/import: send a positions CSV or holdings.yaml

<b>Or just type</b>: "bought 400 of voo", "I got a 5k bonus", "how far am I from the goal?"

Buy-only by design. I'll never tell you to sell."""

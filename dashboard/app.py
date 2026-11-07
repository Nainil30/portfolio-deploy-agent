"""Optional local dashboard:  pip install -e ".[dashboard]"  then  streamlit run dashboard/app.py

Reads the same Service as the bot, so the numbers always match Telegram.
"""

import os

import pandas as pd
import streamlit as st

from pda.config import DEFAULT_DB, DEFAULT_STRATEGY, DEMO_STRATEGY, load_strategy
from pda.engine import monthly_plan
from pda.ledger import Ledger
from pda.prices import StaticPrices, YahooPrices
from pda.service import Service

st.set_page_config(page_title="Portfolio Deploy Agent", page_icon="📈", layout="wide")

has_plan = DEFAULT_STRATEGY.exists()
offline = st.sidebar.toggle("Offline demo prices", value=not has_plan)
if not has_plan:
    st.sidebar.info("No config/strategy.yaml yet: showing the example plan. Run `pda init` to make yours.")


@st.cache_resource
def service(offline: bool) -> Service:
    s = load_strategy(DEFAULT_STRATEGY if has_plan else DEMO_STRATEGY)
    prices = StaticPrices.from_yaml() if offline else YahooPrices(s.yahoo_aliases)
    db = os.getenv("PDA_DB", str(DEFAULT_DB)) if has_plan else ":memory:"
    return Service(s, Ledger(db), prices)


svc = service(offline)
if not has_plan and not svc.ledger.holdings():
    from pda.config import DEMO_HOLDINGS
    from pda.importers import parse_file
    svc.ledger.replace_with_import(parse_file(DEMO_HOLDINGS.name, DEMO_HOLDINGS.read_text(encoding="utf-8")))
snap = svc.snapshot(save=False)
s = svc.strategy

c = s.currency
st.title(f"📈 {s.name}")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Value", f"{c}{snap.total_value:,.0f}", f"{snap.gain_pct:+.1f}%")
c2.metric("Goal progress", f"{snap.total_value / s.goal_value * 100:.1f}%", f"of {c}{s.goal_value:,.0f}")
c3.metric("Monthly", f"{c}{s.monthly_amount:,.0f}", f"{s.mode} mode")
proj = svc.goal(snap)
mid = proj[len(proj) // 2]
c4.metric("Months to goal", mid.months or "50y+", f"at {mid.annual_return:.0%}/yr")

left, right = st.columns([3, 2])
with left:
    st.subheader("Actual vs target")
    df = pd.DataFrame(
        [{"ticker": p.ticker, "actual %": p.actual_pct, "target %": p.target_pct}
         for p in snap.positions.values() if p.value or p.target_pct]
    ).set_index("ticker")
    st.bar_chart(df, stack=False)
with right:
    st.subheader("Guardrails")
    for c in svc.guardrails(snap):
        (st.success if c.status == "ok" else st.warning)(f"**{c.name}**: {c.detail}")

st.subheader("This month's plan")
plan = monthly_plan(snap, s)  # preview only; not saved to the ledger
st.dataframe(pd.DataFrame([{"ticker": ln.ticker, "amount": ln.amount, "why": ln.reason} for ln in plan.lines]),
             hide_index=True, use_container_width=True)
for n in plan.notes:
    st.caption("🛡 " + n.message)

hist = svc.ledger.snapshots()
if len(hist) > 1:
    st.subheader("History")
    h = pd.DataFrame(hist, columns=["day", "value", "invested"]).set_index("day")
    st.line_chart(h)

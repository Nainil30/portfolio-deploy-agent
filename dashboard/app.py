# dashboard/app.py
"""
Streamlit dashboard for portfolio visualization.

Run with: streamlit run dashboard/app.py
    or:   python -m streamlit run dashboard/app.py
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import json

st.set_page_config(
    page_title="Portfolio Deploy Agent",
    page_icon="📊",
    layout="wide",
)


# ── DATA LOADING ───────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_portfolio():
    """Fetch live prices and build portfolio state. Cached 5 minutes."""
    from src.utils.config_loader import load_config
    from src.tools.market_data import get_current_prices
    from src.tools.portfolio_math import build_portfolio_state

    config = load_config()
    tickers = [h["ticker"] for h in config["holdings"]]
    prices = get_current_prices(tickers)
    portfolio = build_portfolio_state(
        config["holdings"], config["target_allocation"], prices
    )
    return portfolio, config


def load_history():
    """Load deployment history from database."""
    try:
        from src.tools.database import get_deployments
        return get_deployments()
    except Exception:
        return []


def load_snapshots():
    """Load portfolio snapshots for trend chart."""
    try:
        from src.tools.database import get_snapshots
        return get_snapshots()
    except Exception:
        return []


# ── LOAD DATA ──────────────────────────────────────────────────

st.title("📊 Portfolio Deployment Agent")

try:
    with st.spinner("Fetching live market data..."):
        portfolio, config = load_portfolio()
except Exception as e:
    st.error(f"Failed to load portfolio: {e}")
    st.info("Make sure config/portfolio_config.yaml exists and is valid.")
    st.stop()


# ── TOP METRICS ────────────────────────────────────────────────

budget = config["budget"]["monthly_amount"]
strategy = config.get("strategy", "lump_sum")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Portfolio Value", f"${portfolio.total_value:,.2f}")
col2.metric("Total Cost", f"${portfolio.total_cost:,.2f}")
col3.metric(
    "Total Return",
    f"{portfolio.total_return_pct:+.2f}%",
    delta=f"${portfolio.total_value - portfolio.total_cost:,.2f}",
)
col4.metric("Monthly Budget", f"${budget:,.0f}")

st.divider()


# ── ALLOCATION CHARTS ─────────────────────────────────────────

holdings_df = pd.DataFrame([
    {
        "Ticker": h.ticker,
        "Actual %": h.actual_pct,
        "Target %": h.target_pct,
        "Drift": h.drift,
        "Value": h.current_value,
        "Price": h.current_price,
        "Shares": h.shares,
        "Avg Cost": h.avg_cost,
    }
    for h in portfolio.holdings
])

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Actual vs Target Allocation")
    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(
        name="Actual",
        x=holdings_df["Ticker"],
        y=holdings_df["Actual %"],
        marker_color="#4CAF50",
    ))
    fig_bar.add_trace(go.Bar(
        name="Target",
        x=holdings_df["Ticker"],
        y=holdings_df["Target %"],
        marker_color="#2196F3",
    ))
    fig_bar.update_layout(
        barmode="group",
        height=380,
        yaxis_title="Allocation %",
        margin=dict(t=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig_bar, use_container_width=True)

with col_right:
    st.subheader("Portfolio Composition")
    fig_pie = px.pie(
        holdings_df,
        values="Value",
        names="Ticker",
        color_discrete_sequence=px.colors.qualitative.Set3,
    )
    fig_pie.update_layout(height=380, margin=dict(t=10))
    st.plotly_chart(fig_pie, use_container_width=True)


# ── DRIFT ANALYSIS ─────────────────────────────────────────────

st.divider()
st.subheader("Allocation Drift")

drift_sorted = holdings_df.sort_values("Drift")

colors = []
for d in drift_sorted["Drift"]:
    if d < -2:
        colors.append("#f44336")
    elif d > 2:
        colors.append("#FF9800")
    else:
        colors.append("#4CAF50")

fig_drift = go.Figure(go.Bar(
    x=drift_sorted["Ticker"],
    y=drift_sorted["Drift"],
    marker_color=colors,
    text=[f"{d:+.1f}%" for d in drift_sorted["Drift"]],
    textposition="outside",
))
fig_drift.update_layout(
    height=320,
    yaxis_title="Drift from Target (%)",
    margin=dict(t=10, b=60),
    shapes=[dict(
        type="line", y0=0, y1=0,
        x0=-0.5, x1=len(drift_sorted) - 0.5,
        line=dict(color="gray", dash="dash"),
    )],
)
st.plotly_chart(fig_drift, use_container_width=True)
st.caption("🔴 Red = Underweight (buy more) · 🟢 Green = On target · 🟡 Orange = Overweight (skip)")


# ── HOLDINGS TABLE ─────────────────────────────────────────────

st.divider()
st.subheader("Holdings")

table_data = []
for h in sorted(portfolio.holdings, key=lambda x: x.drift):
    gain_pct = ((h.current_price - h.avg_cost) / h.avg_cost * 100) if h.avg_cost > 0 else 0

    if h.drift < -2:
        status = "🔴 Buy More"
    elif h.drift > 2:
        status = "🟡 Skip"
    else:
        status = "🟢 OK"

    table_data.append({
        "Ticker": h.ticker,
        "Shares": round(h.shares, 4),
        "Avg Cost": f"${h.avg_cost:,.2f}",
        "Price": f"${h.current_price:,.2f}",
        "Gain": f"{gain_pct:+.1f}%",
        "Value": f"${h.current_value:,.2f}",
        "Target": f"{h.target_pct:.1f}%",
        "Actual": f"{h.actual_pct:.1f}%",
        "Drift": f"{h.drift:+.1f}%",
        "Action": status,
    })

st.dataframe(
    pd.DataFrame(table_data),
    use_container_width=True,
    hide_index=True,
)


# ── CATEGORY BREAKDOWN ────────────────────────────────────────

if "category_targets" in config:
    st.divider()
    st.subheader("Category Allocation")

    cat_values = {}
    for h_conf in config["holdings"]:
        cat = h_conf.get("category", "other")
        holding = next(
            (h for h in portfolio.holdings if h.ticker == h_conf["ticker"]),
            None,
        )
        if holding:
            cat_values[cat] = cat_values.get(cat, 0) + holding.current_value

    cat_rows = []
    for cat, target_pct in config["category_targets"].items():
        actual_val = cat_values.get(cat, 0)
        actual_pct = (actual_val / portfolio.total_value * 100) if portfolio.total_value > 0 else 0
        drift = actual_pct - target_pct
        cat_rows.append({
            "Category": cat.upper(),
            "Value": f"${actual_val:,.0f}",
            "Actual %": f"{actual_pct:.1f}%",
            "Target %": f"{target_pct:.0f}%",
            "Drift": f"{drift:+.1f}%",
        })

    st.dataframe(
        pd.DataFrame(cat_rows),
        use_container_width=True,
        hide_index=True,
    )


# ── STRATEGY INFO ─────────────────────────────────────────────

st.divider()
st.subheader("Deployment Strategy")

if strategy == "split_tranches":
    tranches_config = config.get("tranches", {})
    t1 = tranches_config.get("immediate_pct", 60)
    t2 = tranches_config.get("dip_reserve_pct", 25)
    t3 = tranches_config.get("deep_dip_reserve_pct", 15)
    dip_thresh = tranches_config.get("dip_threshold_pct", 2.0)
    deep_thresh = tranches_config.get("deep_dip_threshold_pct", 3.5)
    payday = config.get("schedule", {}).get("payday", 15)

    col_a, col_b, col_c = st.columns(3)
    col_a.metric(
        f"Tranche 1 — Payday (Day {payday})",
        f"${budget * t1 / 100:,.0f}",
        delta=f"{t1}% of budget",
    )
    col_b.metric(
        f"Tranche 2 — Dip ({dip_thresh}%+ drop)",
        f"${budget * t2 / 100:,.0f}",
        delta=f"{t2}% reserved",
    )
    col_c.metric(
        f"Tranche 3 — Deep Dip ({deep_thresh}%+)",
        f"${budget * t3 / 100:,.0f}",
        delta=f"{t3}% reserved",
    )
else:
    st.info(f"Strategy: **{strategy}** — Deploy ${budget:,.0f} on payday as a lump sum.")


# ── DEPLOYMENT HISTORY ─────────────────────────────────────────

st.divider()
st.subheader("Deployment History")

history = load_history()
if history:
    for entry in history[:10]:
        plan = json.loads(entry["plan_json"])
        tranche_label = plan.get("tranche", "full")
        label = f"{entry['date'][:10]} | {tranche_label} | ${entry['budget']:,.0f}"

        with st.expander(label):
            recs = plan.get("recommendations", [])
            if recs:
                rec_df = pd.DataFrame([
                    {
                        "Ticker": r["ticker"],
                        "Amount": f"${r['dollar_amount']:,.0f}",
                        "% Budget": f"{r['pct_of_budget']:.0f}%",
                        "Reasoning": r["reasoning"],
                    }
                    for r in recs
                ])
                st.dataframe(rec_df, use_container_width=True, hide_index=True)
            else:
                st.write("No buys this run (monitoring only).")

            if plan.get("summary"):
                st.caption(plan["summary"])
else:
    st.info("No history yet. Run `python main.py` to generate your first recommendation.")


# ── PORTFOLIO VALUE OVER TIME ──────────────────────────────────

snapshots = load_snapshots()
if len(snapshots) > 1:
    st.divider()
    st.subheader("Portfolio Value Over Time")

    snap_df = pd.DataFrame(snapshots)
    snap_df["date"] = pd.to_datetime(snap_df["date"])

    fig_line = px.line(
        snap_df,
        x="date",
        y="total_value",
        markers=True,
        labels={"total_value": "Value ($)", "date": "Date"},
    )
    fig_line.update_layout(height=350, margin=dict(t=10))
    st.plotly_chart(fig_line, use_container_width=True)


# ── FOOTER ─────────────────────────────────────────────────────

st.divider()
st.caption(
    "Personal portfolio tool, not financial advice. "
    "Built with LangGraph, Streamlit, and yfinance."
)

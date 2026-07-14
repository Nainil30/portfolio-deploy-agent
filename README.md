# 📊 Portfolio Deployment Agent

**AI-powered monthly investment deployment assistant built with LangGraph**

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/downloads/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent-orange.svg)](https://github.com/langchain-ai/langgraph)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Streamlit](https://img.shields.io/badge/Dashboard-Streamlit-red.svg)](https://streamlit.io)

---

> **The Problem:** You have $1,500/month to invest across 8+ ETFs and stocks in Fidelity. Every month you stare at prices, don't know what's underweight, miss dips, buy emotionally, or freeze and skip the month entirely.
>
> **The Solution:** An AI agent system that analyzes your portfolio, scores market conditions, splits your budget into smart tranches, detects dips, and sends you a Telegram notification with exact dollar amounts to type into Fidelity. Takes 3 minutes to execute. Zero decision fatigue.

---

## 🎬 How It Works

```text
Payday (Day 15):
  📱 Telegram: "Deploy $900 now"
     → Buy $400 of SCHD
     → Buy $250 of SPMO
     → Buy $150 of VOO
     → Buy $100 of MSFT
  You: Open Fidelity → Type amounts → Done in 3 minutes

Week 3 (Day 22 — SCHD drops 3%):
  📱 Telegram: "DIP ALERT — Deploy $375 into SCHD"
  You: Open Fidelity → Buy $375 of SCHD → Caught the dip!

Month End (Day 28 — no more dips):
  📱 Telegram: "Deploy remaining $225"
     → Buy $125 of AMZN
     → Buy $100 of QQQM
  You: Final deployment → $1,500 fully invested → Zero cash drag



---
## ✨ Features

| Feature | Description |
|---------|-------------|
| **Smart Tranches** | Split monthly budget into 3 deployment windows: 60% on payday, 25% for dip-buying, 15% for deep dips or month-end |
| **Dollar-Based** | All recommendations in dollar amounts — matches how Fidelity actually works. No fractional share math. |
| **Category Allocation** | Set targets like "60% ETFs, 30% stocks, 10% gold" — system auto-balances within categories |
| **Market Scoring** | Each ticker scored 1-10 using RSI, SMA-20, drawdown from highs, consecutive red days, and VIX |
| **Dip Detection** | Monitors positions daily. Alerts when any ticker drops 2%+ below its 20-day moving average |
| **LangGraph Agents** | Multi-agent orchestration with shared state, conditional routing, and self-critique reflection loop |
| **LLM Analysis** | Natural language summary explaining why each recommendation was made (Groq, free tier) |
| **Telegram Alerts** | Push notifications to your phone with buy list. Only notifies when action is needed — not every day |
| **Streamlit Dashboard** | Visual portfolio overview: allocation charts, drift analysis, deployment history, value over time |
| **GitHub Actions** | Fully automated — runs daily after market close, monitors for dips, sends alerts. Zero manual effort |
| **SQLite Persistence** | Tracks portfolio snapshots and deployment history over time for trend analysis |
| **Config-Driven** | Edit one YAML file with your holdings. No code changes needed. Works for any portfolio |



## 🏗️ Architecture

```text
┌──────────────────────────────────────────────────────────────────┐
│                    LANGGRAPH AGENT WORKFLOW                       │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│   Config Loader                                                  │
│       │                                                          │
│       ▼                                                          │
│   Portfolio Tracker ◄── yfinance (live prices, free)             │
│       │                                                          │
│       ▼                                                          │
│   Analyst + Strategist ◄── RSI, SMA, VIX scoring                │
│       │                    Tranche logic (which tranche today?)  │
│       │                    Dollar allocation math                │
│       │                    LLM commentary (Groq, free)           │
│       ▼                                                          │
│   Reflection Agent ── FAIL ──► (loop back to Strategist)        │
│       │                        max 2 revisions                   │
│       │ PASS                                                     │
│       ▼                                                          │
│   Notification Agent ──► Console output                         │
│                      ──► Telegram push notification              │
│                      ──► SQLite deployment log                   │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘


PYTHON handles (deterministic, trustworthy):
  ✓ Portfolio value calculations
  ✓ Allocation percentages and drift
  ✓ RSI, SMA, and technical scoring
  ✓ Dollar amount allocation across positions
  ✓ Position cap enforcement

LLM handles (natural language, communicative):
  ✓ Explaining WHY the plan makes sense
  ✓ Summarizing market conditions in plain English
  ✓ Addressing reflection feedback in revised summaries

The LLM never touches financial calculations.
Numbers are too important to trust to probabilistic text generation.



---
## 📊 Smart Tranche Strategy

The monthly budget is split into 3 deployment tranches to balance immediate deployment with dip-buying opportunity.

```text
MONTHLY BUDGET: $1,500
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tranche 1 — IMMEDIATE (60% = $900)
  When: Payday
  What: Deploy into most underweight positions
  Why:  Gets money working immediately. Lump sum beats
        DCA 68% of the time (Vanguard research).

Tranche 2 — DIP RESERVE (25% = $375)
  When: First time any position drops 2%+ below 20-day SMA
  What: Deploy into the dipping position(s)
  Why:  Catches short-term pullbacks. Buy low, not high.
  Deadline: If no dip by day 20, deploy into most underweight.

Tranche 3 — DEEP DIP RESERVE (15% = $225)
  When: Any position drops 3.5%+ below 20-day SMA
  What: Deploy into the deeply dipping position(s)
  Why:  Reserved for significant drops. Maximum value capture.
  Deadline: If no deep dip by day 28, deploy remaining cash.

GUARANTEE: All $1,500 is deployed every month.
           Cash never rolls over. No analysis paralysis.



Day 1-14:  Before payday → "No action. Waiting for payday."
Day 15:    Payday → "DEPLOY Tranche 1: $900" (Telegram alert)
Day 16-19: Monitoring for dips → silent (no notification)
Day 20:    Dip detected → "DIP ALERT: Deploy $375 into SCHD"
Day 21-27: Monitoring for deep dips → silent
Day 28:    No deep dip → "Deploy remaining $225" (Telegram alert)
Day 29-31: "All tranches deployed. No action."




---

## 🚀 Quick Start

### Option 1: GitHub Codespaces (Zero Install, Recommended)

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/Nainil30/portfolio-deploy-agent)

1. Click the badge above — full VS Code opens in your browser
2. Everything is pre-installed automatically
3. Edit `config/portfolio_config.yaml` with your holdings
4. Edit `.env` with your API keys
5. Run: `python main.py`

### Option 2: Local Setup (15 minutes)

**Prerequisites:** Python 3.12+, Git

```bash
# Clone the repository
git clone https://github.com/Nainil30/portfolio-deploy-agent.git
cd portfolio-deploy-agent

# Create virtual environment
python -m venv .venv
source .venv/bin/activate        # Mac/Linux
# source .venv/Scripts/activate  # Windows Git Bash

# Install dependencies
pip install -e .

# Copy example config files
cp config/portfolio_config.example.yaml config/portfolio_config.yaml
cp .env.example .env

# Edit config with your real holdings
# (see Configuration section below)

# Edit .env with your API keys
# (see API Keys section below)

# Run the agent
python main.py

# Launch the dashboard (optional)
streamlit run dashboard/app.py



Telegram Chat ID Setup:
	1. After creating your bot, search for it in Telegram and send it hello
	2. Open your browser to: https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
	3. Find "chat": {"id": 123456789} in the JSON — that number is your Chat ID
	4. Add both token and chat ID to your .env file
Your .env file should look like:

GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_BOT_TOKEN=7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_CHAT_ID=987654321



---


## ⚙️ Configuration

Edit `config/portfolio_config.yaml` with your real portfolio. This is the **only file you need to change**.

```yaml
budget:
  monthly_amount: 1500.00        # Your monthly investment amount
  currency: "USD"
  max_single_position_pct: 0.40  # No single buy exceeds 40% of tranche

strategy: "split_tranches"       # "split_tranches" or "lump_sum"

tranches:
  immediate_pct: 60              # Deploy on payday
  dip_reserve_pct: 25            # Deploy when a position dips 2%+
  deep_dip_reserve_pct: 15       # Deploy on deep dips or month-end
  dip_threshold_pct: 2.0
  deep_dip_threshold_pct: 3.5
  dip_deadline_day: 20
  final_deadline_day: 28

schedule:
  payday: 15                     # Day of month you invest
  pay_frequency: "biweekly"

holdings:
  - ticker: "VOO"                # S&P 500 ETF
    shares: 15                   # Your current share count
    avg_cost_per_share: 485.00   # Your cost basis
    category: "etf"              # Category for allocation targets

  - ticker: "QQQM"
    shares: 12
    avg_cost_per_share: 175.00
    category: "etf"

  # Add all your positions...

# Category-level targets (must sum to 100)
category_targets:
  etf: 60
  stocks: 30
  gold: 10

# LLM provider
llm:
  provider: "groq"
  model: "llama-3.1-8b-instant"




---


## 🛠️ Tech Stack

| Component | Technology | Cost | Why |
|-----------|-----------|------|-----|
| Agent Framework | [LangGraph](https://github.com/langchain-ai/langgraph) | Free | State machines, conditional edges, agentic loops |
| LLM | [Groq](https://console.groq.com) (Llama 3.1 8B) | Free tier | Fastest inference, 30 req/min free |
| Market Data | [yfinance](https://github.com/ranaroussi/yfinance) | Free | No API key needed, reliable daily data |
| Data Models | [Pydantic v2](https://docs.pydantic.dev) | Free | Type-safe structured outputs |
| Database | SQLite | Free | Zero setup, ships with Python |
| Dashboard | [Streamlit](https://streamlit.io) | Free | Python-native, free cloud hosting |
| Notifications | [Telegram Bot API](https://core.telegram.org/bots) | Free | Instant push, interactive |
| Automation | [GitHub Actions](https://github.com/features/actions) | Free | Daily scheduled runs |
| Linting | [Ruff](https://github.com/astral-sh/ruff) | Free | Fast Python linter |
| Testing | [pytest](https://pytest.org) | Free | Industry standard |

**Total monthly cost: $0.00**

## 📁 Project Structure

```text
portfolio-deploy-agent/
├── main.py                          # Entry point — run this
├── pyproject.toml                   # Dependencies and project config
├── requirements.txt                 # For Streamlit Cloud deployment
├── README.md
├── .env.example                     # Template for API keys
├── .gitignore
│
├── config/
│   ├── portfolio_config.example.yaml  # Template for new users
│   └── portfolio_config.yaml          # YOUR config (gitignored)
│
├── src/
│   ├── graph/
│   │   ├── state.py                 # AgentState TypedDict
│   │   ├── nodes.py                 # 5 agent implementations
│   │   └── workflow.py              # LangGraph StateGraph
│   │
│   ├── tools/
│   │   ├── market_data.py           # yfinance + RSI + scoring
│   │   ├── portfolio_math.py        # Allocation + tranche math
│   │   └── database.py              # SQLite operations
│   │
│   ├── models/
│   │   └── portfolio.py             # Pydantic data models
│   │
│   ├── notifications/
│   │   └── telegram_bot.py          # Telegram sender
│   │
│   └── utils/
│       ├── config_loader.py         # YAML + category resolution
│       └── llm_provider.py          # Groq/Gemini/Ollama factory
│
├── dashboard/
│   └── app.py                       # Streamlit dashboard
│
├── data/
│   └── portfolio.db                 # SQLite database (gitignored)
│
├── tests/
│   └── test_portfolio_math.py       # Unit tests
│
├── .github/workflows/
│   └── daily_analysis.yml           # Scheduled automation
│
└── .devcontainer/
    └── devcontainer.json            # One-click Codespaces setup



---

## README Part 8: Usage, Dashboard, Roadmap, License

```markdown
## 📱 Usage

### Daily Operation

Once configured and GitHub Actions is set up, the agent runs automatically every weekday at 4:30 PM ET (after market close). You receive Telegram notifications only when action is needed.

**Manual run (anytime):**

```bash
python main.py

streamlit run dashboard/app.py

Dashboard Features
The Streamlit dashboard provides:
	• Portfolio Metrics — total value, cost basis, total return
	• Allocation vs Target — bar chart comparing actual allocation to targets
	• Portfolio Composition — pie chart of holdings
	• Drift Analysis — color-coded chart showing which positions are underweight (red), on-target (green), or overweight (orange)
	• Holdings Table — detailed view with shares, prices, cost basis, and drift status
	• Category Breakdown — ETF/Stocks/Gold allocation vs targets
	• Deployment History — log of all past deployment recommendations
	• Portfolio Value Over Time — line chart tracking portfolio growth
	Note: The dashboard reads your portfolio config and fetches live prices. It does NOT modify your config file. To update your holdings after buying, edit config/portfolio_config.yaml manually.
Automated GitHub Actions
The agent runs automatically via GitHub Actions. To set it up:
	1. Go to your repo → Settings → Secrets and variables → Actions
	2. Add these secrets:
	Secret Name	Value
	GROQ_API_KEY	Your Groq API key
	TELEGRAM_BOT_TOKEN	Your Telegram bot token
	TELEGRAM_CHAT_ID	Your Telegram chat ID
	PORTFOLIO_CONFIG	Entire contents of your portfolio_config.yaml
	3. Go to Actions tab → Daily Portfolio Analysis → Run workflow to test
The workflow runs automatically Monday-Friday at 4:30 PM ET.
🗺️ Roadmap
	• Core portfolio tracking engine
	• Dollar-based deployment (matches Fidelity)
	• Category-level allocation targets
	• Market scoring (RSI, SMA, drawdown, VIX)
	• LangGraph multi-agent orchestration
	• Reflection/self-critique agentic loop
	• Smart tranche deployment (60/25/15 split)
	• Dip detection and targeted buying
	• Telegram push notifications
	• Streamlit dashboard
	• GitHub Actions daily automation
	• SQLite persistence and history tracking
	• RAG integration — fundamental analysis from earnings transcripts
	• MCP server — query portfolio from any AI assistant
	• Backtesting — compare agent strategy vs buy-and-hold
	• Multi-broker support (Schwab, Robinhood, IBKR)
	• CLI onboarding wizard for new users
	• Fractional rebalancing suggestions
🤝 Contributing
Contributions welcome! This project is designed to be useful for anyone who invests monthly from their salary.
	1. Fork the repository
	2. Create a feature branch: git checkout -b feature/your-feature
	3. Commit changes: git commit -m "feat: your feature"
	4. Push: git push origin feature/your-feature
	5. Open a Pull Request
📄 License
MIT — use it, fork it, improve it.
⚠️ Disclaimer
This is a personal portfolio management tool, not financial advice. It does not execute trades — it only recommends. Past performance does not predict future results. Always do your own research before making investment decisions. The authors are not liable for any financial losses
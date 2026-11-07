# 📈 Portfolio Deploy Agent

**A buy-only Telegram co-pilot that turns a written investing plan into a monthly buy list, enforces guardrails, keeps your holdings up to date, and talks you out of panic-selling.**

Free to run: Telegram bot API + Yahoo Finance + SQLite, plus an *optional* free LLM (Groq / Gemini / local Ollama).

```
 You (Telegram)                              Payday, 9:30 AM
 ─────────────                               ───────────────
 "📋 Plan"  ──────────────▶  🗓 Monthly buy list: $2,000
                             VOO    $750   ≈1.103 sh
                             SPCX   $400   ≈3.030 sh   ← stock slot: furthest below target
                             VHT    $250   ...
                             🛡 VOO is 1.3x QQQM (rule: ≥3x). $100 of QQQM moved to VOO.
                             [ ✅ I bought these ]  [ ⏭ Skip ]
 tap ✅  ─────────────────▶  📝 Bought, ledger updated
 "should I sell?" ────────▶  🛑 No selling. Here's what a bad year looks like on paper…
```

---

## The plan it enforces

| Bucket | Holdings | Share |
|---|---|---|
| Core ETFs | VOO 30%, QQQM 10% | 40% |
| Other ETFs | VHT 8%, SMH 6%, SCHD 2.8%, SPMO 2.4%, VXUS 0.8% | 20% |
| Gold | IAUM 8% | 8% |
| Stocks | BRK.B 7%, NVDA 5%, GOOGL 4%, DELL 3%, TSLA 2.5%, SPCX 2.5%, MSFT 2.5%, AMZN 2%, PLTR 1.5%, AMD 1%, LLY 0.6%, INTC 0.4% | 32% |

**Monthly $2,000:** VOO $650 · VHT $250 · BRK.B $200 · IAUM $200 · SMH $150 · QQQM $100 · SPMO $50 · **stock slot $400** → whichever of NVDA, GOOGL, SPCX, TSLA, MSFT, AMZN is furthest below its target.

**Guardrails (code, not suggestions):**
1. **VOO ≥ 3× QQQM.** QQQM's top holdings are already inside VOO. If a buy would break the ratio, the QQQM money goes to VOO.
2. **No single stock above 5%** of the portfolio *after* the buy. DELL is capped at 3% because your job already gives you Dell exposure. BRK.B is capped at its own 7% target, since it's a diversified holding company. Excess goes to VOO.
3. **VHT and BRK.B are the biggest non-AI buys.** Validated at startup and enforced on every plan.
4. **Never sell.** The engine has no sell output. `/sold` exists only to keep the ledger in sync with your broker, and it asks you to confirm.
5. **Rebalance only with new money.** Drift is closed by steering the monthly buys, the stock slot, and `/extra` cash.

Everything lives in [`config/strategy.yaml`](config/strategy.yaml), validated strictly at startup (targets = 100%, split = monthly amount, caps ≥ targets, cushions largest).

---

## Quick start (about 10 minutes)

```bash
git clone https://github.com/Nainil30/portfolio-deploy-agent && cd portfolio-deploy-agent
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pda validate                       # checks strategy.yaml
pda --offline plan                 # try it with demo prices, no keys needed
```

**1. Create the bot.** In Telegram, message **@BotFather** → `/newbot` → copy the token.
**2. Configure.** `cp .env.example .env` and paste `TELEGRAM_BOT_TOKEN`.
**3. Run.** `pda bot`, then send `/start` to your bot. It replies with your chat id. Put it in `.env` as `TELEGRAM_CHAT_ID` and restart. From then on only your chat can use the bot.
**4. Load holdings.** In Fidelity: *Accounts & Trade → Portfolio → Positions → Download*. Send the CSV to the bot. (Or `cp config/holdings.example.yaml config/holdings.yaml`, edit it, and run `pda import config/holdings.yaml`.)
**5. Optional AI.** Get a free key at [console.groq.com](https://console.groq.com) and set `GROQ_API_KEY`. Without it, plain-English buy logging still works through the rule-based parser.

### Keeping it running for $0
| Option | How |
|---|---|
| Your PC | `pda bot` (Windows: Task Scheduler "At log on"; macOS/Linux: `tmux` or a systemd user service) |
| Always-free VM (Oracle Cloud, GCP e2-micro) or Raspberry Pi | `docker compose up -d`. The ledger is kept in `./data` |
| No always-on machine | Cron or Task Scheduler runs `pda send-plan` on payday. You record buys with the CLI, or open the bot when you're at your PC |

---

## Using it

| Command | What it does |
|---|---|
| `/plan [amount]` | This month's buy list with reasons + ✅ button (`/plan 3000` scales the split) |
| `/extra 5000` | Bonus / refund cash → fills the biggest gaps vs target |
| `/portfolio` · `/drift` | Value, buckets, AI exposure · every ticker vs target |
| `/guardrails` | ✅/⚠️ for each rule with the exact numbers |
| `/goal [monthly]` | Months to $155k at 4% / 7% / 10% |
| `/stress` | Paper loss in an AI sell-off, a bear market, or a correction |
| `/bought VOO 650 [@ 612.4]` · `/bought NVDA 2 sh` | Record a buy in $ or shares |
| `/history` · `/undo` | Audit trail; undo the last record **or import** |
| *send a .csv / .yaml* | Replace the ledger with your broker's positions |
| *free text* | "bought 400 of nvda", "got a 5k bonus", "how long to 155k?", "should I sell?" |

**Automatic messages:** your buy list on payday (`reminder_day`, skipped if already recorded). A "hold the line" message the first time the portfolio is 10/20/30% below its peak. A Sunday digest with a nudge if this month's buys aren't recorded yet.

The CLI mirrors everything: `pda plan`, `pda extra 5000`, `pda portfolio`, `pda guardrails`, `pda import file.csv`, `pda bought VOO 650`, `pda ask "…"`, etc. Add `--offline` for demo prices.

Optional dashboard: `pip install -e ".[dashboard]" && streamlit run dashboard/app.py`.

---

## Architecture

```mermaid
flowchart LR
    TG[Telegram<br/>commands · buttons · text · files] --> BOT[bot.py<br/>auth · handlers · jobs]
    CLI[CLI pda] --> SVC
    DASH[Streamlit] --> SVC
    BOT --> INT[intents.py<br/>rule-based NLU]
    BOT -. optional .-> LLM[llm.py<br/>tool-calling agent]
    INT --> SVC
    LLM -- read-only tools<br/>+ propose_buy --> SVC
    BOT --> SVC[service.py<br/>facade]
    SVC --> ENG[engine.py<br/>monthly · stock slot · gap fill]
    ENG --> GR[guardrails.py<br/>caps · 3x · cushions · buy-only]
    SVC --> LED[(ledger.py<br/>SQLite transactions)]
    SVC --> PX[prices.py<br/>Yahoo / static]
    SVC --> INS[insights.py<br/>goal · drawdown · stress]
```

**Core idea: the rules decide and the LLM only explains.** Money math is pure, deterministic and unit-tested. The LLM can only call read-only tools or *propose* a buy that you confirm with a button.

```
src/pda/
  config.py      strategy.yaml → typed Strategy + strict validation
  models.py      dataclasses: Position, Snapshot, Plan, BuyLine, Adjustment
  prices.py      PriceProvider protocol; YahooPrices (cached, aliases) / StaticPrices
  ledger.py      append-only SQLite ledger; holdings are replayed from it; undo; imports
  portfolio.py   holdings + prices → Snapshot with drift
  engine.py      monthly_plan, pick_slot, extra_plan
  guardrails.py  apply_guardrails (moves money) + check_portfolio (status report)
  insights.py    months_to_goal, drawdown, stress_test
  importers.py   Fidelity CSV / YAML parsing
  intents.py     regex + keyword NLU (no key needed)
  llm.py         OpenAI-compatible tool-calling agent (Groq/Gemini/Ollama)
  formatting.py  Telegram HTML + plain-text rendering
  service.py     facade shared by bot, CLI, LLM tools and dashboard
  bot.py         python-telegram-bot v21: handlers, buttons, scheduled jobs
```

## Tests

```bash
pytest -q          # 77 tests, no network: engine, guardrails, ledger, parser, bot handlers, LLM loop
ruff check src tests
```

CI runs both on Python 3.11 and 3.12 for every push.

## What changed from v1

v1 was a LangGraph pipeline that sent a daily push. v2 is an interactive tool built around your actual plan. See [docs/INTERVIEW_GUIDE.md](docs/INTERVIEW_GUIDE.md) for the full reasoning. The short version:
- The **ledger** replaced hand-edited YAML holdings: one tap records a month's buys, and holdings stay correct.
- **GitHub Actions + SQLite lost state every run.** v2 runs on any machine that keeps state, or uses `send-plan` for cron.
- The **reflection loop** re-ran identical math. It's replaced by guardrails that actually change the plan and explain why.
- **Dip-timing tranches** were dropped: your plan is a fixed split with new-money rebalancing.
- **No LLM key needed.** The LLM is now an optional explainer, not a required step.
- Removed the committed `.venv` (16k files), the database, and personal holdings from the repo.

---

*Personal planning tool. Not financial advice. Market data from Yahoo Finance may be delayed.*

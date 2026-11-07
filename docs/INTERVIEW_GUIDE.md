# Interview Guide: Portfolio Deploy Agent v2

How to explain this project in an AI or software interview: a pitch, the build story step by step, the design decisions, and answers to likely questions.

---

## 1. The 30-second pitch

> "I invest $2,000 a month with a written plan: target weights, a fixed monthly split, and a few guardrails like 'VOO stays at least 3× QQQM' and 'never sell in a drop'. The hard part isn't the math, it's following the plan every month without second-guessing it. So I built a Telegram bot that does three things. On payday it sends a buy list. It enforces my guardrails in code and explains every adjustment. And it keeps my holdings in sync with one tap. An LLM is an optional layer for plain-English questions. It can read data through tools and propose a buy, but it never decides an amount, and nothing is written until I confirm."

## 2. The 2-minute version (problem → design → AI → result)

1. **Problem.** v1 was a LangGraph pipeline that pushed a daily message. When I reviewed it I found real bugs:
   - It ran on GitHub Actions with SQLite, so state reset every run and it re-sent the same tranche daily.
   - Holdings were hand-edited YAML, so they went stale.
   - The "reflection" loop re-ran deterministic math, so a revision could never change anything.
   - The repo had a committed virtualenv and my personal positions in it.
2. **Design.** I rebuilt it around one principle: **the rules decide, the LLM explains.**
   - The plan lives in `strategy.yaml` and is strictly validated at startup.
   - A pure-function engine builds the buy list, and a guardrail layer moves money when a rule would be broken. Each move comes with a plain-English reason.
   - An append-only SQLite ledger is the source of truth, so I get undo and an audit trail for free.
3. **AI layer.** It's a tool-calling agent behind an OpenAI-compatible interface, so it works with Groq or Gemini (free tiers) or Ollama (local).
   - Tools are read-only except `propose_buy`, which needs a human tap (human-in-the-loop).
   - If there's no API key, a regex/keyword parser handles the common phrases, so the bot is fully usable for $0.
4. **Result.** One tap a month keeps the portfolio on plan. There are 77 offline tests and CI on 3.11/3.12. It runs free on a PC, a Pi or an always-free VM.

---

## 3. How I built it, step by step

### Step 1: Review v1 critically
- Read every module and traced a full run.
- Listed the defects: state loss on CI, push-only bot, cosmetic reflection loop, per-budget (not per-portfolio) caps, the `enabled: true7` config typo, duplicated code, committed `.venv`/DB/holdings, and a hard dependency on an LLM key.
- **Talking point:** "I treated my own code like a code review. What looks agentic but doesn't change outcomes?"

### Step 2: Turn the investing plan into a spec (`config/strategy.yaml`)
- Targets per ticker (with `bucket` and an `ai` tag), the monthly split, the stock-slot candidates and the guardrail parameters.
- **Strict validation** (`config.py`):
  - targets total exactly 100%
  - split + slot equals the monthly amount
  - every bought ticker has a target
  - no target is above its own cap
  - the written split already keeps VHT/BRK.B as the largest non-AI buys
- Validation caught a contradiction in my own plan: BRK.B at 7% conflicts with "no stock above 5%". I resolved it explicitly with a per-ticker cap (a diversified holding company is capped at its target) instead of letting the code silently pick one.
- **Talking point:** "Config is code. A typo in an investing plan should crash at startup, not produce a wrong buy list."

### Step 3: Domain model (`models.py`)
- Small dataclasses: `Position`, `Snapshot`, `Plan`, `BuyLine`, `Adjustment`, `RuleCheck`.
- `Adjustment` is the key one: every guardrail decision is a structured record with a message. That's what makes the system explainable to me and to the LLM.

### Step 4: Ledger as the source of truth (`ledger.py`)
- An append-only `transactions` table; holdings are **derived** by replaying it (sells reduce cost at average cost).
- Every write is a **batch**, so `/undo` removes the last batch.
- A broker CSV import **voids** old rows instead of deleting them, so even an import can be undone.
- Plans are stored with a status (`proposed`/`executed`/`skipped`). That makes the ✅ button **idempotent**, and the payday reminder doesn't fire if the month is already recorded.
- **Talking point:** "Event sourcing in miniature: undo, audit trail and idempotency come from one design decision."

### Step 5: Prices behind an interface (`prices.py`)
- A `PriceProvider` protocol, with `YahooPrices` (batch download, per-ticker retry, 10-minute cache, `BRK.B → BRK-B` alias) and `StaticPrices` for tests and the offline demo.
- A missing price never crashes anything: the position is valued at cost and flagged, and a stock-slot candidate without a price is skipped with a note.

### Step 6: The engine (`engine.py`)
- **`monthly_plan`:** scale the written split to the amount, then `pick_slot`. The slot ranks candidates by percentage points below target and fills the top one up to its cap headroom; any remainder goes to the next candidate, then to VOO. Then the guardrails run.
- **`extra_plan`:** "rebalance with new money" for a bonus. It computes each ticker's shortfall versus target *after* adding the cash (capped by headroom) and splits the cash in proportion to those shortfalls.
- **Finalize:** whole dollars, small leftovers folded into VOO, and the rounding residual assigned so the total is exact.

### Step 7: Guardrails that move money (`guardrails.py`)
They run in a fixed order, and each one records an `Adjustment`:
1. **Buy-only:** negatives are clamped.
2. **Caps:** headroom = `cap% × post-buy total − current value`. Excess goes to VOO.
3. **Core ratio:** a closed form for the most QQQM that keeps `VOO ≥ 3× QQQM` *after* the money moves: `q' ≤ (V + v + q − 3Q) / 4`, rounded **down** so rounding can't break the rule. A test caught exactly that $2 rounding bug.
4. **Cushions:** a non-AI buy can't exceed VHT/BRK.B, but a cushion held back by its own cap doesn't set the floor. A test caught BRK.B's cap starving the gold buy.

`check_portfolio` reports the status of each rule for `/guardrails`, for example: "VOO is 1.3× QQQM; QQQM buys go to VOO until about $15k more VOO is added".

### Step 8: Behavioural features (`insights.py`)
- **Goal projection:** months to $155k at 4/7/10% (labelled as assumptions).
- **Drawdown alerts:** measured on *unrealized gain*, so new deposits don't hide losses and a pause in deposits doesn't look like one. They fire once per level per peak.
- **Stress test:** shocks by bucket and AI tag (an AI sell-off hits NVDA harder than VHT). It turns "-30%" into "your $2k buys ~40% more shares".
- **Talking point:** "The biggest risk to this plan is me selling in a drop. So 'should I sell?' never gets a sell signal. It gets the stress test and the reason the plan says hold."

### Step 9: Two-tier natural language
- **Tier 1, `intents.py`:** regex/keyword parsing for "bought 400 of nvda", "bought 2 sh brk.b @ 570", "got a 5k bonus" and "should I sell". It's free, instant, deterministic and testable.
- **Tier 2, `llm.py`:** a tool-calling loop (max 4 rounds) for everything else.
  - Tools: `get_portfolio`, `get_monthly_plan`, `get_extra_cash_plan`, `check_guardrails`, `project_goal`, `stress_test`, `propose_buy`.
  - The system prompt says to get every number from a tool and never recommend selling.
  - `propose_buy` writes nothing. The bot shows a confirm button.
- **Talking point:** "Cheapest reliable path first, LLM only as the fallback. That's how you keep cost, latency and hallucination risk down."

### Step 10: Telegram UX (`bot.py`)
- Long polling, so there's no public URL to host.
- **Auth:** only `TELEGRAM_CHAT_ID` is served. `/start` tells a new user their chat id.
- Persistent reply keyboard (📋 Plan, 💼 Portfolio…), inline ✅/⏭ buttons, CSV/YAML upload for import, `/undo` everywhere.
- **Jobs (JobQueue):** monthly payday plan, a weekday after-close drawdown check, a Sunday digest.
- Blocking work (SQLite, yfinance) runs in `asyncio.to_thread` behind a lock, so the event loop never stalls.

### Step 11: Testing (77 tests, no network)
- Engine and guardrail invariants: the total is exact, every amount is positive, no capped ticker ends above its cap at $2k/$6k/$20k, VOO ≥ 3× QQQM after the buy, and the cushions stay largest.
- Ledger: undo, undo of an import, average-cost sells, no overselling, idempotent execution.
- Parser cases, a Fidelity CSV with multiple accounts and cash rows, goal math.
- Bot handlers driven with fake Update objects: stranger rejected, plan → ✅ → no double record, sell confirmation, document import.
- The LLM loop with a **scripted fake model**: tool results reach the model, and `propose_buy` does not write.
- **Talking point:** "You can test an agent without calling a model: script the model's turns and assert on the tool calls and side effects."

### Step 12: Shipping for $0
- Docker + compose with a data volume, for an always-free VM or a Pi.
- `pda send-plan` for cron if nothing is always on.
- CI on GitHub Actions (ruff + validate + pytest on 3.11/3.12).
- Secrets live in `.env`. Personal holdings are in a gitignored file or the DB.

---

## 4. Design decisions and trade-offs

| Decision | Why | Trade-off / alternative |
|---|---|---|
| Deterministic engine, LLM only explains | Money must be reproducible and testable; LLMs hallucinate numbers | Less "magic"; the LLM can't come up with new strategies (on purpose) |
| Dropped LangGraph | The flow is a linear pipeline plus a tool loop; the graph added dependencies but no new behaviour | For multi-agent or long-running workflows I'd bring it back |
| OpenAI-compatible HTTP instead of a vendor SDK | One client works for Groq/Gemini/Ollama/OpenRouter, and it's free | Some vendor-specific features are lost |
| Append-only ledger | Undo, audit, idempotency, safe imports | Replays on every read (trivial at this size; could cache) |
| Caps on the *post-buy* portfolio | Matches the rule as stated ("no stock above 5%") | Slightly more math than a per-budget cap |
| Broker import replaces the ledger | The broker is the source of truth and fixes drift from manual entry | Loses lot-level detail (average cost only) |
| Long polling | No domain, TLS or public endpoint; works from home | Needs an always-on process |
| SQLite | No server, a single file, backed up by copying | Single writer (fine for one user) |

## 5. AI-specific talking points

- **Grounding:** every number in an LLM answer comes from a tool result produced by the tested engine.
- **Human-in-the-loop for writes:** the model can only propose; a button commits. That's the main defence against hallucination *and* prompt injection.
- **Minimal privilege:** the tools can't sell, change config or delete data.
- **Graceful degradation:** no key or provider down → the rule-based parser and commands keep working.
- **Cost:** about $0. Free tiers are enough because most messages never reach the LLM (tier 1 handles them).
- **Evaluation:** a scripted-LLM unit test for the tool loop. Next step: a small golden set of questions with expected tool calls, scored per model to choose a provider.
- **Safety framing:** a personal planning tool, not advice. The system prompt refuses timing and sell calls and redirects to the plan's rules.

## 6. Likely questions, with short answers

**Why not let the LLM pick the stock-slot ticker?**
It's a ranking by distance below target. A one-line `sorted()` is correct every time; an LLM is right most of the time and costs money.

**How do you stop it recommending a sell?**
In three places. The engine can't output one. `apply_guardrails` clamps negatives. The system prompt forbids it. And the "sell" intent is caught before the LLM runs and answered with the stress test.

**What happens if Yahoo is down or a ticker is new (SPCX)?**
Batch download, then a per-ticker retry. If there's still nothing, the position is valued at cost and flagged ⚠️, the slot skips it with a note, and nothing crashes.

**How would this scale to many users?**
Per-user strategy and ledger rows (`user_id` column), Postgres, webhooks behind a small FastAPI service, a queue for the scheduled jobs, and encrypted storage for broker data. The engine stays unchanged because it's pure.

**What was the hardest bug?**
Interactions between guardrails. A capped BRK.B lowered the cushion floor and starved the gold buy, and rounding put VOO $2 under 3× QQQM. Property-style tests over several amounts found both.

**Why drop v1's dip-buying tranches?**
They were a market-timing strategy that conflicted with the written plan (a fixed split, rebalancing with new money). Fewer moving parts also means fewer ways to talk myself out of buying.

## 7. What I'd build next
1. Read-only brokerage sync (e.g. through an aggregator) instead of CSV import.
2. Look-through exposure: count NVDA inside VOO/QQQM/SMH for a true "AI exposure" number.
3. A golden-set evaluation harness for LLM providers (accuracy of tool selection, latency, cost).
4. Tax-lot tracking and an annual contribution summary.
5. Per-user multi-tenancy (see the scaling answer).

## 8. Live demo script (3 minutes)
1. `pda --offline plan`: show the guardrail note ("VOO 1.3× QQQM → $100 to VOO") and the stock slot reason.
2. `pda --offline guardrails`: NVDA/GOOGL over cap → "no new buys; don't sell".
3. `pda --offline extra 5000`: gap fill goes to VHT/BRK.B first.
4. In Telegram: tap 📋 Plan → ✅ → `/history` → `/undo`.
5. Type "should I sell?" → stress test instead of a sell signal.
6. `pytest -q`: 77 green.

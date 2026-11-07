# How it works, and how it was built

A walkthrough you can read **without running anything**: the problem, the architecture, each build step with the reasoning behind it, and what the user sees at each stage.

---

## The problem, in one paragraph

Long-term investing is simple on paper: pick target weights, invest every month, don't sell in a crash. In practice people skip months, don't know how to split *this* month's money, let one hot stock grow to 15% of the portfolio, and sell at the bottom. The goal was a tool that turns **a written plan into a monthly habit**. It works for anyone's plan (any amount, tickers, currency or goal), costs $0, and never lets an AI make money decisions.

## Design principles (decided before writing code)

1. **The rules decide, the AI explains.** Buy amounts come from pure, tested functions. The LLM can read results and *propose* a record, never write one.
2. **Buy-only.** There is no code path that outputs a sell. Rebalancing happens only with new money.
3. **Explain every number.** Each guardrail that changes the plan leaves a one-line, human-readable reason.
4. **Works with zero keys.** No AI key → a rule-based parser. No Telegram → the full CLI. No internet → demo prices.
5. **Universal and private.** Any Yahoo ticker and any currency; self-hosted, so holdings never leave your machine.

---

## Architecture

```
          ┌──────────── interfaces ────────────┐
Telegram ─┤ bot.py   (auth, commands, buttons, │
          │           files, scheduled jobs)   │
CLI ──────┤ __main__.py (pda …)                │
Dashboard ┤ dashboard/app.py                   │
          └──────────────┬─────────────────────┘
                         │   natural language → intents.py (rules) → optional llm.py (tools)
                         ▼
                   service.py  ← one facade, so every interface shows the same numbers
        ┌────────────┬───┴────────┬──────────────┬─────────────┐
   config.py     engine.py    ledger.py      prices.py    insights.py
 (validated   (auto / fixed / (append-only  (Yahoo, demo; (goal, drawdown,
  strategy)    slot / gap-fill) SQLite)      intl symbols)  stress test)
                    │
              guardrails.py (buy-only → caps → core ratio → cushions)
```

---

## Build steps

### Step 1: Review the first version honestly
v1 was a LangGraph pipeline that sent a daily Telegram push. A full read-through found that it *looked* agentic but didn't behave correctly:
- **State reset on every run.** It ran on GitHub Actions with a SQLite file, so the database was thrown away each time and the same "tranche" was re-sent every weekday.
- **A cosmetic "reflection" loop.** It re-ran identical deterministic math, so a revision could never change anything.
- **Caps on the wrong number.** Position caps were measured against the *monthly budget*, not the portfolio.
- **Hard-coded and stale holdings.** Holdings were hand-edited YAML that went stale; the plan itself was hard-coded to one person.
- **Repo problems.** A committed virtualenv (16k files), the database and personal positions were all in a public repo.

**Lesson:** judge an "agent" by whether each step can change the outcome.

### Step 2: Make the plan a validated config (`config.py`)
- One YAML file describes any plan: `goal`, `monthly`, `targets`, optional `guardrails` and `alerts`. The smallest valid plan is three lines.
- **Two modes:**
  - `auto`: new money fills the biggest gaps.
  - `fixed`: a written dollar split plus an optional "stock slot".
- **Strict validation, with plain-English errors.** It checks that:
  - targets add up to exactly 100%,
  - a fixed split adds up to the monthly amount,
  - no target is above its own cap,
  - every guardrail references a real ticker,
  - in fixed mode, the split already keeps the cushions as the largest defensive buys.
- **Ticker normalization** that works internationally: `brk/b` → `BRK.B`, while `RELIANCE.NS`, `VOD.L` and `BTC-USD` are left as they are.

*Example it caught in a real plan:* "BRK.B target 7% is above its cap 5%". The plan's own rules contradicted each other, and the fix (a per-ticker cap) is now explicit instead of the code silently choosing one.

### Step 3: A small domain model (`models.py`)
These are plain dataclasses: `Position`, `Snapshot`, `Plan`, `BuyLine`, `Adjustment`, `RuleCheck`. The important one is **`Adjustment`**: every guardrail decision is recorded as structured data with a message. That makes the system explainable to the user, to the AI, and in tests.

### Step 4: The ledger is the source of truth (`ledger.py`)
- **Holdings are calculated, not stored.** Every buy, sell or import is a row in an append-only `transactions` table, and holdings come from replaying those rows. Sells reduce the cost basis at average cost.
- **Each write is a batch**, so `/undo` removes exactly the last action.
- **An import never deletes history.** A broker import *voids* the old rows rather than deleting them, so an import can be undone too.
- **Plans have a status** (`proposed` / `executed` / `skipped`). That makes the ✅ button safe to tap twice, and lets the payday reminder skip a month that's already recorded.
- The ledger also stores daily snapshots (for drawdowns), alerts already sent (so nothing repeats), and settings changed from chat (`/set monthly 3000`).

### Step 5: Prices behind an interface (`prices.py`)
- `PriceProvider` is a two-line protocol with two implementations:
  - `YahooPrices`: free with no key, batched, cached for 10 minutes.
  - `StaticPrices`: fixed prices for tests and the demo.
- **International symbols.** A one-letter suffix is ambiguous on Yahoo (`BRK.B` is `BRK-B`, but `VOD.L` is `VOD.L`), so the dash form is tried first and the literal ticker is retried in a second batch.
- A missing price never crashes anything: the position is valued at cost and flagged, and a buy that needs a price is skipped with a note.

### Step 6: The engine (`engine.py`)
- **`gap_fill` (auto mode and `/extra`):**
  - For each ticker: *shortfall = target% × (portfolio + new money) − current value*, capped by its headroom.
  - The money is split in proportion to those shortfalls. Anything left over once every gap is closed is spread by target weight.
  - Result: an empty portfolio simply follows the targets ($500 → VTI $300, VXUS $150, BND $50), while a lopsided one sends everything to the laggard.
- **Fixed mode:** the written split is scaled to the amount, then **`pick_slot`** ranks the candidates by percentage points below target and fills the top one up to its cap; any remainder goes to the next candidate.
- **`_finalize`:** whole amounts, tiny orders folded into the core fund, and the rounding residual assigned so the total exactly equals what you invest.

### Step 7: Guardrails that move money (`guardrails.py`)
Applied in order, each recording an `Adjustment`:

| # | Rule | Mechanism |
|---|---|---|
| 1 | Buy-only | Negative amounts are clamped to 0 |
| 2 | Position caps | headroom = cap% × **post-buy** total − current value, **rounded down**; the excess goes to the overflow fund |
| 3 | Core ratio (A ≥ m × B) | Closed form for the largest B buy that keeps the rule *after* the money moves: `b' ≤ (A + a + b − m·B) / (1 + m)`, rounded down |
| 4 | Cushions | No non-theme buy may exceed the defensive funds. A cushion held back by its *own* cap doesn't set the floor |

There are two bugs the tests caught here, which make good interview stories:
- **Rounding:** an allowed $37.50 rounded up to $38 and broke the 3× rule by $2. Fix: round limits down.
- **Interacting rules:** a capped cushion lowered the floor and starved the gold buy. Fix: capped cushions are excluded from the floor.

`check_portfolio` reports each configured rule as ✅/⚠️ with numbers, for example: *"VOO is only 1.3x QQQM (need 3x). QQQM buys go to VOO until about $15,504 more VOO is added."*

### Step 8: Behavioural features (`insights.py`)
- **Goal projection:** months to the goal at 4/7/10%/yr, with the dates. It's clearly labelled as an assumption.
- **Drawdown:** measured on *unrealized gain* rather than raw value, so a new deposit can't hide a loss and a skipped month can't fake one. The alert fires **once per level per peak**.
- **Stress test:** each position is shocked by its bucket (themed stocks harder, gold up). The message turns "-27%" into "your next $2,000 buys ~40% more shares".
- **"Should I sell?"** never reaches a sell path; it's answered with the stress test and the plan's rule.

### Step 9: Language in two tiers
- **`intents.py` (free, instant, deterministic):** regex and keyword parsing for "bought 400 of nvda", "bought 2 sh brk.b @ 570", "got a 5k bonus", "plan 3000", "should I sell", plus the keyboard buttons.
- **`llm.py` (optional):** an OpenAI-compatible tool-calling loop (up to 4 rounds) that works with Groq or Gemini (free tiers) or local Ollama.
  - The system prompt is **generated from the user's own strategy**: their amount, goal and rules.
  - Tools: `get_portfolio`, `get_monthly_plan`, `get_extra_cash_plan`, `check_guardrails`, `project_goal`, `stress_test`, `propose_buy`.
  - Only `propose_buy` relates to writing, and it **doesn't write**: the bot shows a ✅ Record / Cancel button.

### Step 10: The Telegram experience (`bot.py`)
- **Long polling**, so there's no server, domain or TLS to set up.
- **Locked to one chat id.** For anyone else, `/start` replies with their own chat id and setup instructions.
- **Controls:** a persistent keyboard (📋 Plan, 💼 Portfolio, 🎯 Drift, 🛡 Guardrails, 🏁 Goal, ⚙️ Settings), inline ✅/⏭ buttons, CSV/YAML upload, and `/set` for settings.
- **Scheduled jobs:** the payday plan, a weekday after-close drawdown check and a Sunday digest. Changing the reminder day with `/set day 15` reschedules immediately.
- Slow work (SQLite, Yahoo) runs in a thread behind a lock, so the bot never freezes.

### Step 11: Onboarding for anyone (`onboarding.py`)
- **`pda init`:** six questions plus a preset or custom tickers. Weights that don't add up are scaled to 100%, a fixed split is rescaled to your amount, the result is validated, and then `strategy.yaml` is written.
- **`pda demo`:** a full tour on an example plan with demo prices. No accounts, keys or network needed.
- **`pda doctor`:** checks the plan, ledger, live prices, Telegram token (including a live `getMe` call), chat id and AI, and prints the exact fix for each problem.
- **`scripts/setup.sh` / `setup.ps1`:** install, demo, wizard and doctor in one command.

### Step 12: Tests and shipping
- **121 offline tests**, about 3 seconds. They cover money invariants at several amounts, each guardrail and how they interact, both modes, every preset, the wizard (scripted answers), the ledger and undo, CSVs from several brokers, Telegram handlers (fake updates), and the AI loop (a **scripted fake model**: it proves `propose_buy` doesn't write).
- **CI:** ruff, validating every preset, `pda demo`, and pytest on Python 3.11 and 3.12.
- **Deployment:** Docker and compose with a data volume, for a Raspberry Pi or an always-free VM. `pda send-plan` covers cron-only setups.

---

## What a new user experiences

| Minute | They do | They see |
|---|---|---|
| 0 | `bash scripts/setup.sh` | Install, then a demo buy list with reasons and guardrails |
| 1 | Answer the wizard | "✅ Saved config/strategy.yaml" |
| 2 | `pda plan` | Their own buy list with live prices |
| 4 | Create a bot with @BotFather, paste the token, `pda bot`, `/start` | Their chat id; after a restart the bot is locked to them |
| 5 | Send their broker CSV | "📥 Imported 17 positions. Portfolio: $42,491" |
| Every payday | Tap ✅ after buying | "📝 Bought, ledger updated" |
| In a crash | Nothing | One "🧘 Hold the line" message with the numbers and the plan's rule |

## Trade-offs, stated honestly
| Choice | Benefit | Cost |
|---|---|---|
| Deterministic engine | Correct, testable, explainable | No "creative" AI strategies (by design) |
| No automatic trading | No credentials, no runaway risk | The user places orders by hand |
| Self-hosted, one user per bot | Privacy, $0 | Each user runs their own copy |
| SQLite + replaying the ledger | Undo, audit trail, safe imports | Single writer (fine for one user) |
| Long polling | No infrastructure | Needs an always-on process |
| Yahoo Finance | Free and global | Unofficial and sometimes delayed |

# Interview Guide: presenting Portfolio Deploy Agent

Use this to present the project **without running it**. The step-by-step build story is in [HOW_IT_WORKS.md](HOW_IT_WORKS.md); this page gives you the talk track.

---

## 1. The 30-second pitch

> "I built an open-source Telegram co-pilot for long-term investors. You tell it your monthly amount, the stocks and ETFs you want with target percentages, and your money goal. A one-minute setup wizard does that, or you write a three-line YAML file. Every payday it sends exactly what to buy and why, enforces rules like 'no single stock above 5%', keeps your holdings in sync with one tap, and when the market drops it sends the numbers and the plan instead of a sell signal.
>
> The key design decision is that **the rules decide and the AI explains**. Every dollar comes from deterministic, unit-tested code. An optional LLM answers plain-English questions through tools, but it can only *propose* a write, and the user confirms it with a button. It costs nothing to run, works with any broker, currency or Yahoo ticker, and has 121 tests."

## 2. The 2-minute version

1. **Problem.** Investors don't fail by picking the wrong ETF. They fail by skipping months, drifting into concentration and panic-selling. I wanted a tool that turns a written plan into a habit.
2. **What it does.**
   - **Any plan:** auto mode (new money fills the biggest gaps) or a fixed split with a "stock slot".
   - **Guardrails that move money and explain why:** caps, a core ratio, cushion funds, buy-only.
   - **One-tap tracking**, plus an extra-cash planner, goal projections, stress tests and drawdown alerts.
3. **How it's built.**
   - A validated YAML strategy, a pure-function engine, and an append-only SQLite ledger (undo and an audit trail for free).
   - One service facade shared by the Telegram bot, the CLI, the dashboard and the AI tools.
4. **AI layer.**
   - Two-tier language handling: a free regex/keyword parser first, then an optional OpenAI-compatible tool-calling agent (Groq/Gemini/Ollama).
   - Its system prompt is generated from the user's own plan.
   - Tools are read-only; the one write tool needs a human tap.
5. **Result.** Setup in under five minutes, $0 to run, 121 offline tests with CI, Docker for a free VM. It started as my personal bot and I generalized it for anyone.

## 3. Walk through it without running it (5 slides or a screen share of the README)

| Show | Say |
|---|---|
| README §2 payday message | "Each line has a reason. Here a guardrail moved $100 from QQQM to VOO because VOO must stay ≥ 3× QQQM, and the stock slot went to the stock furthest below target." |
| The three-line minimal plan (README §5) | "That's all a beginner needs. Validation catches mistakes in plain English." |
| The wizard transcript (README §5) | "A non-technical user answers six questions; €, a German ETF and a stock cap all work." |
| The architecture diagram (README §9) | "Every interface goes through one service, so Telegram, the CLI and the AI can never disagree." |
| The guardrail table (HOW_IT_WORKS step 7) | "Rules are applied in order, and each leaves an explanation. The core-ratio rule is a closed-form inequality, rounded *down* so rounding can't break it." |
| The AI section (HOW_IT_WORKS step 9) | "Cheapest reliable path first. The LLM never sees a write tool it can execute on its own." |
| The test list (README §11) | "I test the agent loop with a scripted fake model, so no API calls are needed to prove it can't write." |

## 4. Design decisions to bring up

| Decision | Why | Trade-off |
|---|---|---|
| The rules decide, the AI explains | Money must be reproducible; LLMs invent numbers | Less "magic", by design |
| Dropped LangGraph from v1 | A linear flow plus a tool loop; the graph added dependencies but no behaviour | I'd bring it back for multi-agent or long-running workflows |
| OpenAI-compatible HTTP, not a vendor SDK | One client for Groq/Gemini/Ollama/OpenRouter; free tiers | Fewer vendor-specific features |
| Append-only ledger | Undo, audit trail, idempotent ✅, undoable imports | Replays on read (trivial at this scale) |
| Caps measured on the *post-buy* portfolio | Matches how people say the rule | Slightly more math |
| Self-hosted, one bot per user | Privacy, $0, no data liability | Not multi-tenant (yet) |
| No automatic trading | No credentials, no runaway risk | The user places orders by hand |
| Long polling | No domain, TLS or public endpoint | Needs an always-on process |

## 5. AI-specific talking points
- **Grounding:** every number the LLM mentions comes from a tool result produced by the tested engine.
- **Human in the loop for writes:** `propose_buy` returns "pending confirmation", and a Telegram button commits it. This is the main defence against both hallucination and prompt injection.
- **Least privilege:** no tool can sell, edit the config or delete data.
- **Personalized prompt:** the system prompt is built from the user's strategy (their amount, goal and guardrails). There's nothing hard-coded.
- **Graceful degradation:** with no key or with the provider down, the rule-based parser and commands still work.
- **Cost:** about $0. Most messages never reach the LLM.
- **Testing agents:** a scripted fake model checks tool routing and side effects. Next step: a small golden set of questions to compare providers on tool-selection accuracy, latency and cost.

## 6. Likely questions, with short answers

**Why not let the LLM pick what to buy?**
Picking means ranking by distance below target under caps. A deterministic function gets it right every time; an LLM gets it right most of the time and costs money.

**How do you guarantee it never says "sell"?**
In three places. The engine has no sell output. Guardrails clamp negatives. The "sell" intent is caught *before* the LLM and answered with the stress test. And the system prompt forbids it.

**How did you make it work for anyone?**
Every rule is optional config. There's an auto mode so a plan can be just targets, a wizard with presets, international tickers and currencies, and a `doctor` command that explains how to fix each setup problem.

**What was the hardest bug?**
Interactions between guardrails. A capped cushion lowered the floor and starved the gold buy, and rounding put VOO $2 under 3× QQQM. Invariant tests over several amounts caught both.

**How would you scale it to a hosted multi-user product?**
Per-user strategy and ledger rows, Postgres, Telegram webhooks behind FastAPI, a job queue for schedules, and encrypted storage. The engine doesn't change; it's pure.

**What if Yahoo has no price for a ticker?**
A batched download, then a retry with the alternate symbol form. If there's still nothing, the position is valued at cost and flagged ⚠️, the buy is skipped with a note, and `pda doctor` names the ticker.

**What would you add next?**
Read-only brokerage sync, look-through exposure (NVDA inside VOO/QQQM/SMH), tax lots, and a provider evaluation harness.

## 7. If you can run it (3-minute live demo)
1. `pda demo`: the payday list, guardrails, goal, extra cash and stress test.
2. `pda --offline --strategy examples/three_fund.yaml plan`: the simplest auto plan.
3. In Telegram: 📋 Plan → ✅ → `/history` → `/undo` → `/set monthly 3000` → "should I sell?"
4. `pytest -q`: 121 green.

# Interview Guide: presenting Portfolio Deploy Agent

Use this to present the project **without running it**. The step-by-step build story is in [HOW_IT_WORKS.md](HOW_IT_WORKS.md); this page gives you the talk track. Interviewing for a data engineering role? Section 8 reframes the project in data engineering terms.

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
5. **Result.** Setup in under five minutes, $0 to run, 121 offline tests with CI, Docker for a free VM. It started as my personal bot and I generalized it for anyone. My own plan still runs on it, but it lives in gitignored config: the public repo ships only made-up examples.

## 3. Walk through it without running it (5 slides or a screen share of the README)

| Show | Say |
|---|---|
| README §2 payday message | "Each line has a reason. Here a guardrail moved $75 from QQQ to VTI because VTI must stay ≥ 3× QQQ, and the stock slot went to the stock furthest below target." |
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
Interactions between guardrails. A capped cushion lowered the floor and starved the gold buy, and rounding put the core fund $2 under its 3× rule. Invariant tests over several amounts caught both.

**How would you scale it to a hosted multi-user product?**
Per-user strategy and ledger rows, Postgres, Telegram webhooks behind FastAPI, a job queue for schedules, and encrypted storage. The engine doesn't change; it's pure.

**What if Yahoo has no price for a ticker?**
A batched download, then a retry with the alternate symbol form. If there's still nothing, the position is valued at cost and flagged ⚠️, the buy is skipped with a note, and `pda doctor` names the ticker.

**What would you add next?**
Read-only brokerage sync, look-through exposure (e.g. NVDA inside VTI/QQQ), tax lots, and a provider evaluation harness.

## 7. If you can run it (3-minute live demo)
1. `pda demo`: the payday list, guardrails, goal, extra cash and stress test.
2. `pda --offline --strategy examples/three_fund.yaml plan`: the simplest auto plan.
3. In Telegram: 📋 Plan → ✅ → `/history` → `/undo` → `/set monthly 3000` → "should I sell?"
4. `pytest -q`: 121 green.

---

## 8. The data engineering angle

For a data engineering panel, present the project as **a small, complete data system**: it ingests messy sources, keeps one reliable record of truth, derives everything else from that record, checks data quality, runs on a schedule, and adds an AI layer that can't corrupt the data. Lead with the data model and correctness, then introduce the AI layer as the safe use of that data.

### 30-second pitch (data engineering version)

> "I built an open-source portfolio system that ingests broker exports and market prices from Yahoo. It stores every transaction in an append-only ledger and derives holdings from it, so I get an audit trail, undo and reproducible results. A deterministic rules engine turns that data into a monthly plan, and a scheduler sends it on Telegram. On top of that there's an LLM layer that answers plain-English questions using tools over the tested data. It can only propose a change, and a person has to confirm it. About 3,200 lines of Python, 121 offline tests, CI and Docker, and it costs $0 to run."

### What you built, in data engineering terms

| What's in the code | Data engineering term | What to say |
|---|---|---|
| `ledger.py`: transactions with `voided_by` and `batch`; holdings computed from them | **Event sourcing / append-only log**, soft deletes | "I never update rows in place. State is replayed from events, like a CDC log or a Delta table's history. An import voids old rows instead of deleting them, so even a bad import can be undone." |
| A `batch` id on every write; plan status only moves proposed → executed | **Idempotency keys** | "Tapping ✅ twice can't record a purchase twice. Undo reverses a whole batch atomically." |
| SQL `CHECK` constraints (`shares > 0`, `kind IN (...)`) | **Schema enforcement at the storage layer** | "Bad data is rejected at write time, not discovered later in a report." |
| Strategy validation plus `pda doctor` | **Data contracts / data quality checks** | "Config is validated against a schema and errors come back in plain English. Doctor works like a pre-flight data quality check." |
| `prices.py`: one batched download, retry with an alternate symbol, fall back to cost and flag ⚠️ | **Resilient ingestion, graceful degradation** | "A missing upstream price never crashes the pipeline. The row is flagged and the problem is visible to the user." |
| The `snapshots` table (one row per day: value, cost) | **Daily fact table / time series** | "Daily snapshots give me drawdown detection and history without recomputing it." |
| `importers.py`: broker CSV import; combining a month-end statement with later trade confirmations | **Ingesting from multiple sources and reconciling them** | "A statement gives a full snapshot as of one date, and trade confirmations add the changes since then. It's the same pattern as full load plus incremental load." |
| `service.py`, the one layer behind the bot, CLI, dashboard and AI tools | **Single source of truth / semantic layer** | "Four interfaces, one set of logic, so the numbers can never disagree between them." |
| JobQueue for monthly reminders and drawdown alerts | **Orchestration / scheduling** | "In-process scheduling is enough for one user. At scale it moves to Airflow or Dagster." |
| Offline tests with fixture prices; CI with ruff and pytest | **Deterministic pipeline testing** | "Tests never hit the network, so CI is fast and never flaky. I check invariants across many amounts, not just single examples." |
| Real plan, holdings, ledger and `.env` are gitignored; only examples ship | **Data privacy / secrets management** | "Personal data and keys never reach the repo. Configuration is separate from code." |

### Data engineering questions, with short answers

**Why append-only instead of updating holdings?**
Auditability, undo and reproducibility: current state is a function of the events. The cost is replaying on read, which is trivial at this size. At scale I'd keep materialized snapshots and refresh them incrementally.

**How would you scale this to 100k users?**
- **Storage:** Postgres with tables keyed by user, partitioned by user or date.
- **Bot traffic:** Telegram webhooks behind FastAPI instead of long polling.
- **Async work:** a queue (SQS or Kafka) for price updates and notifications.
- **Scheduled jobs:** Airflow or Dagster for the daily price load and snapshots.
- **Prices:** fetched once per ticker and shared across all users, not fetched per user.
- **Analytics:** a warehouse modeled with dbt in bronze/silver/gold layers: raw transactions, then cleaned positions, then portfolio metrics.
- **The engine doesn't change,** because it's a pure function.

**How do you handle late or incorrect data, like a broker correction?**
Void the affected batch and re-import. Because rows are voided rather than deleted, the history shows what changed. In a warehouse that becomes a MERGE/upsert, with the history kept as a slowly changing dimension.

**How do you guarantee idempotency?**
Every write carries a batch id, a plan's status only moves forward, and confirming twice is a no-op.

**How do you monitor data quality?**
Schema validation on config, `CHECK` constraints in the database, and missing prices flagged instead of hidden. At scale I'd add freshness checks, row-count checks and null checks with dbt tests or Great Expectations.

**Batch or streaming?**
Batch: monthly plans and daily snapshots don't need real-time data. Streaming only pays off for intraday alerts, and even then a micro-batch every few minutes is usually enough. Choose based on the latency the business actually needs.

**Why SQLite?**
One user, no server, a single file, and full SQL with transactions. I'd move to Postgres for concurrent users; the schema carries over almost unchanged.

### General AI questions a data engineer may get

**RAG or fine-tuning?**
RAG or tools when the facts change or must be traceable to a source. Fine-tuning for style, format or a narrow task. Most business cases need retrieval, not fine-tuning.

**How do you reduce hallucinations?**
Base answers on retrieved data, use tools for any number, ask for structured output validated against a schema, keep temperature low, have a person approve actions, and run evals on a golden set.

**What does a data engineer do on an AI project?**
- Provide clean, fresh, documented source data.
- Build chunking and embedding pipelines for RAG, and keep the vector index in sync with the source systems.
- Track lineage and control access to personal data.
- Log prompts, responses and cost so the feature can be monitored.

Model quality is limited by data quality.

**How do you evaluate an LLM feature?**
Keep a labelled set of real questions. Measure tool and answer accuracy, latency, cost per request and the refusal rate. Rerun it on every prompt or model change, like regression tests.

**Prompt injection?**
Treat model output as untrusted. Give tools least privilege, never let the model execute a write directly, and keep system instructions separate from user content. Here the LLM can only propose, and a person confirms.

**Why no vector database?**
The data is structured, so typed tools are the better fit. For unstructured text such as PDF statements or news, I'd add embeddings in pgvector, which keeps everything in Postgres.

### Gaps to admit up front (it builds credibility)
- No Spark or Airflow, because one user's data doesn't need them. The pieces map onto them, though: the engine is pure, the ledger is an event log, and the jobs are separate.
- No RAG or vector store, because the data is structured. I'd add them for parsing PDF statements.
- Next, I'd add read-only brokerage sync, look-through exposure, tax lots and a provider evaluation harness.

### Things to have ready
- The README architecture diagram and the `transactions` schema in `ledger.py`. A schema discussion is a natural way into the data engineering conversation.
- The example plan from the repo, not your real holdings or dollar amounts.

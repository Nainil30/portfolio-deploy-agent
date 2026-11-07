# LinkedIn post drafts

Pick one, add 1–2 screenshots (the payday message from `pda demo`, and the architecture diagram from the README), and put the repo link in the post or the first comment.

---

## Version A: story (recommended)

I built a free Telegram bot that tells me exactly what to invest each month and talks me out of panic-selling. Now anyone can use it with their own plan. 📈

The hard part of long-term investing isn't picking ETFs. It's showing up every month, not letting one hot stock take over, and *not selling when everything is red*.

So I built **Portfolio Deploy Agent**:

🗓 Every payday it sends your buy list, with a reason for each line
🎯 Your plan, your rules: monthly amount, target stocks/ETFs and %, money goal
🛡 Guardrails in code: max % per stock, "VOO ≥ 3× QQQM", defensive funds, never sell
✅ One tap after you buy keeps your holdings in sync (or import your broker's CSV)
🧘 When the market drops 10/20/30%, you get the numbers and the plan, not a sell signal
🌍 Any currency and any Yahoo ticker: US, India (.NS), UK (.L), Canada, crypto

The design choice I'm proudest of: **the rules decide, the AI explains.** Every dollar comes from deterministic, tested code. The optional LLM (free Groq/Gemini, or local Ollama) answers questions through tools and can only *propose* a change; you confirm it with a button.

Under the hood: Python, python-telegram-bot, SQLite (an append-only ledger with undo), an OpenAI-compatible tool-calling agent, 118 tests, CI and Docker. It's $0 to run and self-hosted, so your data stays yours.

Setup takes 5 minutes: `pda init` asks six questions and writes your plan.

👉 Repo: https://github.com/Nainil30/portfolio-deploy-agent

If you try it, tell me what your plan looks like. I'd love to add more presets.

*Not financial advice: it follows the plan you write.*

#Python #AI #LLM #OpenSource #Investing #PersonalFinance #Telegram #BuildInPublic

---

## Version B: short

Built a free, open-source Telegram co-pilot for long-term investors 📈

You set your monthly amount, target stocks/ETFs and money goal → every payday it sends what to buy and why, enforces your guardrails (caps, never sell), tracks holdings with one tap, and keeps you calm in drawdowns.

AI is optional and can't move money on its own: the rules decide, the LLM explains.

Python · Telegram · SQLite · tool-calling LLM · 118 tests · $0 to run
→ https://github.com/Nainil30/portfolio-deploy-agent

#Python #AI #OpenSource #Investing

---

## Version C: technical (for engineering and AI recruiters)

How do you put an LLM in a money workflow without letting it touch the money?

My answer in Portfolio Deploy Agent (an open-source Telegram investing co-pilot):

1️⃣ **Deterministic core.** A pure-function engine builds the monthly buy list from a validated YAML plan. Guardrails (position caps on the post-buy portfolio, a closed-form "A ≥ m×B" ratio, defensive cushions, buy-only) *move* money and record a human-readable reason for each change.
2️⃣ **Two-tier language handling.** A regex/keyword parser handles the common messages for free ("bought 400 of VOO", "got a 5k bonus"). Only the rest goes to an OpenAI-compatible tool-calling agent (Groq/Gemini/Ollama), whose system prompt is generated from the user's own plan.
3️⃣ **Least-privilege tools.** All tools are read-only except `propose_buy`, which only returns "pending". A Telegram button is the only path that writes.
4️⃣ **Event-sourced ledger.** Holdings are replayed from an append-only SQLite log, which gives undo (even of imports), idempotent confirmations and an audit trail.
5️⃣ **Testing the agent without a model.** A scripted fake LLM asserts on tool calls and side effects. 118 offline tests, CI on 3.11/3.12.

Anyone can run it with their own amount, tickers, currency and goal, for $0, self-hosted.

Code + architecture write-up: https://github.com/Nainil30/portfolio-deploy-agent

#AIEngineering #LLM #Agents #Python #SoftwareEngineering #OpenSource

---

## Posting tips
- **Visual:** a screenshot of the payday message is the hook. The Mermaid diagram (GitHub renders it in the README) is the second image.
- **Timing:** Tuesday–Thursday morning in your audience's timezone.
- **First comment:** "Setup is `git clone` → `bash scripts/setup.sh`. Happy to help anyone get their bot running."
- **Reply to every comment in the first hour.** It boosts reach.
- Pin the repo on your GitHub profile, and add the README's CI and tests badges to your LinkedIn Featured section.

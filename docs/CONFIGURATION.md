# Configuration reference: `config/strategy.yaml`

Your plan lives in one YAML file. Create it with `pda init`, or copy a preset from [`examples/`](../examples/). After editing, run:

```bash
pda validate
```

Mistakes are reported in plain English, for example: *"targets add up to 101.00%, must be exactly 100%"*.

The file is gitignored (it's personal). Your holdings are **not** in it; they live in the ledger (`data/pda.db`).

---

## Smallest valid plan

```yaml
goal:    { target_value: 100000 }
monthly: { amount: 500 }
targets: { VTI: 60, VXUS: 30, BND: 10 }
```

That's enough: **auto mode**, buy-only, reminders on the 1st, New York time.

---

## Full reference

### `profile` (optional)
| Field | Default | Meaning |
|---|---|---|
| `name` | `My plan` | Shown in messages and the dashboard |
| `currency` | `$` | Any symbol: `₹`, `€`, `£`, `C$` … (display only; amounts are whatever your broker uses) |

### `goal`
| Field | Default | Meaning |
|---|---|---|
| `target_value` | **required** | The portfolio value you're working toward |
| `expected_annual_return` | `0.07` | Used **only** for projections (as a decimal: 0.07 = 7%). Never used for buy decisions |

### `monthly`
| Field | Default | Meaning |
|---|---|---|
| `amount` | **required** | What you invest each month |
| `mode` | `auto`, or `fixed` if a `split` is given | `auto`: money goes to what's furthest below target. `fixed`: your written split |
| `reminder_day` | `1` | Day of the month (1–28) the bot sends the buy list |
| `reminder_time` | `09:30` | `HH:MM`, in `timezone` |
| `timezone` | `America/New_York` | Any IANA zone: `Europe/London`, `Asia/Kolkata`, `Australia/Sydney` … |
| `min_buy` | `25` | Buys smaller than this are folded into the overflow ticker |
| `split` | none | **fixed mode only.** `{TICKER: amount}`. Together with `stock_slot.amount` it must add up to `amount` |
| `stock_slot.amount` | `0` | **fixed mode only.** A flexible part of the monthly buy |
| `stock_slot.candidates` | `[]` | It goes to whichever candidate is furthest below its target (respecting caps) |

If you invest a different amount than planned (`/plan 3000` or `/set monthly 3000`), a fixed split is **scaled proportionally**.

### `targets`
Your target weight for every ticker. **The weights must add up to exactly 100.**

```yaml
targets:
  VOO:  30                                   # shorthand: just the %
  QQQM: { pct: 10, bucket: core_etf, ai: true }
  NVDA: { pct: 5,  bucket: stock,    ai: true }
  BND:  { pct: 10, bucket: bond }
```

| Field | Default | Meaning |
|---|---|---|
| `pct` | **required** | Target % of the whole portfolio |
| `bucket` | `etf` | `core_etf`, `etf`, `stock`, `bond`, `gold`, `reit`, `crypto` or `cash`. Only `stock` gets the single-stock cap. The bucket also drives the portfolio summary and the stress test |
| `ai` (alias: `theme`) | `false` | Mark positions that are mostly one theme (AI, tech, a sector). Used for the "theme-heavy %" figure, the stress test (themed positions are shocked harder), and the cushion rule |

**Tickers:** use the Yahoo Finance symbol. US: `VOO`, `BRK.B` (or `BRK-B`). India: `RELIANCE.NS`. UK: `VOD.L`. Canada: `SHOP.TO`. Germany: `VWCE.DE`. Crypto: `BTC-USD`. Run `pda doctor` to confirm every ticker returns a price. If a symbol needs a different Yahoo name, add it under `yahoo_aliases` (`MYTICKER: YAHOO-SYMBOL`).

Tickers you own but don't list here are tracked and valued, but never bought.

### `guardrails` (all optional except never-sell)
| Field | Default | Meaning |
|---|---|---|
| `never_sell` | `true` | The plan never outputs a sell. (`/sold` exists only to keep your records accurate, and asks you to confirm) |
| `max_single_stock_pct` | `10` | No `bucket: stock` position may pass this % of the **post-buy** portfolio. Set `null` for no cap |
| `per_ticker_caps` | `{}` | Overrides for specific tickers, e.g. `{DELL: 3}` for your employer's stock, `{BRK.B: 7}` for a diversified holding company |
| `core_ratio` | none | `{ticker: VOO, versus: QQQM, min_multiple: 3}` keeps VOO ≥ 3× QQQM after every buy; any excess QQQM money moves to VOO |
| `cushions` | `[]` | Defensive funds (e.g. `[VHT, BRK.B]`) that must stay the biggest non-theme buys |
| `overflow_ticker` | the largest target | Receives money that a guardrail frees up. It's never capped, so pick a broad fund |

**Order applied:** buy-only → caps → core ratio → cushions. Every adjustment is explained in the message.

**Startup checks** catch contradictions: a target above its own cap, a fixed split where a non-cushion buy is bigger than the cushions, or a guardrail that names a ticker that isn't in `targets`.

### `alerts` (optional)
| Field | Default | Meaning |
|---|---|---|
| `daily_check_time` | `16:30` | Weekday check after the market closes (in `timezone`) |
| `drawdown_levels_pct` | `[10, 20, 30]` | You get one calm "hold the line" message the first time each level is crossed after a new peak |
| `weekly_digest` | `true` | A Sunday summary, with a nudge if this month's buys aren't recorded |

---

## Changing things later
| Change | How |
|---|---|
| Monthly amount, goal, reminder day, assumed return | From chat: `/set monthly 3000`, `/set goal 250k`, `/set day 15`, `/set return 6`. Or the CLI: `pda set monthly 3000`. Stored in the ledger; `/set reset` reverts to the file |
| Tickers, weights, guardrails | Edit `config/strategy.yaml` → `pda validate` → restart `pda bot`. Or rerun `pda init` |
| Holdings | Send a broker CSV to the bot, `pda import FILE`, `/bought`, or `/undo` |

## Environment (`.env`)
| Variable | Needed for |
|---|---|
| `TELEGRAM_BOT_TOKEN` | The bot (from @BotFather) |
| `TELEGRAM_CHAT_ID` | Locking the bot to your chat and turning on scheduled messages |
| `LLM_PROVIDER` | `groq` (default), `gemini`, `openrouter`, `ollama` or `none` |
| `GROQ_API_KEY` / `GEMINI_API_KEY` / `OPENROUTER_API_KEY` | The optional AI assistant |
| `LLM_MODEL`, `LLM_BASE_URL` | Any OpenAI-compatible model or endpoint |
| `PDA_DB`, `PDA_STRATEGY`, `PDA_HOME` | Custom file locations (Docker sets these) |

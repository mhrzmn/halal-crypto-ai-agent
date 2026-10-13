# Halal Crypto AI Spot Trading Agent (Process Over Profit)

> **A Shariah-compliant, quantitative AI spot swing-trading engine for Binance.**
> Built on the **"Process Over Profit"** philosophy: strict capital preservation, zero interest (*Riba*), zero gambling (*Maysir*), zero short-selling (*Bay' ma la tamlik*), and 100% unleveraged spot asset ownership (*Qabd*).

---

## 1. Fiqh & Shariah Analysis: Why Kalshi Cannot Be Traded the Halal Way

The tutorial you referenced from Process Over Profit (`video-15-kalshi-ai-trading-bot`) automates 15-minute event contracts on **Kalshi**.

Under Islamic Commercial Jurisprudence (*Fiqh al-Mu'amalat*) and standards set by major Shariah bodies (AAOIFI, Islamic Fiqh Academy), **Kalshi's contracts are impermissible (Haram)** due to fundamental structural reasons that cannot simply be "patched" in software:

| Dimension | Kalshi Event Contracts | Binance Spot (This Project) |
| :--- | :--- | :--- |
| **Contract Nature** | **Binary Option / Wager**: Pays \$1.00 or \$0.00 based on an external event. | **Spot Exchange (*Bay' al-Sarf / Bay' al-Sila'*)**: Genuine asset purchase. |
| **Maysir (Gambling)** | **Severe Maysir / Qimar**: Zero-sum bet where one trader's gain is directly another trader's loss with no underlying value created. | **No Maysir**: You purchase a legitimate technological utility asset. |
| **Milkiyyah & Qabd (Ownership & Possession)** | **No Asset Ownership**: You do not receive or hold any cryptocurrency. | **Full Constructive Custody (*Qabd al-Hukmi*)**: Real coins enter your spot wallet. |
| **Gharar (Uncertainty)** | **Gharar Fahish**: Pure speculation on 15-minute price boundaries. | **Controlled**: Regulated spot asset, disciplined risk management. |
| **Riba (Interest)** | N/A (Event derivative) | **Zero Riba**: 100% unleveraged cash trades; no margin loans, no funding rates. |

> **Conclusion**: You cannot trade Kalshi in a Halal way because the financial instrument itself is an event wager. However, by porting the concept of **systematic, AI-driven automation** to your **Binance Spot account**, we achieve a fully Halal, disciplined algorithmic trading agent.

---

## 2. Core Shariah Rules Enforced in the Code

This codebase features a dedicated **`ShariahComplianceGuard`** in [`core/shariah_guard.py`](core/shariah_guard.py) that strictly enforces:

1. **100% Spot Only (Zero Leverage)**:
   - Margin trading requires borrowing funds with interest (*Riba*).
   - Futures involve synthetic cash-settled derivatives without physical delivery.
   - Any order with leverage ≠ 1.0 throws a `ShariahViolationError`.
2. **Prohibition of Short-Selling (*Bay' ma la tamlik*)**:
   - The Prophet (ﷺ) forbade: *"Do not sell what you do not possess"* (Sunan Abi Dawud 3503).
   - The bot is **Long-Only**: it buys spot crypto with cash (USDT), holds custody, and sells owned assets only at its pre-committed take-profit or stop-loss.
3. **Screened Halal Asset Whitelist**:
   - Only assets with verified utility and permissible economic models are tradable: **BTC, ETH, SOL, LINK, AVAX, NEAR, ADA, DOT, POL (MATIC), XAUT (Tether Gold)**.
   - XAUT is screened as a gold-backed token (1 token = 1 oz allocated physical gold), treated as digital gold under *Bay' al-Sarf* with immediate on-chain settlement (see `config/halal_whitelist.py` for the full screening notes and custody caveat).
   - **Hardcoded Blacklist**: pure meme tokens (DOGE, SHIB, PEPE), interest-bearing lending protocols (AAVE, COMP, MKR), and gambling dApps are permanently blocked. Unlisted assets are blocked by default.
4. **Immediate Possession (*Qabd al-Hukmi*)**:
   - Orders execute on the Binance Spot exchange (`/api/v3/*`), immediately crediting the cryptocurrency to your wallet.
5. **Derivatives Endpoint Blocking**:
   - Calling `/fapi` (Futures), `/dapi` (Coin Futures), or `/sapi/margin` is blocked at the networking layer.

> The Shariah screenings in this project are compiled from public criteria for convenience and are **not** a formal fatwa. Consult a qualified Islamic finance advisor for a binding ruling.

---

## 3. The Strategy: High-Conviction Swing Trading with Pre-Committed Exits

The bot trades a **patient swing style**: few trades, high-quality entries, bigger targets, and no panic exits.

```
                [ Market Data: Binance klines, CLOSED candles only ]
                                   │
                                   ▼
              [ Technical Engine: EMA 20/50/200, RSI 14, ATR 14, MACD ]
                                   │
                                   ▼
              [ Regime + Confluence Filter (trend, RSI zone, MACD, volume) ]
                                   │
                ┌──────────────────┴──────────────────┐
                ▼                                     ▼
       [ Rule-Based Engine ]              [ AI Agent (Gemini/OpenAI/Custom) ]
                └──────────────────┬──────────────────┘
                                   ▼
                  [ Conviction Score >= 0.80 ? ]
                                   │ Yes
                                   ▼
              [ Pending Entry Order (limit-zone, not market buy) ]
                - Entry zone  = min(EMA20, close − 0.75 × ATR)   [pullback]
                - SL/TP shifted down by same delta → 2:1 R:R preserved
                - Fills only when price trades into the zone
                - Cancels if price breaks stop first; expires after 48h
                                   │
                                   ▼
              [ Position Sizing from stop distance (risk-based) ]
                - Risk per trade ≤ 1.0% of portfolio
                - Stop-Loss   = Entry − (2.5 × ATR)
                - Take-Profit = Entry + (5.0 × ATR)   → 2:1 reward:risk
                - Max 20% of portfolio per trade, max 4 concurrent positions
                                   │
                                   ▼
        [ Spot Execution: Paper / Binance Testnet / Live ]
                - Strict exit: ONLY the pre-committed SL or TP may sell
                - Optional exchange-side OCO protection (survives downtime)
```

### 3.1 Strict Swing-Trade Exit Policy (`STRICT_SL_TP_EXIT_ONLY`, default ON)

- **Entry**: high-conviction only (`AI_CONFIDENCE_THRESHOLD=0.80`), signals computed on **closed candles only** (`REQUIRE_CLOSED_CANDLE=true`), ≥2:1 reward:risk, 6h symbol re-entry cooldown.
- **Exit**: routine positions close **only** via the pre-committed stop-loss or take-profit. Trailing stops and AI/regime exits are disabled as sale triggers; the direct AI SELL path is rejected unless the reason is SL/TP/panic. Emergency panic-sell remains available and is logged separately.
- **Timeframe**: default `CANDLE_TIMEFRAME=4h` with `CANDLE_LIMIT=260` so EMA-200 is properly warmed up.

### 3.2 Pending (Limit-Zone) Entries

The AI never buys the moment it likes a setup. When a setup qualifies, it computes a **target entry zone** (`min(EMA20, close − PENDING_ENTRY_PULLBACK_ATR × ATR)`), preserves the 2:1 risk structure around that price, and queues a pending order (`pending_entries` table, visible on the dashboard). Each cycle:

- Price ≤ zone → validate levels at the real fill price, size, and buy → `FILLED`
- Price < stop before filling → `CANCELLED` (no catching a falling knife)
- `PENDING_ENTRY_EXPIRY_HOURS` (default 48h) elapse → `EXPIRED`

**AI zone amendments** (`PENDING_ENTRY_AMEND_ENABLED`, default ON): each scan re-evaluates a waiting order against fresh analysis. The AI may amend the zone under direction-safe guardrails — downward moves (better price) always allowed; upward moves only if the new stop is **not looser** than the old one (risk never widens to chase price); moves under 0.25×ATR are ignored (anti-churn); max `PENDING_ENTRY_MAX_AMENDMENTS` (3) per order, then it's left to fill/expire. Every amendment extends the expiry and is audit-logged (`amend_log` column), with an "amended ×n" badge on the dashboard.

### 3.3 Exchange-Side OCO Protection

In live mode, set `PROTECT_WITH_EXCHANGE_OCO=true` **after testnet verification** to attach a spot OCO order list (take-profit limit + stop-loss stop-limit) to every position, so protection survives bot downtime:

- Live buys attach the OCO; quantities are rounded to the exchange `LOT_SIZE` step and prices to the `PRICE_FILTER` tick (both verified on testnet).
- Sells cancel the OCO **first** (otherwise it locks the balance).
- On restart, the engine reconciles: if the OCO filled while the bot was offline, the position is closed via `EXCHANGE_RECONCILE` without double-selling.

### 3.4 Live Market Data vs Trading Network

Market **display** data (dashboard candles, ticker prices, prediction inputs) always comes from the **real public Binance API** — klines/tickers need no API key — even when `BINANCE_USE_TESTNET=true`. Order placement respects the testnet flag. In `BinanceSpotClient`, an explicit `use_testnet=True/False` constructor argument always overrides the `.env` flag.

---

## 4. Quick Start & CLI Usage

### Prerequisites
- Python 3.10+ (tested on 3.11)
- Binance account (Spot permissions only) — or the free Spot Testnet for safe practice

### Installation
```bash
pip install -r requirements.txt
```

### CLI Commands

#### 0. Launch the Live Visual Web Dashboard (Recommended)
```bash
python main.py dashboard
```
Open **http://127.0.0.1:8000**. The dashboard includes:
- TradingView-style **candlestick chart with real Binance OHLC data** (symbol tabs for all configured pairs, 5m/15m/1H/4H/1D intervals, volume bars, and open-position entry/SL/TP drawn as price lines)
- Equity curve with y-axis padding (small fluctuations stay visible)
- **AI Brain panel**: one forecast per pair (direction, conviction, target/invalidation, thesis)
- **Pending Entry Orders** panel (zone, SL, TP, conviction, expiry)
- Working **AI Scan Now** button (spinner, poll-until-fresh, toast) — every scan persists a fresh forecast for every pair

#### 1. Test Binance API Connection
```bash
python main.py test-connection
```

#### 2. Shariah Screen a Coin
```bash
python main.py screen BTC
python main.py screen XAUT
python main.py screen AAVE
```

#### 3. Run a Market Scan (Single Cycle)
Scans all configured pairs (default: NEAR, ADA, AVAX, LINK, BTC, XAUT vs USDT), runs indicators, evaluates AI models, and prints conviction per pair:
```bash
python main.py scan
# or the direct AI cycle:
python run_ai_cycle.py
```

#### 4. View Portfolio & Active Positions
```bash
python main.py status
```

#### 5. View Trade History & Win Rate
```bash
python main.py history
```

#### 6. Run Autonomous Trading Loop
```bash
python main.py run --interval 300
```

---

## 4.5 Paper Mode — How to Run Safely

**Paper mode is the default.** `PAPER_TRADING=true` is set in `config/settings.py`, so a fresh clone never sends a real order. Paper mode simulates a virtual USDT wallet (default **1000 USDT**) and records every simulated fill, position, and exit to the same SQLite DB the live engine uses — so the dashboard, P&L, and win-rate you see are fully exercised, just with fake money.

There are **three safety levels**; always move through them in order:

| Level | `PAPER_TRADING` | `BINANCE_USE_TESTNET` | Funds | Orders sent to |
| :--- | :--- | :--- | :--- | :--- |
| **1. Paper (default)** | `true` | any | none | nowhere — simulated in SQLite |
| **2. Testnet** | `false` | `true` | free fake keys | Binance Spot Testnet |
| **3. Live** | `false` | `false` | real money | real Binance Spot |

### Run paper mode (Level 1)

1. Create your `.env` from the template and confirm the paper switches:
   ```bash
   cp .env.example .env
   ```
   ```ini
   PAPER_TRADING=true
   INITIAL_PAPER_BALANCE_USDT=1000.0
   BINANCE_USE_TESTNET=false   # ignored while PAPER_TRADING=true
   ```
   API keys can be left **empty** in paper mode. Market data is always the real public Binance API, so signals are genuine.

2. Start the dashboard (recommended — you can watch it trade):
   ```bash
   python main.py dashboard
   # open http://127.0.0.1:8000
   ```

3. Or run the headless autonomous loop:
   ```bash
   python main.py run --interval 300
   ```

4. Or run a single cycle / inspect state:
   ```bash
   python run_ai_cycle.py     # one full AI cycle
   python main.py scan        # scan only, no execution
   python main.py status      # virtual balances + open positions
   python main.py history     # simulated trade log + win rate
   ```

### Useful paper-mode toggles

```ini
# Speed up the sim to learn faster (4h candles are slow to accumulate):
CANDLE_TIMEFRAME=1h
POLL_INTERVAL_SECONDS=300

# Reset the paper wallet back to the starting balance:
#   delete the sim rows for the paper account, or simply set a new
#   INITIAL_PAPER_BALANCE_USDT and re-seed from the dashboard.
```

### Recommended paper-mode duration before going live

Run **at least 2–4 weeks** of continuous paper mode across a full market cycle, and confirm you see **≥ 30 completed simulated trades** with a positive expectancy after fees. Only then consider Level 2 (testnet). The bot's own exit policy (`STRICT_SL_TP_EXIT_ONLY=true`) already forbids discretionary exits, so paper results are a fair preview of live behavior modulo slippage.

---

## 4.6 Can This Run on a Luckfox Pico Max?

**Short answer: technically yes, but it is not recommended as the primary host — use a Raspberry Pi 4/5, mini-PC, or VPS instead. The Luckfox is a viable *headless sentinel* only if you strip it down.**

The Luckfox Pico Max specs are:

| Resource | Luckfox Pico Max | What this bot needs |
| :--- | :--- | :--- |
| CPU | **Single-core** 32-bit ARM Cortex-A7 @ up to 1.2 GHz | `pandas`/`numpy` are optimised for 64-bit with NEON; 32-bit wheels are painful to install |
| RAM | **256 MB DDR3L** | pandas + FastAPI/uvicorn + Jinja2 easily exceed this; swap thrash on a 256 MB box |
| Storage | 256 MB SPI NAND (or microSD) | Python 3 + pandas/numpy wheels ≈ 150–250 MB; SD card strongly advised |
| Network | 10/100 Mbps Ethernet | Fine for the REST polling this bot does |
| NPU | 1 TOPS (INT8) | **Unused** — the bot does no local ML; signals are rule-based or a cloud LLM |
| OS | Buildroot (SDK) / community Ubuntu | Need a 32-bit ARMv7 userland with pip |

### The real blockers

1. **32-bit ARMv7 wheels.** `numpy` and `pandas` ship prebuilt manylinux wheels mostly for x86-64 and aarch64. On a 32-bit Cortex-A7 you frequently have to compile them from source, which is slow and may hit 32-bit float/index limits.
2. **256 MB RAM.** The dashboard (`web/app.py`, FastAPI + uvicorn + lightweight-charts template) plus a pandas DataFrame per pair will not comfortably fit. Running the dashboard **and** the trading loop on-device will OOM.
3. **No local AI acceleration value.** The 1 TOPS NPU only helps for on-device vision models. This bot calls a cloud LLM (or uses the free `algorithmic` provider) and rule-based indicators — the NPU does nothing here.
4. **Flash wear.** SQLite writes every cycle; 256 MB NAND will wear. Use a microSD card and back it up.

### If you still want to run it on the Luckfox (recommended shape)

Run the Luckfox as a **headless sentinel daemon** with a cut-down footprint, and view the dashboard from another machine:

```bash
# On the Luckfox (Buildroot/Ubuntu, Python 3.10+):
pip install --no-cache-dir requests pandas numpy pydantic pydantic-settings python-dotenv click rich
# skip: fastapi, uvicorn, jinja2, openai  (no dashboard, no LLM client on-device)

# Headless loop only, algorithmic provider, no web server:
AI_PROVIDER=algorithmic PAPER_TRADING=true python main.py run --interval 900
```

```ini
# Keep the footprint small on-device:
CANDLE_TIMEFRAME=4h        # fewer bars fetched/computed per cycle
CANDLE_LIMIT=260
POLL_INTERVAL_SECONDS=900  # poll every 15 min, not 5
AI_PROVIDER=algorithmic    # no cloud calls; rule-based only
```

With those settings it will fit in 256 MB, but expect **slow cycles** (seconds per pair on the single A7). For anything public-facing or with the dashboard, put it on a Pi/VPS and keep the Luckfox only if you specifically want the smallest possible always-on headless runner.

---

## 5. Configuration (`.env`)

Copy `.env.example` to `.env` and customize:

```ini
# Binance API Keys (leave empty for paper trading)
BINANCE_API_KEY=your_binance_api_key_here
BINANCE_API_SECRET=your_binance_api_secret_here

# Network: true = Binance Spot TESTNET (free paper funds, its own keys from
# testnet.binance.vision). false = real Binance (real money!).
# Displayed charts/prices always use the real public API regardless.
BINANCE_USE_TESTNET=false

# Simulation Mode (simulated USDT balance, no orders sent)
PAPER_TRADING=true
INITIAL_PAPER_BALANCE_USDT=1000.0

# Trading Parameters (halal, liquidity-screened pairs)
TRADING_PAIRS=["NEARUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "BTCUSDT", "XAUTUSDT"]
CANDLE_TIMEFRAME=4h
CANDLE_LIMIT=260
REQUIRE_CLOSED_CANDLE=true
MAX_ALLOCATION_PER_TRADE_PERCENT=20.0
RISK_PER_TRADE_PERCENT=1.0
ATR_STOP_LOSS_MULTIPLIER=2.5
ATR_TAKE_PROFIT_MULTIPLIER=5.0
MIN_RISK_REWARD_RATIO=2.0

# Strict swing exits: positions close ONLY via SL/TP
STRICT_SL_TP_EXIT_ONLY=true
# Exchange-side OCO protection (enable only after testnet verification)
PROTECT_WITH_EXCHANGE_OCO=false

# Pending limit-zone entries
PENDING_ENTRY_ENABLED=true
PENDING_ENTRY_PULLBACK_ATR=0.75
PENDING_ENTRY_EXPIRY_HOURS=48

# AI Engine: 'algorithmic' (free, offline), 'gemini', 'openai', or 'custom'
AI_PROVIDER=algorithmic
AI_CONFIDENCE_THRESHOLD=0.80

# Optional LLM API Keys
GEMINI_API_KEY=
OPENAI_API_KEY=

# Custom OpenAI-Compatible Endpoints (DeepSeek, OpenRouter, Groq, Ollama, LM Studio)
CUSTOM_BASE_URL=https://api.deepseek.com/v1
CUSTOM_MODEL_NAME=deepseek-chat
CUSTOM_API_KEY=

# --- Regime-quality entry filter (avoids trading in chop) ---
# Master switch; individual gates below are OFF by default after out-of-sample
# validation showed they lower headline return on the 5-pair 4h universe.
REGIME_FILTER_ENABLED=true
REQUIRE_ADX_FILTER=false        # hard ADX gate (off by default)
REQUIRE_CHOP_FILTER=false       # hard Choppiness gate (off by default)
REQUIRE_DI_ALIGNMENT=false      # +DI > -DI gate (defensive profile; off by default)

# --- Portfolio-level risk ---
MAX_TOTAL_EXPOSURE_PERCENT=70.0     # cap total deployed capital
MAX_PORTFOLIO_HEAT_PERCENT=6.0      # cap aggregate open risk
MAX_CORRELATED_EXPOSURE_PERCENT=40.0  # cap capital in correlated assets
CORRELATION_THRESHOLD=0.7

# --- Drawdown circuit breaker / kill switch (high-water-mark based) ---
DRAWDOWN_BREAKER_ENABLED=true
DRAWDOWN_REDUCE_HALF_PERCENT=5.0    # halve new size at -5% DD
DRAWDOWN_REDUCE_QUARTER_PERCENT=10.0 # quarter new size at -10% DD
DRAWDOWN_HALT_PERCENT=15.0          # halt all entries at -15% DD (manual re-arm)

# --- Volatility-targeted sizing & time stop ---
VOL_TARGET_SIZING_ENABLED=true
TARGET_VOL_PERCENT_PER_BAR=1.5
CONFIDENCE_SIZE_SCALING_ENABLED=true
MAX_HOLD_HOURS=0.0                  # 0 = disabled; e.g. 168 = recycle after 7d
```

---

## 6. Going Live Safely (recommended path)

1. **Paper first**: run with `PAPER_TRADING=true` and observe several cycles.
2. **Testnet second**: create free keys at [testnet.binance.vision](https://testnet.binance.vision) (GitHub login), paste them into `.env`, set `BINANCE_USE_TESTNET=true`, and verify OCO end-to-end:
   ```bash
   python analysis/verify_oco_testnet.py
   ```
   This validates buy → OCO attach → sell-cancels-OCO → offline-fill reconciliation against the real testnet. (Already validated in this repo; it caught real LOT_SIZE/PRICE_FILTER bugs.)
3. **Live, small**: generate Binance API keys with **Can Read + Spot Trading only** — **never** enable withdrawals; restrict by IP. Set `PAPER_TRADING=false`, `BINANCE_USE_TESTNET=false`, restore your real keys, and only then consider `PROTECT_WITH_EXCHANGE_OCO=true`. Start with the smallest sensible allocation.

---

## 7. Testing

```bash
python -m unittest discover tests
```

- `test_bot.py` — Shariah compliance, indicators, risk sizing, strict-exit gating, confirmed candles (16 tests)
- `test_oco_flow.py` — OCO attach / cancel-before-sell / offline-fill reconciliation against a stubbed exchange (3 tests)
- `test_pending_entry.py` — entry-zone math, SL/TP shift, fill-on-touch, stop-break cancel, expiry (11 tests)
- `test_portfolio_risk.py` — correlation guard, portfolio heat, total-exposure cap, drawdown breaker, vol/confidence sizing (6 tests)
- `test_full_cycle_guards.py` — end-to-end engine cycle with the new portfolio guards wired in (4 tests)

Current status: **40/40 passing.**

### Empirical validation harnesses

```bash
python analysis/backtest_validation.py       # old vs new signal logic, real Binance klines
python -m analysis.regime_filter_diagnostic  # per-gate (ADX / CHOP / DI) contribution
```

These run against live Binance Spot history (fees included, next-bar fills, end-of-test mark-to-market) and are how the default regime-filter settings were chosen — not by theory.

---

## 8. Branch & Commit Naming (before pushing to `main`)

This upgrade touched the signal engine, risk layer, and added validation tooling. Land it on a **dedicated branch** via a PR — never commit straight to `main`.

### Recommended branch name

```bash
git checkout -b feat/portfolio-risk-regime-guards
```

Naming scheme used here: `<type>/<short-scope>`. Good alternatives for this change set:

- `feat/portfolio-risk-regime-guards` (recommended — covers both new areas)
- `feat/regime-filter-and-drawdown-breaker`
- `refactor/risk-layer-hardening`

### Recommended commit series (atomic, reviewable)

Split the change set into logically separate commits so the diff reads cleanly:

```bash
# 1. New indicators the rest depends on
git add strategy/indicators.py
git commit -m "feat(indicators): add ADX, Choppiness Index, +DI/-DI and realized vol"

# 2. New portfolio-level risk module
git add risk/portfolio_risk.py
git commit -m "feat(risk): add portfolio heat, correlation guard, exposure cap and drawdown breaker"

# 3. Sizing + time-stop upgrades
git add risk/risk_manager.py
git commit -m "feat(risk): volatility-targeted and confidence-scaled position sizing, optional time stop"

# 4. Signal-layer regime gating
git add strategy/signals.py
git commit -m "feat(signals): optional regime-quality entry gate (ADX/CHOP/DI), off by default"

# 5. Config + engine wiring + DB support
git add config/settings.py execution/bot_engine.py storage/database.py
git commit -m "feat(engine): wire portfolio guards, drawdown breaker and new sizing into the cycle"

# 6. Validation harnesses + tests + docs
git add analysis/backtest_validation.py analysis/regime_filter_diagnostic.py \
        tests/test_portfolio_risk.py tests/test_full_cycle_guards.py README.md
git commit -m "test+docs: add backtest validation harnesses, guard tests and README upgrade notes"
```

### One-line / squash alternative

If the repo squash-merges PRs, a single conventional-commit title works:

```
feat(risk): add regime gating, portfolio heat, correlation guard, drawdown breaker and vol-targeted sizing

Empirically validated on 5-pair 4h Binance history (fees included).
Regime gates available but OFF by default — out-of-sample test showed they
lower headline return; enable REQUIRE_DI_ALIGNMENT for a defensive profile.
40/40 tests passing.
```

### Convention rules

- **Type**: `feat` · `fix` · `refactor` · `test` · `docs` · `chore`
- **Scope**: module touched — `indicators`, `risk`, `signals`, `engine`, `config`, `docs`
- **Subject**: imperative mood, ≤ 72 chars, no trailing period
- **Body**: explain *why* and the empirical evidence, not just *what*
- **PR title = squashed commit title**; mention **"40/40 tests passing"** and the paper-mode requirement in the PR description.

### Pre-push checklist

```bash
python -m unittest discover tests      # expect 40/40 passing
python -m py_compile strategy/*.py risk/*.py execution/*.py config/*.py storage/*.py
git status --short                     # review exactly what will ship
git push -u origin feat/portfolio-risk-regime-guards
# then open a PR into main
```

---

## 9. Project Architecture

```
trading agent x/
├── config/
│   ├── settings.py           # Pydantic settings loaded from .env (all policy knobs)
│   └── halal_whitelist.py    # Shariah screenings & token whitelist (incl. XAUT)
├── core/
│   ├── shariah_guard.py      # Compliance guard (blocks margin/futures/shorts/unlisted)
│   └── binance_client.py     # Spot REST client; OCO support; explicit testnet override
├── strategy/
│   ├── indicators.py         # EMA/RSI/ATR/MACD + confirmed-candle helper
│   ├── signals.py            # Quantitative trend-following & momentum rules
│   └── ai_predictor.py       # AI forecaster (Gemini / OpenAI / custom endpoints)
├── risk/
│   ├── risk_manager.py       # Risk-based sizing, ATR stops, strict-mode exit checks
│   └── portfolio_risk.py     # Correlation guard, portfolio heat, exposure cap, drawdown breaker
├── storage/
│   └── database.py           # SQLite: balances, positions, pending entries, predictions, equity curve
├── execution/
│   └── bot_engine.py         # Cycle coordinator: scans, pending entries, strict exits, OCO, portfolio guards
├── analysis/
│   ├── halal_swing_scan.py       # Liquidity/ATR/trend scanner used to pick pairs
│   ├── verify_oco_testnet.py     # Live testnet OCO verification script
│   ├── backtest_validation.py    # Old-vs-new signal logic on real Binance history
│   └── regime_filter_diagnostic.py  # Per-gate (ADX/CHOP/DI) contribution analysis
├── web/
│   ├── app.py                # FastAPI dashboard & background sentinel
│   └── templates/index.html  # Dashboard UI (lightweight-charts + Tailwind)
├── tests/                    # 40-test suite (see §7)
├── run_ai_cycle.py           # Single-cycle AI scan (shares settings/thresholds)
├── ai_commander.py           # Direct command interface (policy-checked)
├── main.py                   # Rich CLI
└── .env.example              # Template configuration
```

---

**Disclaimer**: This software is for educational and research purposes. It is not financial advice, and its Shariah screenings are not a formal fatwa. Crypto trading involves substantial risk of loss; never trade with funds you cannot afford to lose, and consult qualified financial and Shariah advisors before going live.

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
cd tests
python -m unittest test_bot test_oco_flow test_pending_entry
```

- `test_bot.py` — Shariah compliance, indicators, risk sizing, strict-exit gating, confirmed candles (16 tests)
- `test_oco_flow.py` — OCO attach / cancel-before-sell / offline-fill reconciliation against a stubbed exchange (3 tests)
- `test_pending_entry.py` — entry-zone math, SL/TP shift, fill-on-touch, stop-break cancel, expiry (6 tests)

Current status: **25/25 passing.**

---

## 8. Project Architecture

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
│   └── risk_manager.py       # Risk-based sizing, ATR stops, strict-mode exit checks
├── storage/
│   └── database.py           # SQLite: balances, positions, pending entries, predictions
├── execution/
│   └── bot_engine.py         # Cycle coordinator: scans, pending entries, strict exits, OCO
├── analysis/
│   ├── halal_swing_scan.py   # Liquidity/ATR/trend scanner used to pick pairs
│   └── verify_oco_testnet.py # Live testnet OCO verification script
├── web/
│   ├── app.py                # FastAPI dashboard & background sentinel
│   └── templates/index.html  # Dashboard UI (lightweight-charts + Tailwind)
├── tests/                    # 25-test suite (see §7)
├── run_ai_cycle.py           # Single-cycle AI scan (shares settings/thresholds)
├── ai_commander.py           # Direct command interface (policy-checked)
├── main.py                   # Rich CLI
└── .env.example              # Template configuration
```

---

**Disclaimer**: This software is for educational and research purposes. It is not financial advice, and its Shariah screenings are not a formal fatwa. Crypto trading involves substantial risk of loss; never trade with funds you cannot afford to lose, and consult qualified financial and Shariah advisors before going live.

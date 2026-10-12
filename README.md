# Halal Crypto AI Spot Trading Agent (Process Over Profit)

> **A Shariah-compliant, quantitative AI spot trading engine for Binance.**  
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

This codebase features a dedicated **`ShariahComplianceGuard`** in [`core/shariah_guard.py`](file:///c:/Users/admin/Downloads/trading%20agent%20x/core/shariah_guard.py) that strictly enforces:

1. **100% Spot Only (Zero Leverage)**:
   - Margin trading requires borrowing funds with interest (*Riba*).
   - Futures involve synthetic cash-settled derivatives without physical delivery.
   - Any order with leverage $\neq 1.0$ throws a `ShariahViolationError`.
2. **Prohibition of Short-Selling (*Bay' ma la tamlik*)**:
   - The Prophet (ﷺ) forbade: *"Do not sell what you do not possess"* (Sunan Abi Dawud 3503).
   - The bot is **Long-Only**: It buys spot crypto with cash (USDT), holds custody, and sells owned assets only when profit targets or stop-losses are reached.
3. **Screened Halal Asset Whitelist**:
   - Only coins with verified technological utility and permissible economic models are tradable: **BTC, ETH, SOL, LINK, AVAX, POL (MATIC), NEAR, DOT, ADA**.
   - **Hardcoded Blacklist**: Pure meme tokens (DOGE, SHIB, PEPE), interest-bearing lending protocols (AAVE, COMP, MKR), and gambling dApps are permanently blocked.
4. **Immediate Possession (*Qabd al-Hukmi*)**:
   - Orders execute on the Binance Spot exchange (`/api/v3/*`), immediately crediting the cryptocurrency to your wallet.
5. **Derivatives Endpoint Blocking**:
   - Calling `/fapi` (Futures), `/dapi` (Coin Futures), or `/sapi/margin` is blocked at the networking layer.

---

## 3. The New Strategy: From Binary Bets to Systematic Spot Momentum

Instead of a 15-minute coin flip, the bot uses a **Multi-Layered Quantitative + AI Strategy**:

```
                       [ Market Data: 15m Binance Candlesticks ]
                                          │
                                          ▼
                      [ Technical Indicator Engine: EMA, RSI, ATR, MACD ]
                                          │
                                          ▼
                      [ Market Regime & Confluence Filter ]
                                          │
                  ┌───────────────────────┴───────────────────────┐
                  ▼                                               ▼
         [ Rule-Based Engine ]                       [ AI Agent (Gemini/OpenAI) ]
                  │                                               │
                  └───────────────────────┬───────────────────────┘
                                          ▼
                         [ Conviction Score >= 0.65 ? ]
                                          │ Yes
                                          ▼
                   [ Shariah-Compliant Position Sizing (Risk Manager) ]
                     - Risk max 1.5% portfolio on Stop-Loss distance
                     - Dynamic Stop-Loss = Entry - (1.8 * ATR)
                     - Dynamic Take-Profit = Entry + (3.2 * ATR)
                     - Trailing Stop unlocks after +2% gain
                                          │
                                          ▼
                     [ Spot Execution: Paper Trade or Live Binance ]
```

---

## 3.1 Strict Swing-Trade Exit Policy (STRICT_SL_TP_EXIT_ONLY)

The bot runs in **strict swing mode** by default:

- **Entry**: high-conviction only (`AI_CONFIDENCE_THRESHOLD=0.80`), signals computed on **closed candles only** (`REQUIRE_CLOSED_CANDLE=true`), ≥2:1-style ATR reward:risk (2.5×/5.0× ATR), max 4 concurrent positions, 6h symbol re-entry cooldown.
- **Exit**: routine positions close **only** via the pre-committed stop-loss or take-profit. Trailing stops and AI/regime exits are disabled as sale triggers. The AI may still *review* a thesis, but it cannot sell early. Emergency panic-sell remains available and is logged separately.
- **Protection**: in live mode, set `PROTECT_WITH_EXCHANGE_OCO=true` (after testnet verification) to attach an exchange-side OCO (take-profit + stop-loss) to every position, so protection survives bot downtime. The engine cancels the OCO before manual/panic sells and reconciles the DB if the exchange filled it while offline.

## 4. Quick Start & CLI Usage

### Prerequisites
- Python 3.10+ (Tested on Python 3.11)
- Binance account (Spot permissions only)

### Installation
```bash
pip install -r requirements.txt
```

### CLI Commands

#### 0. Launch the Live Visual Web Dashboard (Recommended!)
Start the real-time web dashboard with live equity graphs, AI prediction brain, and one-click controls:
```bash
python main.py dashboard
```
Then open your browser to **http://127.0.0.1:8000** to see live graphs, fee audits, and market predictions.

#### 1. Test Binance API Connection
Verifies connectivity to Binance Spot API and fetches current BTC price without requiring any API keys:
```bash
python main.py test-connection
```

#### 2. Shariah Screen a Coin
Inspect the Halal compliance report and reasoning for any token:
```bash
python main.py screen BTC
python main.py screen AAVE
python main.py screen SOL
```

#### 3. Run a Market Scan (Single Cycle)
Scans all whitelisted spot markets (BTC, ETH, SOL, LINK, AVAX), runs indicators, evaluates AI models, and displays a formatted table:
```bash
python main.py scan
```

#### 4. View Portfolio & Active Positions
Displays available USDT cash, open spot positions, current prices, stop-losses, and unrealized PnL:
```bash
python main.py status
```

#### 5. View Trade History & Win Rate
Displays closed trades, realized profit/loss, and exit reasons:
```bash
python main.py history
```

#### 6. Run Autonomous Trading Loop
Runs continuous scans every 60 seconds (or custom interval):
```bash
python main.py run --interval 60
```

---

---

## 5. Configuration (`.env`)

Copy `.env.example` to `.env` and customize your settings:

```ini
# Binance API Keys (Leave empty for Paper Trading)
BINANCE_API_KEY=your_binance_api_key_here
BINANCE_API_SECRET=your_binance_api_secret_here

# Simulation Mode (Keep true to test with simulated $1,000 USDT)
PAPER_TRADING=true
INITIAL_PAPER_BALANCE_USDT=1000.0

# Trading Parameters
TRADING_PAIRS=["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT"]
CANDLE_TIMEFRAME=15m
MAX_ALLOCATION_PER_TRADE_PERCENT=20.0
RISK_PER_TRADE_PERCENT=1.5
ATR_STOP_LOSS_MULTIPLIER=1.8
ATR_TAKE_PROFIT_MULTIPLIER=3.2

# AI Engine: 'algorithmic' (Free, offline), 'gemini', 'openai', or 'custom'
AI_PROVIDER=algorithmic
AI_CONFIDENCE_THRESHOLD=0.65

# Optional LLM API Keys
GEMINI_API_KEY=
OPENAI_API_KEY=

# Custom OpenAI-Compatible Endpoints (DeepSeek, OpenRouter, Groq, Ollama, LM Studio)
# Examples:
# DeepSeek:   CUSTOM_BASE_URL=https://api.deepseek.com/v1          CUSTOM_MODEL_NAME=deepseek-chat
# OpenRouter: CUSTOM_BASE_URL=https://openrouter.ai/api/v1         CUSTOM_MODEL_NAME=deepseek/deepseek-r1
# Groq:       CUSTOM_BASE_URL=https://api.groq.com/openai/v1       CUSTOM_MODEL_NAME=llama-3.3-70b-versatile
# Ollama:     CUSTOM_BASE_URL=http://localhost:11434/v1            CUSTOM_MODEL_NAME=llama3
# LM Studio:  CUSTOM_BASE_URL=http://localhost:1234/v1             CUSTOM_MODEL_NAME=local-model
CUSTOM_BASE_URL=https://api.deepseek.com/v1
CUSTOM_MODEL_NAME=deepseek-chat
CUSTOM_API_KEY=
```

---

## 6. How to Switch to Live Binance Spot Trading Safely

1. **Generate Binance API Keys**:
   - Log into Binance -> Account -> API Management.
   - Create an API key named `HalalAI_Agent`.
   - **Permissions**: Enable **"Can Read"** and **"Enable Spot & Margin Trading"** (leave Margin unchecked).
   - **Crucial Security**: **NEVER check "Enable Withdrawals"**. Restrict IP access to your IP address.
2. In `.env` or the Dashboard Settings Modal:
   - Paste your `BINANCE_API_KEY` and `BINANCE_API_SECRET`
   - Switch mode to **REAL BINANCE SPOT** (`PAPER_TRADING=false`)
3. The bot will automatically verify your real spot balance and place real spot buy/sell orders strictly on the Spot exchange.

---

## 7. Project Architecture

```
trading agent x/
├── config/
│   ├── settings.py           # Pydantic settings loading from .env
│   └── halal_whitelist.py    # Shariah screening criteria and token whitelists
├── core/
│   ├── shariah_guard.py      # Hardcoded compliance guard (blocks margin/shorting)
│   └── binance_client.py     # Pure Binance Spot REST API client
├── strategy/
│   ├── indicators.py         # EMA 20/50/200, RSI 14, ATR 14, MACD, Volume analysis
│   ├── signals.py            # Quantitative trend-following & momentum rules
│   └── ai_predictor.py       # Autonomous AI Forecaster (Gemini / OpenAI / Custom Endpoints)
├── risk/
│   └── risk_manager.py       # Position sizing, dynamic ATR stops, trailing stop logic
├── storage/
│   └── database.py           # SQLite database for paper balance, positions, trade history
├── execution/
│   └── bot_engine.py         # Autonomous cycle coordinator
├── web/
│   ├── app.py                # FastAPI dashboard server & background sentinel
│   └── templates/
│       └── index.html        # Dark-mode dashboard UI (Chart.js + Tailwind)
├── tests/
│   └── test_bot.py           # Full test suite covering compliance, risk, indicators, and AI
├── main.py                   # Rich CLI interface & interactive commands
├── .env.example              # Template configuration
└── .gitignore                # Protects .env and databases from git commits
```


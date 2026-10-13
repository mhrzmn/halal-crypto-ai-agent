"""
Application Configuration and Settings.
Loads settings from environment variables or .env file with robust defaults.
"""

from typing import List, Optional
import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# Load .env if present
load_dotenv()

class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Binance Spot Configuration
    BINANCE_API_KEY: str = Field(default="", description="Binance API Key (Spot permissions only)")
    BINANCE_API_SECRET: str = Field(default="", description="Binance API Secret")
    BINANCE_USE_TESTNET: bool = Field(default=False, description="Use Binance Spot Testnet if True")

    # Paper Trading / Simulation Mode (Always True by default for capital preservation)
    PAPER_TRADING: bool = Field(default=True, description="Enable simulated paper trading without real funds")
    INITIAL_PAPER_BALANCE_USDT: float = Field(default=1000.0, description="Virtual starting USDT balance")

    # Halal Trading Pairs (Strictly Shariah-screened spot pairs)
    TRADING_PAIRS: List[str] = Field(
        default=["NEARUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "BTCUSDT", "XAUTUSDT"],
        description="Halal whitelisted spot pairs to monitor. Ranked by live liquidity + ATR% + trend "
                    "(analysis/halal_swing_scan.py, 2026-10-12): high-volatility uptrend names first, "
                    "BTC as the deep-liquidity anchor. ETH/SOL excluded (neutral trend), DOT/POL excluded "
                    "(below $10M 24h quote volume liquidity gate)."
    )

    # Strategy & Timeframe Settings
    CANDLE_TIMEFRAME: str = Field(default="4h", description="Candlestick interval (e.g. 15m, 1h, 4h)")
    CANDLE_LIMIT: int = Field(
        default=260,
        description="Number of past candles to analyze (>= 200 EMA span + warmup buffer)"
    )
    POLL_INTERVAL_SECONDS: int = Field(default=300, description="Seconds between market scan iterations")
    REQUIRE_CLOSED_CANDLE: bool = Field(
        default=True,
        description="Drop the still-forming last candle before computing signals (prevents intra-bar flip-flops)"
    )

    # Risk Management Settings (Process Over Profit principle)
    MAX_ALLOCATION_PER_TRADE_PERCENT: float = Field(
        default=20.0,
        description="Maximum percent of total available USDT to allocate to a single spot position"
    )
    RISK_PER_TRADE_PERCENT: float = Field(
        default=1.0,
        description="Maximum portfolio percentage risked on stop-loss distance"
    )
    MAX_OPEN_POSITIONS: int = Field(
        default=4,
        description="Maximum number of concurrent open positions (caps total exposure)"
    )
    MIN_RISK_REWARD_RATIO: float = Field(
        default=2.0,
        description="Minimum TP-distance / SL-distance ratio required to enter a trade. "
                    "Aligned with ATR multipliers (5.0 / 2.5 = 2:1) so entries below the "
                    "configured R:R are rejected instead of silently accepted."
    )
    # Pending (limit) entries: instead of buying immediately at market when the AI
    # approves a setup, the bot computes a target entry zone (pullback toward EMA20
    # or close - PENDING_ENTRY_PULLBACK_ATR * ATR) and waits for price to trade into it.
    PENDING_ENTRY_ENABLED: bool = Field(
        default=True,
        description="Queue approved entries as pending limit-zone orders instead of buying at market"
    )
    PENDING_ENTRY_PULLBACK_ATR: float = Field(
        default=0.75,
        description="How deep below the signal close the entry zone sits, in ATR multiples"
    )
    PENDING_ENTRY_AMEND_ENABLED: bool = Field(
        default=True,
        description="Allow the AI to amend a waiting pending entry's zone on fresh analysis "
                    "(direction-safe: downward moves always allowed; upward moves only if the "
                    "stop is not loosened)."
    )
    PENDING_ENTRY_MAX_AMENDMENTS: int = Field(
        default=3,
        description="Max number of times a single pending order may be amended before it is left to fill/expire."
    )
    PENDING_ENTRY_EXPIRY_HOURS: int = Field(
        default=48,
        description="Cancel a pending entry if price never reaches the zone within this window"
    )
    ATR_STOP_LOSS_MULTIPLIER: float = Field(
        default=2.5,
        description="Multiple of ATR to set Stop-Loss below entry"
    )
    ATR_TAKE_PROFIT_MULTIPLIER: float = Field(
        default=5.0,
        description="Multiple of ATR to set Take-Profit above entry"
    )
    TRAILING_STOP_ACTIVATION_PERCENT: float = Field(
        default=3.0,
        description="Profit percentage when trailing stop becomes active"
    )
    TRAILING_STOP_DISTANCE_PERCENT: float = Field(
        default=2.0,
        description="How far below the highest price the trailing stop trails (percent)"
    )

    # AI Decision Engine Configuration
    # Supported: 'algorithmic' (no API key required), 'gemini', 'openai', 'custom'
    AI_PROVIDER: str = Field(default="algorithmic", description="AI Provider: algorithmic, gemini, openai, or custom")
    GEMINI_API_KEY: str = Field(default="", description="Google Gemini API Key")
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API Key")
    CUSTOM_BASE_URL: str = Field(default="", description="Custom OpenAI-compatible base URL (e.g. https://api.deepseek.com/v1, https://openrouter.ai/api/v1, http://localhost:11434/v1)")
    CUSTOM_MODEL_NAME: str = Field(default="", description="Custom model name (e.g. deepseek-chat, llama-3.3-70b, etc.)")
    CUSTOM_API_KEY: str = Field(default="", description="API key for custom endpoint")
    AI_CONFIDENCE_THRESHOLD: float = Field(
        default=0.80,
        description="Minimum AI conviction score (0.0 to 1.0) required to execute an entry. "
                    "Deliberately high: fewer, higher-conviction trades."
    )

    # Strict Exit Policy (Process Over Profit — quality over frequency)
    STRICT_SL_TP_EXIT_ONLY: bool = Field(
        default=True,
        description="When True, routine positions close ONLY via the pre-committed stop-loss or "
                    "take-profit. Trailing stops and AI/regime exits are disabled as sale triggers; "
                    "emergency panic sell remains available and is separately logged."
    )
    PROTECT_WITH_EXCHANGE_OCO: bool = Field(
        default=False,
        description="When True (live mode), place an exchange-side OCO (take-profit + stop-loss) "
                    "after each live buy so protection survives bot downtime. Verify on testnet first."
    )

    # Anti-Churn Protection (stops fee-bleeding from rapid in/out trading)
    MIN_HOLD_MINUTES: float = Field(
        default=720.0,
        description="Minimum minutes a position must be held before an AI/regime exit is allowed (SL/TP/trailing/panic always fire)"
    )
    AI_EXIT_MIN_EDGE_PERCENT: float = Field(
        default=1.5,
        description="AI exits are blocked unless the trade is losing more than this %% (cut losses) or gaining more than this %% (lock profit). Round-trip fees are ~0.2%%, so exits below this just donate fees."
    )
    SYMBOL_REENTRY_COOLDOWN_MINUTES: float = Field(
        default=360.0,
        description="Minutes to wait before re-buying a symbol that was just closed"
    )

    # ------------------------------------------------------------------
    # Regime Quality Filter (avoid trading in chop — the #1 whipsaw killer)
    # Only enter when the tape has genuine directional energy (ADX up,
    # Choppiness down). Both conditions must be met to allow an entry.
    # ------------------------------------------------------------------
    REGIME_FILTER_ENABLED: bool = Field(
        default=True,
        description="Block new entries when the market is non-trending (low ADX / high Choppiness)"
    )
    # Self-critique / out-of-sample finding (2026-10-13, 5-pair 4h ~1000-bar
    # Binance history, fees included, next-bar fills):
    #   full ADX+CHOP gate  -> reduced aggregate return
    #   +DI>-DI gate alone  -> NEARUT 8.1->3.8, ADA 2.3->5.2, LINK 5.9->6.7,
    #                          BTC 2.4->2.5, AVAX neutral; TOTAL 23.4->22.9
    # Net: the gate improves 3 of 5 pairs and lowers drawdown but slightly
    # reduces headline return. It is therefore kept AVAILABLE but OFF by default;
    # enable REQUIRE_DI_ALIGNMENT for a more conservative, lower-variance profile.
    REGIME_FILTER_ENABLED: bool = Field(
        default=True,
        description="Master switch for regime-quality entry gating"
    )
    REQUIRE_ADX_FILTER: bool = Field(
        default=False,
        description="Require ADX above threshold as a hard entry gate (off: reduced aggregate edge)"
    )
    ADX_TREND_THRESHOLD: float = Field(
        default=20.0,
        description="Minimum ADX(14) when REQUIRE_ADX_FILTER is enabled"
    )
    ADX_STRONG_TREND: float = Field(
        default=30.0,
        description="ADX(14) level used for observability (not a score bonus)"
    )
    REQUIRE_CHOP_FILTER: bool = Field(
        default=False,
        description="Require Choppiness below threshold as a hard entry gate (off: reduced aggregate edge)"
    )
    CHOP_MAX_THRESHOLD: float = Field(
        default=61.8,
        description="Choppiness Index ceiling when REQUIRE_CHOP_FILTER is enabled"
    )
    REQUIRE_DI_ALIGNMENT: bool = Field(
        default=False,
        description="Require +DI > -DI (bullish directional bias) for entries. Lower-variance but "
                    "marginally lower return on the tested universe; enable for a defensive profile."
    )

    # ------------------------------------------------------------------
    # Portfolio-Level Risk (correlation / heat / total exposure)
    # ------------------------------------------------------------------
    MAX_TOTAL_EXPOSURE_PERCENT: float = Field(
        default=70.0,
        description="Hard cap on total deployed capital as %% of equity (keeps dry powder for drawdowns)"
    )
    MAX_PORTFOLIO_HEAT_PERCENT: float = Field(
        default=6.0,
        description="Max aggregate open risk (sum of per-trade risk) as %% of equity"
    )
    MAX_CORRELATED_EXPOSURE_PERCENT: float = Field(
        default=40.0,
        description="Max capital (%% of equity) allowed in concurrently-held assets that move together"
    )
    CORRELATION_THRESHOLD: float = Field(
        default=0.7,
        description="Correlation above which two assets are treated as one concentrated bet"
    )
    CORRELATION_LOOKBACK_CANDLES: int = Field(
        default=120,
        description="Number of candles used to estimate pairwise return correlation for the correlation guard"
    )

    # ------------------------------------------------------------------
    # Drawdown Circuit Breaker / Kill Switch (equity high-water-mark based)
    # Tiered de-risking, then a full halt requiring manual re-arm.
    # ------------------------------------------------------------------
    DRAWDOWN_BREAKER_ENABLED: bool = Field(
        default=True,
        description="Enable equity-curve drawdown circuit breakers (like institutional bots)"
    )
    DRAWDOWN_REDUCE_HALF_PERCENT: float = Field(
        default=5.0,
        description="Drawdown from equity high-water mark at which new position sizes are halved"
    )
    DRAWDOWN_REDUCE_QUARTER_PERCENT: float = Field(
        default=10.0,
        description="Drawdown at which new position sizes are cut to a quarter"
    )
    DRAWDOWN_HALT_PERCENT: float = Field(
        default=15.0,
        description="Drawdown at which all new entries halt until manually re-armed (kill switch)"
    )
    KILL_SWITCH_ARMED_FILE: str = Field(
        default="storage/kill_switch.state",
        description="State file recording whether the kill switch is armed (halted) or cleared"
    )

    # ------------------------------------------------------------------
    # Volatility-Targeted Sizing & Time Stops
    # ------------------------------------------------------------------
    VOL_TARGET_SIZING_ENABLED: bool = Field(
        default=True,
        description="Scale position size inversely with realized volatility (calmer tape = larger size)"
    )
    TARGET_VOL_PERCENT_PER_BAR: float = Field(
        default=1.5,
        description="Target per-bar realized vol %% used as the volatility-sizing reference"
    )
    VOL_SCALE_MIN: float = Field(
        default=0.5, description="Lower clamp on the volatility size multiplier"
    )
    VOL_SCALE_MAX: float = Field(
        default=1.5, description="Upper clamp on the volatility size multiplier"
    )
    CONFIDENCE_SIZE_SCALING_ENABLED: bool = Field(
        default=True,
        description="Scale position size with signal confidence (higher conviction = larger size)"
    )
    MAX_HOLD_HOURS: float = Field(
        default=0.0,
        description="Time-based exit: close a position after this many hours even without SL/TP. "
                    "0 disables. Swing default 0; set e.g. 168 (7d) to recycle dead capital."
    )

    # Storage
    DB_PATH: str = Field(default="storage/trades.db", description="SQLite database path")

settings = AppSettings()

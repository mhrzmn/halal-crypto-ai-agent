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

    # Storage
    DB_PATH: str = Field(default="storage/trades.db", description="SQLite database path")

settings = AppSettings()

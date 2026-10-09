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
        default=["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT"],
        description="List of whitelisted spot pairs to monitor"
    )

    # Strategy & Timeframe Settings
    CANDLE_TIMEFRAME: str = Field(default="15m", description="Candlestick interval (e.g. 15m, 1h, 4h)")
    CANDLE_LIMIT: int = Field(default=100, description="Number of past candles to analyze")
    POLL_INTERVAL_SECONDS: int = Field(default=60, description="Seconds between market scan iterations")

    # Risk Management Settings (Process Over Profit principle)
    MAX_ALLOCATION_PER_TRADE_PERCENT: float = Field(
        default=20.0,
        description="Maximum percent of total available USDT to allocate to a single spot position"
    )
    RISK_PER_TRADE_PERCENT: float = Field(
        default=1.5,
        description="Maximum portfolio percentage risked on stop-loss distance"
    )
    ATR_STOP_LOSS_MULTIPLIER: float = Field(
        default=1.8,
        description="Multiple of ATR to set Stop-Loss below entry"
    )
    ATR_TAKE_PROFIT_MULTIPLIER: float = Field(
        default=3.2,
        description="Multiple of ATR to set Take-Profit above entry"
    )
    TRAILING_STOP_ACTIVATION_PERCENT: float = Field(
        default=2.0,
        description="Profit percentage when trailing stop becomes active"
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
        default=0.65,
        description="Minimum AI conviction score (0.0 to 1.0) required to execute an entry"
    )

    # Storage
    DB_PATH: str = Field(default="storage/trades.db", description="SQLite database path")

settings = AppSettings()

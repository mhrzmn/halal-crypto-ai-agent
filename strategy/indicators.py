"""
Technical Indicators Calculation Engine.
Calculates core indicators for systematic trend, momentum, and volatility analysis.
"""

from typing import Dict, Any
import numpy as np
import pandas as pd

class IndicatorEngine:
    @staticmethod
    def confirmed_candles(df: pd.DataFrame) -> pd.DataFrame:
        """
        Return the frame without the still-forming last candle.
        Binance returns the currently open kline as the final row; using it for
        signals causes intra-bar flip-flops and premature entries. Requires the
        `close_time` column produced by BinanceSpotClient.get_klines.
        """
        if df is None or df.empty:
            return df
        if "close_time" not in df.columns:
            # No timing info available — be conservative and drop the last bar.
            return df.iloc[:-1]
        close_time = df["close_time"].iloc[-1]
        if pd.isna(close_time):
            return df.iloc[:-1]
        now_utc = pd.Timestamp.utcnow().tz_localize(None)
        close_time = pd.Timestamp(close_time).tz_localize(None) if pd.Timestamp(close_time).tzinfo else pd.Timestamp(close_time)
        if close_time >= now_utc:
            return df.iloc[:-1]
        return df

    @staticmethod
    def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
        """Calculate technical indicators and append them to DataFrame."""
        data = df.copy()

        # Exponential Moving Averages (Trend Filters)
        data["ema_20"] = data["close"].ewm(span=20, adjust=False).mean()
        data["ema_50"] = data["close"].ewm(span=50, adjust=False).mean()
        data["ema_200"] = data["close"].ewm(span=200, adjust=False).mean()

        # Relative Strength Index (RSI 14)
        delta = data["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        data["rsi_14"] = 100 - (100 / (1 + rs))

        # Average True Range (ATR 14) for dynamic volatility stops
        high_low = data["high"] - data["low"]
        high_prev_close = (data["high"] - data["close"].shift(1)).abs()
        low_prev_close = (data["low"] - data["close"].shift(1)).abs()
        tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
        data["atr_14"] = tr.rolling(window=14).mean()

        # MACD (12, 26, 9)
        ema_12 = data["close"].ewm(span=12, adjust=False).mean()
        ema_26 = data["close"].ewm(span=26, adjust=False).mean()
        data["macd_line"] = ema_12 - ema_26
        data["macd_signal"] = data["macd_line"].ewm(span=9, adjust=False).mean()
        data["macd_hist"] = data["macd_line"] - data["macd_signal"]

        # Bollinger Bands (20, 2 std)
        data["bb_mid"] = data["close"].rolling(window=20).mean()
        bb_std = data["close"].rolling(window=20).std()
        data["bb_upper"] = data["bb_mid"] + (bb_std * 2)
        data["bb_lower"] = data["bb_mid"] - (bb_std * 2)

        # Volume Moving Average & Volume Spike Detection
        data["vol_ma_20"] = data["volume"].rolling(window=20).mean()
        data["vol_ratio"] = data["volume"] / (data["vol_ma_20"] + 1e-9)

        return data

    @staticmethod
    def get_latest_snapshot(df_with_indicators: pd.DataFrame) -> Dict[str, Any]:
        """Extract a structured summary of the latest market bar."""
        latest = df_with_indicators.iloc[-1]
        prev = df_with_indicators.iloc[-2] if len(df_with_indicators) > 1 else latest

        close = float(latest["close"])
        ema_20 = float(latest["ema_20"]) if not np.isnan(latest["ema_20"]) else close
        ema_50 = float(latest["ema_50"]) if not np.isnan(latest["ema_50"]) else close
        ema_200 = float(latest["ema_200"]) if not np.isnan(latest["ema_200"]) else close
        rsi = float(latest["rsi_14"]) if not np.isnan(latest["rsi_14"]) else 50.0
        atr = float(latest["atr_14"]) if not np.isnan(latest["atr_14"]) else (close * 0.01)
        vol_ratio = float(latest["vol_ratio"]) if not np.isnan(latest["vol_ratio"]) else 1.0

        # Market Regime
        if close > ema_200 and ema_20 > ema_50:
            regime = "STRONG_BULLISH"
        elif close > ema_200:
            regime = "MODERATE_BULLISH"
        elif close < ema_200 and ema_20 < ema_50:
            regime = "STRONG_BEARISH"
        elif close < ema_200:
            regime = "MODERATE_BEARISH"
        else:
            regime = "RANGING"

        return {
            "close": close,
            "open": float(latest["open"]),
            "high": float(latest["high"]),
            "low": float(latest["low"]),
            "volume": float(latest["volume"]),
            "ema_20": ema_20,
            "ema_50": ema_50,
            "ema_200": ema_200,
            "rsi_14": rsi,
            "atr_14": atr,
            "vol_ratio": vol_ratio,
            "macd_hist": float(latest["macd_hist"]) if not np.isnan(latest["macd_hist"]) else 0.0,
            "prev_macd_hist": float(prev["macd_hist"]) if not np.isnan(prev["macd_hist"]) else 0.0,
            "regime": regime,
        }

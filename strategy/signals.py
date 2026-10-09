"""
Quantitative Signal Generator.
Executes rule-based trend-following and momentum pullback checks.
Adheres strictly to Long-Only Spot principles (no short selling).
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass
from config.settings import settings

@dataclass
class TradeSignal:
    symbol: str
    action: str  # 'BUY', 'SELL', 'HOLD'
    confidence: float  # 0.0 to 1.0
    current_price: float
    stop_loss: float
    take_profit: float
    risk_reward_ratio: float
    rationale: str
    regime: str

class SignalGenerator:
    @staticmethod
    def generate_signal(
        symbol: str,
        snapshot: Dict[str, Any],
        has_open_position: bool = False,
        entry_price: Optional[float] = None
    ) -> TradeSignal:
        """
        Evaluate market snapshot and return a structured trading signal.
        """
        close = snapshot["close"]
        rsi = snapshot["rsi_14"]
        ema_20 = snapshot["ema_20"]
        ema_50 = snapshot["ema_50"]
        ema_200 = snapshot["ema_200"]
        atr = snapshot["atr_14"]
        vol_ratio = snapshot["vol_ratio"]
        regime = snapshot["regime"]
        macd_hist = snapshot["macd_hist"]
        prev_macd_hist = snapshot["prev_macd_hist"]

        # Default dynamic targets
        stop_dist = atr * settings.ATR_STOP_LOSS_MULTIPLIER
        tp_dist = atr * settings.ATR_TAKE_PROFIT_MULTIPLIER
        sl_price = round(max(0.01, close - stop_dist), 4)
        tp_price = round(close + tp_dist, 4)
        rr_ratio = round(tp_dist / (stop_dist + 1e-9), 2)

        # 1. Position Exit Evaluation (If currently holding the asset)
        if has_open_position and entry_price is not None:
            # Overbought target reached -> take profit
            if rsi > 75 and macd_hist < prev_macd_hist:
                return TradeSignal(
                    symbol=symbol,
                    action="SELL",
                    confidence=0.85,
                    current_price=close,
                    stop_loss=sl_price,
                    take_profit=tp_price,
                    risk_reward_ratio=rr_ratio,
                    rationale="Overbought target reached (RSI > 75) with momentum deceleration. Taking profit.",
                    regime=regime
                )
            # Severe breakdown below entry
            if close < (entry_price * 0.985) and macd_hist < prev_macd_hist and rsi < 25:
                return TradeSignal(
                    symbol=symbol,
                    action="SELL",
                    confidence=0.80,
                    current_price=close,
                    stop_loss=sl_price,
                    take_profit=tp_price,
                    risk_reward_ratio=rr_ratio,
                    rationale="Trade thesis invalidated: Price broke down with decaying momentum. Exiting early to cut loss.",
                    regime=regime
                )
            return TradeSignal(
                symbol=symbol,
                action="HOLD",
                confidence=0.50,
                current_price=close,
                stop_loss=sl_price,
                take_profit=tp_price,
                risk_reward_ratio=rr_ratio,
                rationale="Position active within normal tolerance bands. Allowing trade to develop.",
                regime=regime
            )

        # 2. Position Entry Evaluation (Currently in cash USDT)
        # Score factors for confluence
        score = 0.0
        reasons = []

        # Criterion A: Trend Structure
        if close > ema_200:
            score += 0.35
            reasons.append("Price above 200 EMA (Long-term Bullish structure)")
        if ema_20 > ema_50:
            score += 0.20
            reasons.append("20 EMA above 50 EMA (Short-term momentum aligned)")

        # Criterion B: Healthy RSI (Not overbought, not in capitulation)
        if 42 <= rsi <= 65:
            score += 0.25
            reasons.append(f"RSI in optimal bullish accumulation zone ({rsi:.1f})")
        elif rsi < 35 and close > ema_200:
            score += 0.20
            reasons.append(f"Oversold pullback in macro uptrend (RSI {rsi:.1f})")

        # Criterion C: MACD Momentum Expansion
        if macd_hist > 0 and macd_hist >= prev_macd_hist:
            score += 0.15
            reasons.append("MACD histogram expanding upwards")

        # Criterion D: Volume Confirmation
        if vol_ratio > 1.1:
            score += 0.10
            reasons.append(f"Volume surge {vol_ratio:.2f}x above average")

        if score >= settings.AI_CONFIDENCE_THRESHOLD:
            return TradeSignal(
                symbol=symbol,
                action="BUY",
                confidence=round(score, 2),
                current_price=close,
                stop_loss=sl_price,
                take_profit=tp_price,
                risk_reward_ratio=rr_ratio,
                rationale="; ".join(reasons),
                regime=regime
            )

        return TradeSignal(
            symbol=symbol,
            action="HOLD",
            confidence=round(score, 2),
            current_price=close,
            stop_loss=sl_price,
            take_profit=tp_price,
            risk_reward_ratio=rr_ratio,
            rationale=f"Insufficient confluence (Score {score:.2f} < Threshold {settings.AI_CONFIDENCE_THRESHOLD}). Waiting for clearer setup.",
            regime=regime
        )

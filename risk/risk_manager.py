"""
Risk Management Engine (Process Over Profit).
Enforces strict capital preservation, unleveraged position sizing,
dynamic ATR stops, and trailing stop protection.
"""

from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone
from config.settings import settings
from core.shariah_guard import ShariahComplianceGuard

@dataclass
class PositionSizeResult:
    is_valid: bool
    quantity: float
    notional_value_usdt: float
    risk_amount_usdt: float
    reason: str

class RiskManager:
    @staticmethod
    def calculate_spot_position_size(
        available_usdt: float,
        current_price: float,
        stop_loss_price: float,
        symbol: str,
        confidence: float = 1.0,
        realized_vol_per_bar: Optional[float] = None,
        drawdown_multiplier: float = 1.0,
    ) -> PositionSizeResult:
        """
        Calculate unleveraged spot position size based on fixed fractional risk,
        then apply best-in-class adaptive overlays:

          1. Fixed-fractional base risk (RISK_PER_TRADE_PERCENT of portfolio).
          2. Maximum allocation cap (MAX_ALLOCATION_PER_TRADE_PERCENT).
          3. Volatility targeting  — scale size inversely with realized vol so a
             calm tape sizes up and a wild tape sizes down (constant risk budget).
          4. Confidence scaling    — higher-conviction setups earn more size.
          5. Drawdown de-risking   — shrink size as the equity curve bleeds.

        Every multiplier is clamped and the result is always the conservative
        minimum of the risk budget and the allocation cap.
        """
        ShariahComplianceGuard.audit_symbol(symbol)

        if available_usdt < 15.0:
            return PositionSizeResult(
                is_valid=False,
                quantity=0.0,
                notional_value_usdt=0.0,
                risk_amount_usdt=0.0,
                reason=f"Available balance ({available_usdt:.2f} USDT) below minimum trade threshold (15 USDT)."
            )

        if stop_loss_price >= current_price:
            return PositionSizeResult(
                is_valid=False,
                quantity=0.0,
                notional_value_usdt=0.0,
                risk_amount_usdt=0.0,
                reason="Stop loss must be placed strictly below current price for Long Spot trade."
            )

        # Circuit-breaker halt: zero multiplier means no new risk at all.
        if drawdown_multiplier <= 0.0:
            return PositionSizeResult(
                is_valid=False,
                quantity=0.0,
                notional_value_usdt=0.0,
                risk_amount_usdt=0.0,
                reason="Position sizing halted by drawdown circuit breaker."
            )

        # --- Adaptive overlay multipliers (all clamped, all <= sane bounds) ---
        multipliers = []

        # Volatility targeting: calmer than target -> size up; wilder -> size down.
        if settings.VOL_TARGET_SIZING_ENABLED and realized_vol_per_bar and realized_vol_per_bar > 0:
            target = settings.TARGET_VOL_PERCENT_PER_BAR / 100.0
            vol_scale = target / realized_vol_per_bar
            vol_scale = max(settings.VOL_SCALE_MIN, min(settings.VOL_SCALE_MAX, vol_scale))
            multipliers.append(vol_scale)

        # Confidence scaling: linear from 1.0 (at threshold) to 1.5 (full conviction).
        if settings.CONFIDENCE_SIZE_SCALING_ENABLED:
            conf = max(0.0, min(1.0, confidence))
            conf_scale = 1.0 + 0.5 * max(0.0, conf - settings.AI_CONFIDENCE_THRESHOLD) / max(
                1e-9, 1.0 - settings.AI_CONFIDENCE_THRESHOLD
            )
            multipliers.append(conf_scale)

        # Drawdown de-risking (tiered 1.0 / 0.5 / 0.25).
        multipliers.append(max(0.0, drawdown_multiplier))

        overlay = 1.0
        for m in multipliers:
            overlay *= m
        # Never let overlays more than double the base risk-on budget.
        overlay = min(2.0, overlay)

        # Capital to risk on this trade (e.g., 1.5% of portfolio), scaled by overlays
        base_risk_usdt = available_usdt * (settings.RISK_PER_TRADE_PERCENT / 100.0)
        risk_amount_usdt = base_risk_usdt * overlay
        risk_per_unit = current_price - stop_loss_price

        # Ideal quantity based on stop distance
        ideal_quantity = risk_amount_usdt / risk_per_unit

        # Max allocation cap (e.g., max 20% of total available USDT into one asset)
        max_notional_cap = available_usdt * (settings.MAX_ALLOCATION_PER_TRADE_PERCENT / 100.0)
        max_quantity_by_cap = max_notional_cap / current_price

        # The actual quantity is the conservative minimum
        final_quantity = min(ideal_quantity, max_quantity_by_cap)
        final_notional = final_quantity * current_price

        # Binance spot min notional rule (~10 USDT)
        if final_notional < 10.0:
            return PositionSizeResult(
                is_valid=False,
                quantity=0.0,
                notional_value_usdt=0.0,
                risk_amount_usdt=0.0,
                reason=f"Position size notional ({final_notional:.2f} USDT) is below Binance minimum 10 USDT."
            )

        return PositionSizeResult(
            is_valid=True,
            quantity=round(final_quantity, 6),
            notional_value_usdt=round(final_notional, 2),
            risk_amount_usdt=round(risk_amount_usdt, 2),
            reason=(
                f"Position sizing approved (overlay x{overlay:.2f}; "
                f"base risk {base_risk_usdt:.2f} USDT) within Shariah and risk limits."
            )
        )

    @staticmethod
    def evaluate_position_exit(
        entry_price: float,
        current_price: float,
        stop_loss: float,
        take_profit: float,
        highest_price_seen: float,
        entry_time: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Evaluate if an open spot position should be closed based on:
        1. Hard Stop-Loss
        2. Take-Profit target
        3. Trailing Stop
        """
        # 1. Hard Stop Loss
        if current_price <= stop_loss:
            loss_pct = ((current_price - entry_price) / entry_price) * 100.0
            return True, f"STOP_LOSS_HIT: Price {current_price:.4f} hit SL {stop_loss:.4f} ({loss_pct:.2f}%)"

        # 2. Take Profit Target
        if current_price >= take_profit:
            profit_pct = ((current_price - entry_price) / entry_price) * 100.0
            return True, f"TAKE_PROFIT_HIT: Price {current_price:.4f} hit TP {take_profit:.4f} (+{profit_pct:.2f}%)"

        # 3. Trailing Stop Logic (if price pumped > activation %, don't give back more than 1 ATR)
        # STRICT_SL_TP_EXIT_ONLY: trailing stop is disabled as a sale trigger — routine
        # positions close ONLY via the pre-committed SL/TP above.
        if settings.STRICT_SL_TP_EXIT_ONLY:
            return False, "HOLD"

        profit_ratio = (highest_price_seen - entry_price) / entry_price
        activation_ratio = settings.TRAILING_STOP_ACTIVATION_PERCENT / 100.0

        if profit_ratio >= activation_ratio:
            # Trailing stop trails TRAILING_STOP_DISTANCE_PERCENT below highest price seen
            trail_dist = settings.TRAILING_STOP_DISTANCE_PERCENT / 100.0
            trailing_stop_level = highest_price_seen * (1.0 - trail_dist)
            if current_price <= trailing_stop_level:
                locked_profit_pct = ((current_price - entry_price) / entry_price) * 100.0
                return True, f"TRAILING_STOP_HIT: Trailing stop triggered at {current_price:.4f} (Locked in +{locked_profit_pct:.2f}%)"

        return False, "HOLD"

    @staticmethod
    def time_stop_hit(entry_time: Optional[str]) -> Tuple[bool, str]:
        """
        Time-based exit (dead-capital recycling). In crypto, an altcoin that has
        not moved favourably within its expected horizon rarely recovers — the
        capital is better redeployed. Disabled when MAX_HOLD_HOURS <= 0.
        Fails OPEN (no exit) when the entry time is missing/unparseable.
        """
        if settings.MAX_HOLD_HOURS <= 0 or not entry_time:
            return False, "HOLD"
        try:
            dt = datetime.fromisoformat(str(entry_time))
        except (TypeError, ValueError):
            return False, "HOLD"
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        held_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
        if held_hours >= settings.MAX_HOLD_HOURS:
            return True, (
                f"TIME_STOP_HIT: held {held_hours:.1f}h >= max "
                f"{settings.MAX_HOLD_HOURS}h — recycling dead capital"
            )
        return False, "HOLD"

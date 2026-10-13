"""
Portfolio-Level Risk Engine (institutional-style guards).

Single-trade risk controls (stop-loss, per-trade sizing) prevent one bad trade
from hurting you. They do NOT prevent "death by a thousand correlated cuts" —
during stress, crypto correlations spike to 0.85+ and a "diversified" book
behaves like one leveraged position. This module adds the portfolio layer that
best-in-class bots run on top of per-trade risk:

1. Total exposure cap          — never fully deploy; keep dry powder.
2. Portfolio heat cap          — aggregate open risk across all positions.
3. Correlation concentration   — cap capital in assets that move together.
4. Drawdown circuit breaker    — tiered de-risking, then a full kill switch
                                 measured from the equity high-water mark.
"""

from typing import Dict, Any, List, Optional, Tuple
import os
import numpy as np
import pandas as pd

from config.settings import settings


class PortfolioRiskEngine:
    """Stateful (per-process) portfolio guard. Pure/stateless helpers are static."""

    @staticmethod
    def compute_drawdown(equity_curve: List[float]) -> Tuple[float, float]:
        """
        Return (current_drawdown_pct, high_water_mark) measured from the running
        equity peak — NOT from starting capital. This prevents the risk engine
        from "resetting" its perception after a recovery.
        """
        if not equity_curve:
            return 0.0, 0.0
        peak = equity_curve[0]
        current = equity_curve[-1]
        hwm = peak
        for v in equity_curve:
            if v > hwm:
                hwm = v
        if hwm <= 0:
            return 0.0, hwm
        dd = max(0.0, (hwm - current) / hwm * 100.0)
        return dd, hwm

    @staticmethod
    def drawdown_size_multiplier(drawdown_pct: float) -> Tuple[float, str]:
        """
        Tiered de-risking based on current drawdown:
          < reduce_half            -> 1.0x (normal)
          >= reduce_half           -> 0.5x
          >= reduce_quarter        -> 0.25x
          >= halt                  -> 0.0x (halted, kill switch)
        """
        if not settings.DRAWDOWN_BREAKER_ENABLED:
            return 1.0, "breaker disabled"
        if drawdown_pct >= settings.DRAWDOWN_HALT_PERCENT:
            return 0.0, (
                f"KILL SWITCH: drawdown {drawdown_pct:.1f}% >= halt "
                f"{settings.DRAWDOWN_HALT_PERCENT}% — entries halted"
            )
        if drawdown_pct >= settings.DRAWDOWN_REDUCE_QUARTER_PERCENT:
            return 0.25, f"drawdown {drawdown_pct:.1f}% -> sizes at 25%"
        if drawdown_pct >= settings.DRAWDOWN_REDUCE_HALF_PERCENT:
            return 0.5, f"drawdown {drawdown_pct:.1f}% -> sizes at 50%"
        return 1.0, f"drawdown {drawdown_pct:.1f}% within normal band"

    @staticmethod
    def estimate_correlation(series_a: List[float], series_b: List[float]) -> Optional[float]:
        """
        Pearson correlation of two aligned return series. Returns None when the
        estimate is not meaningful (insufficient or degenerate data) so callers
        can fail OPEN (allow the trade) rather than block on noise.
        """
        if not series_a or not series_b:
            return None
        n = min(len(series_a), len(series_b))
        if n < 20:
            return None
        a = np.asarray(series_a[-n:], dtype=float)
        b = np.asarray(series_b[-n:], dtype=float)
        if np.std(a) < 1e-12 or np.std(b) < 1e-12:
            return None
        corr = float(np.corrcoef(a, b)[0, 1])
        if np.isnan(corr):
            return None
        return corr

    @staticmethod
    def returns_from_closes(closes: List[float]) -> List[float]:
        """Simple period returns from a close-price series."""
        if not closes or len(closes) < 2:
            return []
        s = pd.Series(closes, dtype=float)
        return s.pct_change().dropna().tolist()

    @staticmethod
    def correlated_exposure_pct(
        candidate_symbol: str,
        candidate_returns: List[float],
        open_positions: List[Dict[str, Any]],
        position_returns: Dict[str, List[float]],
        equity: float,
    ) -> Tuple[float, List[str]]:
        """
        Percent of equity already committed to assets that correlate with the
        candidate above CORRELATION_THRESHOLD. Fails OPEN (returns 0.0) whenever
        a correlation cannot be reliably estimated.
        """
        if equity <= 0:
            return 0.0, []
        corr_exposure = 0.0
        mates: List[str] = []
        for pos in open_positions:
            sym = pos.get("symbol", "")
            if sym == candidate_symbol:
                continue
            other_returns = position_returns.get(sym)
            if not other_returns:
                continue
            corr = PortfolioRiskEngine.estimate_correlation(candidate_returns, other_returns)
            if corr is None or corr < settings.CORRELATION_THRESHOLD:
                continue
            notional = float(pos.get("quantity", 0.0)) * float(pos.get("entry_price", 0.0))
            corr_exposure += notional
            mates.append(sym)
        return round(corr_exposure / equity * 100.0, 2), mates

    @staticmethod
    def total_exposure_pct(open_positions: List[Dict[str, Any]], equity: float) -> float:
        if equity <= 0:
            return 0.0
        total = sum(
            float(p.get("quantity", 0.0)) * float(p.get("entry_price", 0.0))
            for p in open_positions
        )
        return round(total / equity * 100.0, 2)

    @staticmethod
    def portfolio_heat_pct(open_positions: List[Dict[str, Any]], equity: float) -> float:
        """
        Aggregate open risk: for each position, (entry - stop)/entry * notional,
        summed as a percent of equity. This is the true "money at risk" number.
        """
        if equity <= 0:
            return 0.0
        heat = 0.0
        for p in open_positions:
            entry = float(p.get("entry_price", 0.0))
            stop = float(p.get("stop_loss", 0.0))
            qty = float(p.get("quantity", 0.0))
            if entry <= 0 or stop <= 0 or stop >= entry:
                continue
            risk_per_unit = entry - stop
            heat += risk_per_unit * qty
        return round(heat / equity * 100.0, 2)


class KillSwitch:
    """
    File-backed halt state. Once tripped (drawdown >= halt), new entries stay
    blocked across restarts until a human clears the state file. Live entries
    and exit management are never blocked by this — only new risk.
    """

    def __init__(self, path: Optional[str] = None):
        self.path = path or settings.KILL_SWITCH_ARMED_FILE

    def is_halted(self) -> bool:
        try:
            if not os.path.exists(self.path):
                return False
            with open(self.path, "r", encoding="utf-8") as f:
                return f.read().strip().upper().startswith("HALT")
        except Exception:
            # Fail-safe: if we cannot read state, do not block trading on IO error.
            return False

    def trip(self, reason: str) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(f"HALT\n{reason}\n")

    def clear(self) -> None:
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
        except Exception:
            pass

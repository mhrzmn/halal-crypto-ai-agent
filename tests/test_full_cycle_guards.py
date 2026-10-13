"""
Integration smoke test: a full scan cycle must run cleanly with the new
portfolio-level guards (drawdown breaker, exposure/heat caps, correlation gate,
time stop) wired in — using a stubbed network, no keys, no funds.
"""

import os
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings
from execution.bot_engine import BotEngine
from storage.database import Database


class StubClient:
    """Deterministic OHLCV + prices, no network."""

    def __init__(self, price=100.0, closes=None):
        self.price = price
        self._closes = closes

    def get_ticker_price(self, symbol):
        return self.price

    def get_klines(self, symbol, interval="4h", limit=260):
        if self._closes is not None:
            closes = self._closes[-limit:]
        else:
            rng = np.random.RandomState(7)
            closes = 100 + np.cumsum(rng.randn(limit))
        n = len(closes)
        idx = pd.date_range("2026-06-01", periods=n, freq="4h")
        return pd.DataFrame({
            "open": closes, "high": np.array(closes) + 1.0,
            "low": np.array(closes) - 1.0, "close": closes,
            "volume": np.ones(n) * 10,
            "close_time": [t - pd.Timedelta(hours=4) for t in idx],
        }, index=idx)


class TestFullCycleWithGuards(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db = Database(self._tmp.name)
        # Fresh kill-switch state for the test workspace
        self._ks_path = os.path.join(tempfile.gettempdir(), "ks_test.state")
        self._old_ks = settings.KILL_SWITCH_ARMED_FILE
        settings.KILL_SWITCH_ARMED_FILE = self._ks_path
        if os.path.exists(self._ks_path):
            os.remove(self._ks_path)

    def tearDown(self):
        settings.KILL_SWITCH_ARMED_FILE = self._old_ks
        if os.path.exists(self._ks_path):
            os.remove(self._ks_path)
        # Windows may still hold the sqlite handle; tolerate cleanup failure.
        if os.path.exists(self._tmp.name):
            try:
                os.remove(self._tmp.name)
            except (PermissionError, OSError):
                pass

    def _engine(self, price=100.0):
        eng = BotEngine(binance_client=StubClient(price), database=self.db)
        return eng

    def test_cycle_runs_and_reports_guards(self):
        eng = self._engine()
        out = eng.scan_and_execute_cycle()
        self.assertIn("portfolio_guards", out)
        g = out["portfolio_guards"]
        for key in ("equity", "drawdown_pct", "size_multiplier", "halted",
                    "total_exposure_pct", "portfolio_heat_pct"):
            self.assertIn(key, g)
        self.assertFalse(g["halted"])
        # No crash, no unexpected errors from the guard layer
        self.assertFalse(any("Portfolio guard" in e for e in out["errors"]))

    def test_kill_switch_halts_entries(self):
        eng = self._engine()
        eng.kill_switch.trip("unit-test halt")
        out = eng.scan_and_execute_cycle()
        self.assertTrue(out["portfolio_guards"]["halted"])
        # No buy should be executed while halted
        buys = [a for a in out["actions_taken"] if "BUY" in a.get("type", "")]
        self.assertEqual(len(buys), 0)

    def test_drawdown_breaker_series_is_respected(self):
        # Seed an equity curve with a large peak -> drawdown -> reduced multiplier
        self.db.record_portfolio_snapshot(1000.0, 1000.0, 0.0)
        self.db.record_portfolio_snapshot(1200.0, 1200.0, 0.0)
        self.db.record_portfolio_snapshot(1000.0, 1000.0, 0.0)  # ~16.7% DD from 1200
        eng = self._engine()
        g = eng.evaluate_portfolio_guards()
        self.assertGreaterEqual(g["drawdown_pct"], settings.DRAWDOWN_HALT_PERCENT)
        self.assertTrue(g["halted"])

    def test_regime_context_present_in_snapshot(self):
        eng = self._engine()
        df = eng.client.get_klines("BTCUSDT")
        from strategy.indicators import IndicatorEngine
        snap = IndicatorEngine.get_latest_snapshot(
            IndicatorEngine.calculate_all(eng._signal_frame(df))
        )
        for key in ("adx_14", "chop_14", "di_plus", "di_minus", "is_choppy", "realized_vol_20"):
            self.assertIn(key, snap)


if __name__ == "__main__":
    unittest.main()

"""Tests for portfolio-level risk controls added in the upgrade."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings
from risk.portfolio_risk import PortfolioRiskEngine, KillSwitch
from risk.risk_manager import RiskManager


class TestPortfolioRisk(unittest.TestCase):
    def test_drawdown_uses_high_water_mark(self):
        dd, hwm = PortfolioRiskEngine.compute_drawdown([1000.0, 1100.0, 1045.0])
        self.assertEqual(hwm, 1100.0)
        self.assertAlmostEqual(dd, 5.0, places=6)

    def test_tiered_drawdown_multiplier(self):
        old = (
            settings.DRAWDOWN_REDUCE_HALF_PERCENT,
            settings.DRAWDOWN_REDUCE_QUARTER_PERCENT,
            settings.DRAWDOWN_HALT_PERCENT,
        )
        try:
            self.assertEqual(PortfolioRiskEngine.drawdown_size_multiplier(2.0)[0], 1.0)
            self.assertEqual(PortfolioRiskEngine.drawdown_size_multiplier(5.0)[0], 0.5)
            self.assertEqual(PortfolioRiskEngine.drawdown_size_multiplier(10.0)[0], 0.25)
            self.assertEqual(PortfolioRiskEngine.drawdown_size_multiplier(15.0)[0], 0.0)
        finally:
            settings.DRAWDOWN_REDUCE_HALF_PERCENT = old[0]
            settings.DRAWDOWN_REDUCE_QUARTER_PERCENT = old[1]
            settings.DRAWDOWN_HALT_PERCENT = old[2]

    def test_correlation_estimate_and_exposure(self):
        a = [0.01, 0.02, -0.01, 0.03] * 10
        b = [x * 1.1 for x in a]
        self.assertGreater(PortfolioRiskEngine.estimate_correlation(a, b), 0.99)
        positions = [{"symbol": "BTCUSDT", "quantity": 1.0, "entry_price": 300.0}]
        pct, mates = PortfolioRiskEngine.correlated_exposure_pct(
            "ETHUSDT", a, positions, {"BTCUSDT": b}, 1000.0
        )
        self.assertEqual(pct, 30.0)
        self.assertEqual(mates, ["BTCUSDT"])

    def test_kill_switch_persists_until_cleared(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "kill.state")
            ks = KillSwitch(path)
            self.assertFalse(ks.is_halted())
            ks.trip("test halt")
            self.assertTrue(ks.is_halted())
            ks.clear()
            self.assertFalse(ks.is_halted())

    def test_volatility_and_drawdown_scale_position(self):
        base = RiskManager.calculate_spot_position_size(
            1000.0, 100.0, 95.0, "BTCUSDT", confidence=0.8,
            realized_vol_per_bar=None, drawdown_multiplier=1.0
        )
        reduced = RiskManager.calculate_spot_position_size(
            1000.0, 100.0, 95.0, "BTCUSDT", confidence=0.8,
            realized_vol_per_bar=0.10, drawdown_multiplier=0.5
        )
        self.assertTrue(base.is_valid)
        self.assertTrue(reduced.is_valid)
        self.assertLessEqual(reduced.risk_amount_usdt, base.risk_amount_usdt)

    def test_drawdown_halt_blocks_position(self):
        result = RiskManager.calculate_spot_position_size(
            1000.0, 100.0, 95.0, "BTCUSDT", drawdown_multiplier=0.0
        )
        self.assertFalse(result.is_valid)
        self.assertIn("halted", result.reason.lower())


if __name__ == "__main__":
    unittest.main()

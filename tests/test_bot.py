"""
Unit & Integration Tests for Halal Crypto AI Spot Agent.
"""

import unittest
import pandas as pd
import numpy as np

from config.settings import settings
from config.halal_whitelist import is_pair_halal, is_asset_halal, HARAM_BLACKLIST
from core.shariah_guard import ShariahComplianceGuard, ShariahViolationError
from strategy.indicators import IndicatorEngine
from strategy.signals import SignalGenerator
from risk.risk_manager import RiskManager
from storage.database import Database

class TestShariahCompliance(unittest.TestCase):
    def test_halal_screening_whitelist(self):
        self.assertTrue(is_asset_halal("BTC"))
        self.assertTrue(is_asset_halal("ETH"))
        self.assertTrue(is_asset_halal("SOL"))
        self.assertTrue(is_pair_halal("BTCUSDT"))
        self.assertTrue(is_pair_halal("SOLUSDT"))

    def test_haram_assets_blocked(self):
        self.assertFalse(is_asset_halal("AAVE"))  # Riba lending
        self.assertFalse(is_asset_halal("DOGE"))  # Speculative meme
        self.assertFalse(is_pair_halal("AAVEUSDT"))
        with self.assertRaises(ShariahViolationError):
            ShariahComplianceGuard.audit_symbol("AAVEUSDT")

    def test_leverage_prohibited(self):
        # Leverage > 1.0 must raise ShariahViolationError
        with self.assertRaises(ShariahViolationError):
            ShariahComplianceGuard.audit_order_type("BUY", "MARKET", leverage=2.0)
        # Spot 1.0x should pass
        ShariahComplianceGuard.audit_order_type("BUY", "MARKET", leverage=1.0)

    def test_derivatives_endpoints_blocked(self):
        with self.assertRaises(ShariahViolationError):
            ShariahComplianceGuard.sanitize_api_endpoint("/fapi/v1/order")
        with self.assertRaises(ShariahViolationError):
            ShariahComplianceGuard.sanitize_api_endpoint("/sapi/v1/margin/order")
        # Spot endpoint passes
        ShariahComplianceGuard.sanitize_api_endpoint("/api/v3/order")

class TestIndicatorsAndSignals(unittest.TestCase):
    def setUp(self):
        # Generate synthetic OHLCV data
        np.random.seed(42)
        dates = pd.date_range("2026-01-01", periods=100, freq="15min")
        prices = 100 + np.cumsum(np.random.randn(100) * 0.5)
        self.df = pd.DataFrame({
            "open": prices,
            "high": prices + 0.5,
            "low": prices - 0.5,
            "close": prices + 0.1,
            "volume": np.random.randint(10, 100, size=100),
            "quote_asset_volume": 1000.0
        }, index=dates)

    def test_indicator_calculations(self):
        res = IndicatorEngine.calculate_all(self.df)
        self.assertIn("ema_20", res.columns)
        self.assertIn("ema_50", res.columns)
        self.assertIn("ema_200", res.columns)
        self.assertIn("rsi_14", res.columns)
        self.assertIn("atr_14", res.columns)
        snapshot = IndicatorEngine.get_latest_snapshot(res)
        self.assertIn("regime", snapshot)
        self.assertIn("close", snapshot)

    def test_signal_generation(self):
        res = IndicatorEngine.calculate_all(self.df)
        snapshot = IndicatorEngine.get_latest_snapshot(res)
        signal = SignalGenerator.generate_signal("BTCUSDT", snapshot)
        self.assertIn(signal.action, ["BUY", "SELL", "HOLD"])
        self.assertGreaterEqual(signal.confidence, 0.0)

class TestRiskManagement(unittest.TestCase):
    def test_position_sizing(self):
        res = RiskManager.calculate_spot_position_size(
            available_usdt=1000.0,
            current_price=100.0,
            stop_loss_price=95.0,
            symbol="BTCUSDT"
        )
        self.assertTrue(res.is_valid)
        self.assertLessEqual(res.notional_value_usdt, 200.0)  # Max 20% cap

    def test_exit_conditions(self):
        # Stop loss hit
        should_exit, reason = RiskManager.evaluate_position_exit(
            entry_price=100.0,
            current_price=94.0,
            stop_loss=95.0,
            take_profit=110.0,
            highest_price_seen=100.0
        )
        self.assertTrue(should_exit)
        self.assertIn("STOP_LOSS_HIT", reason)

class TestStrictExitPolicy(unittest.TestCase):
    """Strict SL/TP-only mode: trailing stops and AI exits must never close a position early."""

    def setUp(self):
        self._prev = settings.STRICT_SL_TP_EXIT_ONLY
        settings.STRICT_SL_TP_EXIT_ONLY = True

    def tearDown(self):
        settings.STRICT_SL_TP_EXIT_ONLY = self._prev

    def test_trailing_stop_disabled_in_strict_mode(self):
        # Price pumped 10% (well past trailing activation) then pulled back 3%.
        # In strict mode this must NOT exit — only SL/TP may close.
        should_exit, reason = RiskManager.evaluate_position_exit(
            entry_price=100.0,
            current_price=107.0,
            stop_loss=95.0,
            take_profit=120.0,
            highest_price_seen=110.0
        )
        self.assertFalse(should_exit)
        self.assertEqual(reason, "HOLD")

    def test_sl_tp_still_fire_in_strict_mode(self):
        sl_exit, _ = RiskManager.evaluate_position_exit(100.0, 94.0, 95.0, 120.0, 100.0)
        tp_exit, _ = RiskManager.evaluate_position_exit(100.0, 121.0, 95.0, 120.0, 121.0)
        self.assertTrue(sl_exit)
        self.assertTrue(tp_exit)

    def test_ai_exit_blocked_in_strict_mode(self):
        from execution.bot_engine import BotEngine
        allowed, reason = BotEngine._ai_exit_allowed(100.0, 110.0, "2026-10-01T00:00:00+00:00")
        self.assertFalse(allowed)
        self.assertIn("strict", reason.lower())

    def test_ai_exit_fails_closed_on_bad_timestamp(self):
        settings.STRICT_SL_TP_EXIT_ONLY = False
        from execution.bot_engine import BotEngine
        allowed, reason = BotEngine._ai_exit_allowed(100.0, 110.0, "not-a-timestamp")
        self.assertFalse(allowed)
        self.assertIn("fail-closed", reason)

class TestConfirmedCandles(unittest.TestCase):
    def test_forming_last_candle_is_dropped(self):
        import pandas as pd
        now = pd.Timestamp.utcnow().tz_localize(None)
        df = pd.DataFrame({
            "open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0],
            "close": [1.0, 2.0], "volume": [1.0, 1.0],
            "close_time": [now - pd.Timedelta(hours=8), now + pd.Timedelta(hours=3)]
        })
        confirmed = IndicatorEngine.confirmed_candles(df)
        self.assertEqual(len(confirmed), 1)

    def test_closed_last_candle_is_kept(self):
        import pandas as pd
        now = pd.Timestamp.utcnow().tz_localize(None)
        df = pd.DataFrame({
            "open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0],
            "close": [1.0, 2.0], "volume": [1.0, 1.0],
            "close_time": [now - pd.Timedelta(hours=8), now - pd.Timedelta(hours=1)]
        })
        confirmed = IndicatorEngine.confirmed_candles(df)
        self.assertEqual(len(confirmed), 2)

class TestDatabase(unittest.TestCase):
    def test_paper_trade_lifecycle(self):
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            temp_db = f.name
        try:
            db = Database(temp_db)
            initial = db.get_paper_balance()
            self.assertEqual(initial, 1000.0)

            # Save active position
            db.save_active_position("BTCUSDT", 0.1, 80000.0, 78000.0, 84000.0, is_paper=True)
            pos = db.get_active_position("BTCUSDT")
            self.assertIsNotNone(pos)
            self.assertEqual(pos["quantity"], 0.1)

            # Close position with profit
            closed = db.close_active_position("BTCUSDT", 82000.0, "TAKE_PROFIT_HIT")
            self.assertIsNotNone(closed)
            self.assertEqual(closed["pnl_usdt"], 200.0)

            # Active position should now be gone
            self.assertIsNone(db.get_active_position("BTCUSDT"))
        finally:
            if os.path.exists(temp_db):
                try:
                    os.remove(temp_db)
                except Exception:
                    pass

class TestAIPredictorCustomEndpoint(unittest.TestCase):
    def test_extract_json_with_think_tags_and_markdown(self):
        from strategy.ai_predictor import AIPredictor
        predictor = AIPredictor(
            provider="custom",
            custom_base_url="https://api.deepseek.com/v1",
            custom_model_name="deepseek-chat",
            custom_api_key="test-key"
        )
        self.assertEqual(predictor.provider, "custom")
        self.assertEqual(predictor.custom_base_url, "https://api.deepseek.com/v1")
        self.assertEqual(predictor.custom_model_name, "deepseek-chat")

        # Test reasoning model output with <think>...</think>
        raw_output = """
        <think>
        Analyzing BTCUSDT on 15m. EMA 20 is above EMA 50. RSI is 54. Vol expansion.
        Bullish continuation is likely.
        </think>
        ```json
        {
          "predicted_direction": "BULLISH_EXPANSION",
          "action": "BUY",
          "confidence": 0.88,
          "target_price": 86000.0,
          "invalidation_price": 81000.0,
          "next_recheck_minutes": 25,
          "thesis": "Bullish trend structure confirmed above EMA 50 with strong volume."
        }
        ```
        """
        parsed = predictor._extract_json(raw_output)
        self.assertEqual(parsed["action"], "BUY")
        self.assertEqual(parsed["predicted_direction"], "BULLISH_EXPANSION")
        self.assertEqual(parsed["confidence"], 0.88)
        self.assertEqual(parsed["next_recheck_minutes"], 25)

if __name__ == "__main__":
    unittest.main()

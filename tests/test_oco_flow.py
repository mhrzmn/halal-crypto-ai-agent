"""
Mock-based verification of the exchange-side OCO protection flow.

Stubs the Binance HTTP layer entirely (no keys, no network, no funds) and
verifies OUR logic end-to-end:
  1. Live buy with PROTECT_WITH_EXCHANGE_OCO -> OCO placed with correct levels,
     orderListId persisted to the position row.
  2. Live sell on a protected position -> OCO cancelled BEFORE the sell order.
  3. Offline-fill reconciliation -> wallet empty + protection id present =>
     engine syncs DB (EXCHANGE_RECONCILE) instead of double-selling.

This validates our code paths only. True exchange behavior still requires a
Binance Spot Testnet run.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings
from execution.bot_engine import BotEngine
from storage.database import Database


class FakeBinanceClient:
    """Records calls and returns canned Binance-style responses."""

    def __init__(self, base_balance=0.0):
        self.calls = []
        self.base_balance = base_balance

    def place_spot_order(self, symbol, side, quantity, order_type="MARKET", price=None):
        self.calls.append(("place_spot_order", side, symbol, quantity))
        return {"orderId": 1001, "executedQty": str(quantity), "fills": []}

    def get_exchange_filters(self, symbol):
        return {"step_size": 0.01, "min_notional": 10.0, "tick_size": 0.01}

    @staticmethod
    def round_to_step(qty, step):
        import math
        return math.floor(qty / step) * step

    @staticmethod
    def round_to_tick(price, tick, direction="nearest"):
        import math
        ratio = price / tick
        if direction == "up":
            return math.ceil(ratio) * tick
        if direction == "down":
            return math.floor(ratio) * tick
        return round(ratio) * tick

    def place_spot_oco_sell(self, symbol, quantity, take_profit_price, stop_price, stop_limit_price):
        self.calls.append(("place_spot_oco_sell", symbol, quantity,
                           take_profit_price, stop_price, stop_limit_price))
        return {"orderListId": 777}

    def cancel_order_list(self, symbol, order_list_id):
        self.calls.append(("cancel_order_list", symbol, order_list_id))
        return {"orderListId": order_list_id, "listStatusType": "ALL_DONE"}

    def get_open_order_lists(self):
        return []

    def get_spot_account_balance(self, asset):
        self.calls.append(("get_balance", asset))
        return self.base_balance if asset != "USDT" else 10_000.0

    def get_ticker_price(self, symbol):
        return 100.0

    def get_klines(self, symbol, interval="4h", limit=260):
        raise RuntimeError("network stubbed out in OCO flow tests")


class TestOCOFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Database(db_path=self.tmp.name)
        self.client = FakeBinanceClient()
        self.engine = BotEngine(binance_client=self.client, database=self.db)
        self.engine.is_paper = False  # simulate live mode with mocked client
        self._oco_patch = patch.object(settings, "PROTECT_WITH_EXCHANGE_OCO", True)
        self._oco_patch.start()

    def tearDown(self):
        self._oco_patch.stop()
        try:
            os.unlink(self.tmp.name)
        except PermissionError:
            pass  # Windows: sqlite handle released on GC; temp file is harmless

    def test_buy_attaches_oco_and_persists_id(self):
        res = self.engine._execute_buy(
            symbol="BTCUSDT", quantity=0.1, price=100.0,
            stop_loss=90.0, take_profit=120.0, rationale="mock test"
        )
        self.assertEqual(res["protection_order_id"], 777)
        oco_calls = [c for c in self.client.calls if c[0] == "place_spot_oco_sell"]
        self.assertEqual(len(oco_calls), 1)
        _, sym, qty, tp, stop, stop_limit = oco_calls[0]
        self.assertEqual(sym, "BTCUSDT")
        self.assertAlmostEqual(qty, 0.1)
        self.assertAlmostEqual(tp, 120.0)
        self.assertAlmostEqual(stop, 90.0)
        self.assertLess(stop_limit, stop)  # stop-limit below trigger for fill odds
        pos = self.db.get_active_position("BTCUSDT")
        self.assertEqual(str(pos["protection_order_id"]), "777")

    def test_sell_cancels_oco_before_selling(self):
        self.engine._execute_buy(
            symbol="BTCUSDT", quantity=0.1, price=100.0,
            stop_loss=90.0, take_profit=120.0, rationale="mock test"
        )
        self.client.base_balance = 1.0  # we "own" BTC now
        self.client.calls.clear()

        self.engine._execute_sell("BTCUSDT", 0.1, 120.0, "TAKE_PROFIT_HIT")

        order = [c[0] for c in self.client.calls]
        self.assertIn("cancel_order_list", order)
        sell_idx = order.index("place_spot_order")
        cancel_idx = order.index("cancel_order_list")
        self.assertLess(cancel_idx, sell_idx, "OCO must be cancelled before the sell order")
        cancel_call = [c for c in self.client.calls if c[0] == "cancel_order_list"][0]
        self.assertEqual(str(cancel_call[2]), "777")

    def test_offline_oco_fill_reconciles_without_double_sell(self):
        self.engine._execute_buy(
            symbol="BTCUSDT", quantity=0.1, price=100.0,
            stop_loss=90.0, take_profit=120.0, rationale="mock test"
        )
        # Simulate: OCO filled while bot was offline -> wallet BTC gone
        self.client.base_balance = 0.0
        self.client.calls.clear()

        results = self.engine.scan_and_execute_cycle()

        reconcile = [a for a in results["actions_taken"] if a["type"] == "EXCHANGE_RECONCILE"]
        self.assertEqual(len(reconcile), 1)
        self.assertIsNone(self.db.get_active_position("BTCUSDT"),
                          "Position must be closed in DB after reconciliation")
        # No fresh sell order may be placed during reconciliation
        self.assertNotIn(("place_spot_order", "SELL", "BTCUSDT", 0.1),
                         [tuple(c[:4]) for c in self.client.calls if c[0] == "place_spot_order"])


if __name__ == "__main__":
    unittest.main()

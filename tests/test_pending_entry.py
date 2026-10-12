"""
Pending (limit-zone) entry flow tests — no network, no funds.

Verifies:
  1. _queue_pending_entry computes a zone below market, shifts SL/TP down by
     the same delta (preserving R:R), and persists the order.
  2. Zone already at market -> returns None (caller buys immediately).
  3. Price trades into the zone -> paper buy executes, order marked FILLED.
  4. Price breaks the stop before fill -> order CANCELLED, no trade.
  5. Order past expiry -> EXPIRED, no trade.
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution.bot_engine import BotEngine
from storage.database import Database


class FakeClient:
    def __init__(self, price=100.0):
        self.price = price

    def get_ticker_price(self, symbol):
        return self.price


def make_snapshot(close=100.0, atr=4.0, ema20=99.0):
    return {"close": close, "atr_14": atr, "ema_20": ema20}


def make_assessment(sl=92.0, tp=120.0, conf=0.85):
    return SimpleNamespace(
        confidence=conf,
        recommended_stop_loss=sl,
        recommended_take_profit=tp,
        rationale="test setup"
    )


class TestPendingEntries(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Database(db_path=self.tmp.name)
        self.client = FakeClient(price=100.0)
        self.engine = BotEngine(binance_client=self.client, database=self.db)
        self.engine.is_paper = True
        self.db.update_paper_balance(10_000.0)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except PermissionError:
            pass

    def test_queue_computes_zone_and_shifts_levels(self):
        res = self.engine._queue_pending_entry(
            "BTCUSDT", make_snapshot(), make_assessment()
        )
        self.assertIsNotNone(res)
        # zone = min(ema20=99, 100 - 0.75*4 = 97) -> 97
        self.assertAlmostEqual(res["target_entry"], 97.0, places=4)
        # SL/TP shifted down by delta = 100 - 97 = 3
        self.assertAlmostEqual(res["stop_loss"], 89.0, places=4)
        self.assertAlmostEqual(res["take_profit"], 117.0, places=4)
        rows = self.db.get_pending_entries()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "BTCUSDT")
        self.assertEqual(rows[0]["status"], "PENDING")

    def test_queue_returns_none_when_zone_at_market(self):
        # ema20 above close and shallow ATR -> zone ~ market
        res = self.engine._queue_pending_entry(
            "BTCUSDT", make_snapshot(close=100.0, atr=0.001, ema20=101.0),
            make_assessment()
        )
        self.assertIsNone(res)
        self.assertEqual(self.db.get_pending_entries(), [])

    def _seed_pending(self):
        self.engine._queue_pending_entry("BTCUSDT", make_snapshot(), make_assessment())
        return self.db.get_pending_entries()[0]

    def test_fill_when_price_reaches_zone(self):
        self._seed_pending()
        self.client.price = 96.5  # below zone 97
        res = self.engine._process_pending_entry(
            self.db.get_pending_entries()[0], available_usdt=10_000.0, open_count=0
        )
        self.assertIsNotNone(res)
        self.assertIn("PENDING_", res["type"])
        pos = self.db.get_active_position("BTCUSDT")
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos["stop_loss"], 89.0, places=4)
        self.assertEqual(self.db.get_pending_entries(), [])  # no longer PENDING
        rows = self.db.get_pending_entries(status="FILLED")
        self.assertEqual(len(rows), 1)

    def test_waits_when_price_above_zone(self):
        self._seed_pending()
        self.client.price = 98.0  # above zone 97
        res = self.engine._process_pending_entry(
            self.db.get_pending_entries()[0], available_usdt=10_000.0, open_count=0
        )
        self.assertIsNone(res)
        self.assertIsNone(self.db.get_active_position("BTCUSDT"))
        self.assertEqual(len(self.db.get_pending_entries()), 1)

    def test_cancels_when_stop_breaks_before_fill(self):
        self._seed_pending()
        self.client.price = 88.0  # below SL 89
        res = self.engine._process_pending_entry(
            self.db.get_pending_entries()[0], available_usdt=10_000.0, open_count=0
        )
        self.assertIsNone(res)
        self.assertIsNone(self.db.get_active_position("BTCUSDT"))
        self.assertEqual(len(self.db.get_pending_entries(status="CANCELLED")), 1)

    def test_expires_stale_order(self):
        self._seed_pending()
        pending = self.db.get_pending_entries()[0]
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with self.db._get_connection() as conn:
            conn.execute("UPDATE pending_entries SET expires_at = ? WHERE id = ?",
                         (past, pending["id"]))
        res = self.engine._process_pending_entry(
            self.db.get_pending_entries()[0], available_usdt=10_000.0, open_count=0
        )
        self.assertIsNone(res)
        self.assertEqual(len(self.db.get_pending_entries(status="EXPIRED")), 1)


if __name__ == "__main__":
    unittest.main()

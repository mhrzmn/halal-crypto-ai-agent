"""
Live-fire OCO verification on Binance Spot TESTNET (fake funds).

Scenario A: engine live-buy -> OCO attached on exchange, orderListId in DB,
            open order list visible via API.
Scenario B: engine sell -> OCO cancelled first, position closed, no leftover
            open order lists.
Scenario C: fresh buy -> simulate out-of-band OCO fill (manual market sell of
            the base asset, as the exchange would after an OCO trigger) ->
            scan reconciles via EXCHANGE_RECONCILE, no double-sell.

Uses a throwaway DB so the real paper/live databases are untouched.
PAPER_TRADING and PROTECT_WITH_EXCHANGE_OCO are patched in-process only.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings

settings.PAPER_TRADING = False
settings.PROTECT_WITH_EXCHANGE_OCO = True
settings.BINANCE_USE_TESTNET = True

from core.binance_client import BinanceSpotClient
from execution.bot_engine import BotEngine
from storage.database import Database

SYMBOL = "BTCUSDT"
BASE = "BTC"


def main():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    client = BinanceSpotClient(use_testnet=True)
    db = Database(db_path=tmp.name)
    engine = BotEngine(binance_client=client, database=db)

    price = client.get_ticker_price(SYMBOL)
    qty = round(25.0 / price, 6)  # ~$25 testnet notional
    tp = round(price * 1.05, 2)
    sl = round(price * 0.97, 2)
    print(f"[*] Testnet price: ${price:,.2f} | qty {qty} | TP {tp} | SL {sl}")

    # --- Scenario A: buy attaches OCO -------------------------------------
    res = engine._execute_buy(SYMBOL, qty, price, sl, tp, "testnet verify A")
    pid = res.get("protection_order_id")
    print(f"[A] buy type={res['type']} fill={res['price']} protection_id={pid}")
    assert res["type"] == "LIVE_SPOT_BUY", res
    assert pid is not None, "OCO was not attached"
    open_lists = client.get_open_order_lists()
    print(f"[A] open order lists on exchange: {len(open_lists)}")
    assert any(str(ol.get("orderListId")) == str(pid) for ol in open_lists), \
        "OCO not visible on exchange"
    pos = db.get_active_position(SYMBOL)
    assert str(pos["protection_order_id"]) == str(pid)
    print("[A] PASS: OCO placed on exchange and persisted in DB")

    # --- Scenario B: sell cancels OCO first --------------------------------
    sell = engine._execute_sell(SYMBOL, qty, price, "TESTNET_VERIFY_SELL")
    print(f"[B] sell type={sell['type']} exit={sell.get('exit_price')}")
    remaining = client.get_open_order_lists()
    print(f"[B] open order lists after sell: {len(remaining)}")
    assert not any(str(ol.get("orderListId")) == str(pid) for ol in remaining), \
        "OCO was not cancelled"
    assert db.get_active_position(SYMBOL) is None
    print("[B] PASS: OCO cancelled, position closed, no leftover order lists")

    # --- Scenario C: offline OCO fill reconciles ---------------------------
    price2 = client.get_ticker_price(SYMBOL)
    qty2 = round(25.0 / price2, 6)
    res2 = engine._execute_buy(SYMBOL, qty2, price2,
                               round(price2 * 0.97, 2), round(price2 * 1.05, 2),
                               "testnet verify C")
    pid2 = res2["protection_order_id"]
    filled_qty = float(res2["quantity"])
    print(f"[C] second buy done, protection_id={pid2}, qty={filled_qty}")

    # Simulate the exchange filling the OCO while the bot is "offline":
    # base asset leaves the wallet. Cancel the OCO first so the sell is
    # possible, mirroring what the exchange does when one leg fills.
    client.cancel_order_list(SYMBOL, pid2)
    filters = client.get_exchange_filters(SYMBOL)
    # Testnet wallets start with ~1 BTC; an OCO fill would empty the position,
    # so sell the ENTIRE BTC balance to simulate the post-fill wallet state.
    total_btc = client.get_spot_account_balance(BASE)
    sell_qty = client.round_to_step(total_btc, filters["step_size"])
    client.place_spot_order(SYMBOL, "SELL", sell_qty, order_type="MARKET")
    owned = client.get_spot_account_balance(BASE)
    print(f"[C] simulated off-process fill, wallet {BASE} now: {owned}")
    assert owned < filled_qty * 0.999

    settings.TRADING_PAIRS = []  # reconciliation scan only, no new entries
    results = engine.scan_and_execute_cycle()
    recon = [a for a in results["actions_taken"] if a["type"] == "EXCHANGE_RECONCILE"]
    print(f"[C] reconcile actions: {recon}")
    assert len(recon) == 1, "expected exactly one EXCHANGE_RECONCILE"
    assert db.get_active_position(SYMBOL) is None
    print("[C] PASS: offline fill reconciled, no double-sell")

    print("\nALL TESTNET OCO SCENARIOS PASSED")


if __name__ == "__main__":
    main()

"""
AI Commander Interface.
Enables Antigravity (the AI agent) to directly fetch market state,
perform reasoning, and execute trades autonomously without human intervention.
"""

from typing import Dict, Any, List, Optional
import json
import pandas as pd

from config.settings import settings
from config.halal_whitelist import is_pair_halal
from core.shariah_guard import ShariahComplianceGuard
from core.binance_client import BinanceSpotClient
from strategy.indicators import IndicatorEngine
from risk.risk_manager import RiskManager
from storage.database import Database

class AICommander:
    def __init__(self):
        self.client = BinanceSpotClient()
        self.db = Database()
        self.is_paper = settings.PAPER_TRADING

    def get_market_overview(self) -> Dict[str, Any]:
        """Fetch market data and indicators for all whitelisted pairs for AI analysis."""
        overview = {
            "is_paper": self.is_paper,
            "cash_balance_usdt": self.db.get_paper_balance() if self.is_paper else self.client.get_spot_account_balance("USDT"),
            "open_positions": self.db.get_all_active_positions(),
            "pairs": {}
        }

        for symbol in settings.TRADING_PAIRS:
            try:
                ShariahComplianceGuard.audit_symbol(symbol)
                df = self.client.get_klines(symbol, interval=settings.CANDLE_TIMEFRAME, limit=60)
                df_calc = IndicatorEngine.calculate_all(df)
                snapshot = IndicatorEngine.get_latest_snapshot(df_calc)

                # Recent 5 candle closes and volumes
                recent_candles = []
                for _, row in df_calc.tail(5).iterrows():
                    recent_candles.append({
                        "close": float(row["close"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "volume": float(row["volume"])
                    })

                overview["pairs"][symbol] = {
                    "snapshot": snapshot,
                    "recent_candles": recent_candles
                }
            except Exception as e:
                overview["pairs"][symbol] = {"error": str(e)}

        return overview

    def execute_ai_order(
        self,
        symbol: str,
        action: str,  # 'BUY' or 'SELL'
        rationale: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> Dict[str, Any]:
        """Directly place an order based on AI decision."""
        sym = symbol.upper().strip()
        ShariahComplianceGuard.audit_symbol(sym)
        curr_price = self.client.get_ticker_price(sym)

        if action.upper() == "BUY":
            available_usdt = self.db.get_paper_balance() if self.is_paper else self.client.get_spot_account_balance("USDT")
            sl = stop_loss if stop_loss else round(curr_price * 0.97, 4)
            tp = take_profit if take_profit else round(curr_price * 1.05, 4)

            # Check position sizing
            size_res = RiskManager.calculate_spot_position_size(
                available_usdt=available_usdt,
                current_price=curr_price,
                stop_loss_price=sl,
                symbol=sym
            )

            if not size_res.is_valid:
                return {
                    "success": False,
                    "symbol": sym,
                    "action": "BUY_REJECTED",
                    "reason": size_res.reason
                }

            cost = round(size_res.quantity * curr_price, 2)
            if self.is_paper:
                self.db.update_paper_balance(round(available_usdt - cost, 2))
                self.db.save_active_position(
                    symbol=sym,
                    quantity=size_res.quantity,
                    entry_price=curr_price,
                    stop_loss=sl,
                    take_profit=tp,
                    is_paper=True
                )
                self.db.log_ai_decision(
                    symbol=sym,
                    action="BUY",
                    confidence=0.90,
                    current_price=curr_price,
                    rationale=rationale,
                    provider="Antigravity AI (Direct)"
                )
                return {
                    "success": True,
                    "type": "PAPER_BUY",
                    "symbol": sym,
                    "quantity": size_res.quantity,
                    "price": curr_price,
                    "cost_usdt": cost,
                    "stop_loss": sl,
                    "take_profit": tp,
                    "rationale": rationale
                }
            else:
                # Live Binance Spot Execution
                order = self.client.place_spot_order(
                    symbol=sym,
                    side="BUY",
                    quantity=size_res.quantity,
                    order_type="MARKET"
                )
                self.db.save_active_position(
                    symbol=sym,
                    quantity=size_res.quantity,
                    entry_price=curr_price,
                    stop_loss=sl,
                    take_profit=tp,
                    is_paper=False
                )
                self.db.log_ai_decision(
                    symbol=sym,
                    action="BUY",
                    confidence=0.90,
                    current_price=curr_price,
                    rationale=rationale,
                    provider="Antigravity AI (Direct Live)"
                )
                return {
                    "success": True,
                    "type": "LIVE_SPOT_BUY",
                    "symbol": sym,
                    "quantity": size_res.quantity,
                    "price": curr_price,
                    "order_id": order.get("orderId"),
                    "stop_loss": sl,
                    "take_profit": tp,
                    "rationale": rationale
                }

        elif action.upper() == "SELL":
            pos = self.db.get_active_position(sym)
            if not pos:
                return {
                    "success": False,
                    "symbol": sym,
                    "action": "SELL_REJECTED",
                    "reason": f"No active open position found for {sym} to sell."
                }

            qty = pos["quantity"]
            proceeds = round(qty * curr_price, 2)

            if self.is_paper:
                closed = self.db.close_active_position(sym, curr_price, rationale)
                bal = self.db.get_paper_balance()
                self.db.update_paper_balance(round(bal + proceeds, 2))
                self.db.log_ai_decision(
                    symbol=sym,
                    action="SELL",
                    confidence=0.90,
                    current_price=curr_price,
                    rationale=rationale,
                    provider="Antigravity AI (Direct)"
                )
                return {
                    "success": True,
                    "type": "PAPER_SELL",
                    "symbol": sym,
                    "quantity": qty,
                    "exit_price": curr_price,
                    "pnl_usdt": closed["pnl_usdt"] if closed else 0.0,
                    "pnl_pct": closed["pnl_pct"] if closed else 0.0,
                    "rationale": rationale
                }
            else:
                order = self.client.place_spot_order(
                    symbol=sym,
                    side="SELL",
                    quantity=qty,
                    order_type="MARKET"
                )
                closed = self.db.close_active_position(sym, curr_price, rationale)
                self.db.log_ai_decision(
                    symbol=sym,
                    action="SELL",
                    confidence=0.90,
                    current_price=curr_price,
                    rationale=rationale,
                    provider="Antigravity AI (Direct Live)"
                )
                return {
                    "success": True,
                    "type": "LIVE_SPOT_SELL",
                    "symbol": sym,
                    "quantity": qty,
                    "exit_price": curr_price,
                    "order_id": order.get("orderId"),
                    "pnl_usdt": closed["pnl_usdt"] if closed else 0.0,
                    "pnl_pct": closed["pnl_pct"] if closed else 0.0,
                    "rationale": rationale
                }

        return {"success": False, "reason": f"Unsupported action {action}"}

if __name__ == "__main__":
    commander = AICommander()
    data = commander.get_market_overview()
    print(json.dumps(data, indent=2))

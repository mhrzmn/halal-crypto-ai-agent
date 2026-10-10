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
from execution.bot_engine import BotEngine

class AICommander:
    def __init__(self):
        self.client = BinanceSpotClient()
        self.db = Database()
        self.engine = BotEngine(binance_client=self.client, database=self.db)
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

                # Recent 5 candles with full OHLCV
                recent_candles = []
                for _, row in df_calc.tail(5).iterrows():
                    recent_candles.append({
                        "open": float(row["open"]),
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

            provider = "Antigravity AI (Direct)" if self.is_paper else "Antigravity AI (Direct Live)"
            try:
                # Route through the shared engine: atomic paper buy (incl. fees)
                # or live buy using the real Binance fill price.
                result = self.engine._execute_buy(
                    symbol=sym,
                    quantity=size_res.quantity,
                    price=curr_price,
                    stop_loss=sl,
                    take_profit=tp,
                    rationale=rationale
                )
            except Exception as e:
                return {"success": False, "symbol": sym, "action": "BUY_REJECTED", "reason": str(e)}

            self.db.log_ai_decision(
                symbol=sym,
                action="BUY",
                confidence=0.90,
                current_price=result["price"],
                rationale=rationale,
                provider=provider
            )
            return {
                "success": True,
                "type": result["type"],
                "symbol": sym,
                "quantity": result["quantity"],
                "price": result["price"],
                "cost_usdt": result.get("cost_usdt"),
                "order_id": result.get("binance_order_id"),
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
            provider = "Antigravity AI (Direct)" if self.is_paper else "Antigravity AI (Direct Live)"
            try:
                # Route through the shared engine: atomic paper close (net of fees)
                # or live sell with ownership audit and real fill price.
                result = self.engine._execute_sell(
                    symbol=sym,
                    quantity=qty,
                    exit_price=curr_price,
                    exit_reason=rationale
                )
            except Exception as e:
                return {"success": False, "symbol": sym, "action": "SELL_REJECTED", "reason": str(e)}

            self.db.log_ai_decision(
                symbol=sym,
                action="SELL",
                confidence=0.90,
                current_price=result["exit_price"],
                rationale=rationale,
                provider=provider
            )
            return {
                "success": True,
                "type": result["type"],
                "symbol": sym,
                "quantity": result["quantity"],
                "exit_price": result["exit_price"],
                "order_id": result.get("binance_order_id"),
                "pnl_usdt": result.get("pnl_usdt", 0.0),
                "pnl_net_usdt": result.get("pnl_net_usdt", 0.0),
                "pnl_pct": result.get("pnl_pct", 0.0),
                "rationale": rationale
            }

        return {"success": False, "reason": f"Unsupported action {action}"}

if __name__ == "__main__":
    commander = AICommander()
    data = commander.get_market_overview()
    print(json.dumps(data, indent=2))

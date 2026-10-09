"""
Autonomous Trading Engine.
Coordinates data ingestion, indicator calculations, AI decision making,
Shariah compliance verification, risk management, and order execution.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

from config.settings import settings
from config.halal_whitelist import is_pair_halal
from core.shariah_guard import ShariahComplianceGuard, ShariahViolationError
from core.binance_client import BinanceSpotClient
from strategy.indicators import IndicatorEngine
from strategy.ai_agent import AIAgent, AIAssessment
from risk.risk_manager import RiskManager
from storage.database import Database

logger = logging.getLogger("HalalBotEngine")

class BotEngine:
    def __init__(
        self,
        binance_client: Optional[BinanceSpotClient] = None,
        database: Optional[Database] = None,
        ai_agent: Optional[AIAgent] = None
    ):
        self.client = binance_client or BinanceSpotClient()
        self.db = database or Database()
        self.ai = ai_agent or AIAgent()
        self.is_paper = settings.PAPER_TRADING

    def get_current_usdt_balance(self) -> float:
        """Fetch current available USDT balance (Simulated paper balance or live Binance Spot)."""
        if self.is_paper:
            return self.db.get_paper_balance()
        else:
            try:
                return self.client.get_spot_account_balance("USDT")
            except Exception as e:
                logger.error(f"Failed to fetch live Binance balance: {e}")
                return 0.0

    def scan_and_execute_cycle(self) -> Dict[str, Any]:
        """
        Execute one full cycle of market scanning, position management, and trade execution.
        """
        cycle_start = datetime.utcnow()
        results: Dict[str, Any] = {
            "timestamp": cycle_start.isoformat(),
            "is_paper": self.is_paper,
            "starting_balance_usdt": self.get_current_usdt_balance(),
            "positions_reviewed": [],
            "pairs_scanned": [],
            "actions_taken": [],
            "errors": []
        }

        # -------------------------------------------------------------
        # STEP 1: Manage Open Positions (Exits, Stop-Loss, Take-Profit)
        # -------------------------------------------------------------
        active_positions = self.db.get_all_active_positions()
        for pos in active_positions:
            symbol = pos["symbol"]
            qty = pos["quantity"]
            entry_price = pos["entry_price"]
            sl = pos["stop_loss"]
            tp = pos["take_profit"]
            highest_price = pos["highest_price"]

            try:
                curr_price = self.client.get_ticker_price(symbol)
                
                # Update high watermark if price increased
                if curr_price > highest_price:
                    self.db.update_position_highest_price(symbol, curr_price)
                    highest_price = curr_price

                # Check technical exit conditions via RiskManager
                should_exit, exit_reason = RiskManager.evaluate_position_exit(
                    entry_price=entry_price,
                    current_price=curr_price,
                    stop_loss=sl,
                    take_profit=tp,
                    highest_price_seen=highest_price
                )

                # If no technical exit hit, check if market regime collapsed via AI
                if not should_exit:
                    df = self.client.get_klines(symbol, interval=settings.CANDLE_TIMEFRAME, limit=60)
                    df_calc = IndicatorEngine.calculate_all(df)
                    snapshot = IndicatorEngine.get_latest_snapshot(df_calc)
                    ai_review = self.ai.analyze(
                        symbol=symbol,
                        snapshot=snapshot,
                        has_open_position=True,
                        entry_price=entry_price
                    )
                    if ai_review.action == "SELL" and ai_review.confidence >= 0.75:
                        should_exit = True
                        exit_reason = f"AI_REGIME_EXIT: {ai_review.rationale}"

                # Execute Exit if triggered
                if should_exit:
                    action_summary = self._execute_sell(
                        symbol=symbol,
                        quantity=qty,
                        exit_price=curr_price,
                        exit_reason=exit_reason
                    )
                    results["actions_taken"].append(action_summary)

                results["positions_reviewed"].append({
                    "symbol": symbol,
                    "entry_price": entry_price,
                    "current_price": curr_price,
                    "highest_price": highest_price,
                    "unrealized_pnl_pct": round(((curr_price - entry_price) / entry_price) * 100, 2),
                    "status": "CLOSED" if should_exit else "HOLDING",
                    "reason": exit_reason if should_exit else "Normal"
                })

            except Exception as e:
                err_msg = f"Error managing position for {symbol}: {str(e)}"
                logger.error(err_msg)
                results["errors"].append(err_msg)

        # -------------------------------------------------------------
        # STEP 2: Scan Whitelisted Pairs for High-Conviction Entries
        # -------------------------------------------------------------
        # Refresh balance after potential sells
        available_usdt = self.get_current_usdt_balance()

        for symbol in settings.TRADING_PAIRS:
            # Audit Shariah compliance
            try:
                ShariahComplianceGuard.audit_symbol(symbol)
            except ShariahViolationError as sve:
                results["errors"].append(str(sve))
                continue

            # Skip if we already hold an open position in this asset
            if self.db.get_active_position(symbol):
                continue

            try:
                # 1. Fetch live market candles
                df = self.client.get_klines(
                    symbol=symbol,
                    interval=settings.CANDLE_TIMEFRAME,
                    limit=settings.CANDLE_LIMIT
                )
                df_calc = IndicatorEngine.calculate_all(df)
                snapshot = IndicatorEngine.get_latest_snapshot(df_calc)

                # 2. Run AI Assessment
                assessment = self.ai.analyze(
                    symbol=symbol,
                    snapshot=snapshot,
                    has_open_position=False
                )

                # Log AI decision
                self.db.log_ai_decision(
                    symbol=symbol,
                    action=assessment.action,
                    confidence=assessment.confidence,
                    current_price=snapshot["close"],
                    rationale=assessment.rationale,
                    provider=assessment.provider
                )

                results["pairs_scanned"].append({
                    "symbol": symbol,
                    "price": snapshot["close"],
                    "regime": snapshot["regime"],
                    "rsi": round(snapshot["rsi_14"], 1),
                    "action": assessment.action,
                    "confidence": assessment.confidence,
                    "rationale": assessment.rationale
                })

                # 3. Entry Evaluation
                if assessment.action == "BUY" and assessment.confidence >= settings.AI_CONFIDENCE_THRESHOLD:
                    size_res = RiskManager.calculate_spot_position_size(
                        available_usdt=available_usdt,
                        current_price=snapshot["close"],
                        stop_loss_price=assessment.recommended_stop_loss,
                        symbol=symbol
                    )

                    if size_res.is_valid:
                        action_summary = self._execute_buy(
                            symbol=symbol,
                            quantity=size_res.quantity,
                            price=snapshot["close"],
                            stop_loss=assessment.recommended_stop_loss,
                            take_profit=assessment.recommended_take_profit,
                            rationale=assessment.rationale
                        )
                        results["actions_taken"].append(action_summary)
                        # Update local available balance for next pair
                        available_usdt -= size_res.notional_value_usdt
                    else:
                        logger.info(f"Entry signal for {symbol} skipped by risk manager: {size_res.reason}")

            except Exception as e:
                err_msg = f"Error scanning pair {symbol}: {str(e)}"
                logger.error(err_msg)
                results["errors"].append(err_msg)

        results["ending_balance_usdt"] = self.get_current_usdt_balance()
        return results

    def _execute_buy(
        self,
        symbol: str,
        quantity: float,
        price: float,
        stop_loss: float,
        take_profit: float,
        rationale: str
    ) -> Dict[str, Any]:
        """Execute Long Spot Buy order with full Halal verification."""
        cost_usdt = round(quantity * price, 2)

        if self.is_paper:
            curr_balance = self.db.get_paper_balance()
            new_balance = round(curr_balance - cost_usdt, 2)
            self.db.update_paper_balance(new_balance)
            self.db.save_active_position(
                symbol=symbol,
                quantity=quantity,
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                is_paper=True
            )
            return {
                "type": "PAPER_BUY",
                "symbol": symbol,
                "quantity": quantity,
                "price": price,
                "cost_usdt": cost_usdt,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "rationale": rationale
            }
        else:
            # Live Binance Spot Execution
            order = self.client.place_spot_order(
                symbol=symbol,
                side="BUY",
                quantity=quantity,
                order_type="MARKET"
            )
            self.db.save_active_position(
                symbol=symbol,
                quantity=quantity,
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                is_paper=False
            )
            return {
                "type": "LIVE_SPOT_BUY",
                "symbol": symbol,
                "quantity": quantity,
                "price": price,
                "cost_usdt": cost_usdt,
                "binance_order_id": order.get("orderId"),
                "stop_loss": stop_loss,
                "take_profit": take_profit
            }

    def _execute_sell(
        self,
        symbol: str,
        quantity: float,
        exit_price: float,
        exit_reason: str
    ) -> Dict[str, Any]:
        """Execute Spot Sell order (Closing position and realizing profit/loss)."""
        proceeds_usdt = round(quantity * exit_price, 2)

        if self.is_paper:
            closed_info = self.db.close_active_position(
                symbol=symbol,
                sell_price=exit_price,
                exit_reason=exit_reason
            )
            curr_balance = self.db.get_paper_balance()
            new_balance = round(curr_balance + proceeds_usdt, 2)
            self.db.update_paper_balance(new_balance)
            return {
                "type": "PAPER_SELL",
                "symbol": symbol,
                "quantity": quantity,
                "exit_price": exit_price,
                "proceeds_usdt": proceeds_usdt,
                "pnl_usdt": closed_info["pnl_usdt"] if closed_info else 0.0,
                "pnl_pct": closed_info["pnl_pct"] if closed_info else 0.0,
                "reason": exit_reason
            }
        else:
            # Live Binance Spot Execution
            order = self.client.place_spot_order(
                symbol=symbol,
                side="SELL",
                quantity=quantity,
                order_type="MARKET"
            )
            closed_info = self.db.close_active_position(
                symbol=symbol,
                sell_price=exit_price,
                exit_reason=exit_reason
            )
            return {
                "type": "LIVE_SPOT_SELL",
                "symbol": symbol,
                "quantity": quantity,
                "exit_price": exit_price,
                "proceeds_usdt": proceeds_usdt,
                "binance_order_id": order.get("orderId"),
                "pnl_usdt": closed_info["pnl_usdt"] if closed_info else 0.0,
                "pnl_pct": closed_info["pnl_pct"] if closed_info else 0.0,
                "reason": exit_reason
            }

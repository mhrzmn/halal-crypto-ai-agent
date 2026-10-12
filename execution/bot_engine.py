"""
Autonomous Trading Engine.
Coordinates data ingestion, indicator calculations, AI decision making,
Shariah compliance verification, risk management, and order execution.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
import logging

from config.settings import settings
from config.halal_whitelist import is_pair_halal, get_base_and_quote
from core.shariah_guard import ShariahComplianceGuard, ShariahViolationError
from core.binance_client import BinanceSpotClient
from strategy.indicators import IndicatorEngine
from strategy.ai_agent import AIAgent, AIAssessment
from risk.risk_manager import RiskManager
from storage.database import Database, minutes_since as db_minutes_since

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
        cycle_start = datetime.now(timezone.utc)
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
                # Reconcile exchange-side protection: if an OCO protected this position
                # and the base asset is gone from the wallet, the exchange already closed
                # the trade while we were offline — sync the DB instead of double-selling.
                if not self.is_paper and pos.get("protection_order_id"):
                    base_quote = get_base_and_quote(symbol)
                    if base_quote:
                        base_asset, _ = base_quote
                        owned = self.client.get_spot_account_balance(base_asset)
                        if owned < qty * 0.999:
                            closed = self.db.close_active_position(
                                symbol=symbol,
                                sell_price=pos["take_profit"],  # approx; true fill unknown here
                                exit_reason="EXCHANGE_PROTECTION_FILLED: OCO closed position off-process"
                            )
                            results["actions_taken"].append({
                                "type": "EXCHANGE_RECONCILE",
                                "symbol": symbol,
                                "pnl_net_usdt": closed["pnl_net_usdt"] if closed else 0.0,
                                "reason": "Exchange-side OCO filled; DB synchronized"
                            })
                            results["positions_reviewed"].append({
                                "symbol": symbol,
                                "entry_price": entry_price,
                                "status": "CLOSED_BY_EXCHANGE"
                            })
                            continue

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

                # If no technical exit hit, check if market regime collapsed via AI.
                # STRICT_SL_TP_EXIT_ONLY: AI can never trigger a sale — the pre-committed
                # SL/TP above are the only routine exit triggers. Skip the review entirely.
                if not should_exit and not settings.STRICT_SL_TP_EXIT_ONLY:
                    df = self.client.get_klines(symbol, interval=settings.CANDLE_TIMEFRAME, limit=settings.CANDLE_LIMIT)
                    df = self._signal_frame(df)
                    df_calc = IndicatorEngine.calculate_all(df)
                    snapshot = IndicatorEngine.get_latest_snapshot(df_calc)
                    ai_review = self.ai.analyze(
                        symbol=symbol,
                        snapshot=snapshot,
                        has_open_position=True,
                        entry_price=entry_price
                    )
                    if ai_review.action == "SELL" and ai_review.confidence >= 0.75:
                        allowed, block_reason = self._ai_exit_allowed(
                            entry_price, curr_price, pos.get("entry_time")
                        )
                        if allowed:
                            should_exit = True
                            exit_reason = f"AI_REGIME_EXIT: {ai_review.rationale}"
                        else:
                            logger.info(f"AI exit on {symbol} blocked by anti-churn guard: {block_reason}")

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
        # STEP 1.5: Fill/cancel pending (limit-zone) entries
        # -------------------------------------------------------------
        available_usdt = self.get_current_usdt_balance()
        open_count = len(self.db.get_all_active_positions())
        for pending in self.db.get_pending_entries():
            fill = self._process_pending_entry(pending, available_usdt, open_count)
            if fill:
                results["actions_taken"].append(fill)
                available_usdt -= fill.get("notional_usdt", 0)
                open_count += 1

        # -------------------------------------------------------------
        # STEP 2: Scan Whitelisted Pairs for High-Conviction Entries
        # -------------------------------------------------------------
        # Refresh balance after potential sells
        available_usdt = self.get_current_usdt_balance()

        # Cap total exposure: no new entries once MAX_OPEN_POSITIONS is reached
        open_count = len(self.db.get_all_active_positions())
        max_new = max(0, settings.MAX_OPEN_POSITIONS - open_count)
        if max_new == 0:
            logger.info(
                f"Max open positions ({settings.MAX_OPEN_POSITIONS}) reached; skipping entry scan"
            )

        for symbol in settings.TRADING_PAIRS:
            if max_new <= 0:
                break
            # Audit Shariah compliance
            try:
                ShariahComplianceGuard.audit_symbol(symbol)
            except ShariahViolationError as sve:
                results["errors"].append(str(sve))
                continue

            # Skip if we already hold an open position in this asset
            if self.db.get_active_position(symbol):
                continue

            # Anti-churn: skip symbols closed within the re-entry cooldown window
            if self.reentry_blocked(symbol):
                logger.info(f"Re-entry on {symbol} blocked by cooldown")
                continue

            try:
                # 1. Fetch live market candles (signals only on confirmed/closed candles)
                df = self.client.get_klines(
                    symbol=symbol,
                    interval=settings.CANDLE_TIMEFRAME,
                    limit=settings.CANDLE_LIMIT
                )
                df = self._signal_frame(df)
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
                    # Sanity-check AI-provided stops: invalid/zero/misplaced SL/TP would
                    # create an unprotected or instantly-triggered position.
                    valid_stops, stop_reason = self._validate_stops(
                        snapshot["close"],
                        assessment.recommended_stop_loss,
                        assessment.recommended_take_profit
                    )
                    if not valid_stops:
                        logger.info(f"Entry for {symbol} rejected: {stop_reason}")
                        results["errors"].append(f"{symbol}: rejected entry — {stop_reason}")
                        continue

                    # Pending-entry mode: compute a target entry zone below market and
                    # queue the trade instead of chasing the current price.
                    if settings.PENDING_ENTRY_ENABLED:
                        if self.db.get_pending_entry_for_symbol(symbol):
                            continue  # one pending order per symbol
                        queued = self._queue_pending_entry(
                            symbol=symbol,
                            snapshot=snapshot,
                            assessment=assessment
                        )
                        if queued:
                            results["actions_taken"].append(queued)
                            continue
                        # Fall through to immediate buy if zone already reached

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
                        # Update local available balance and slots for next pair
                        available_usdt -= size_res.notional_value_usdt
                        max_new -= 1
                    else:
                        logger.info(f"Entry signal for {symbol} skipped by risk manager: {size_res.reason}")

            except Exception as e:
                err_msg = f"Error scanning pair {symbol}: {str(e)}"
                logger.error(err_msg)
                results["errors"].append(err_msg)

        results["ending_balance_usdt"] = self.get_current_usdt_balance()
        return results

    @staticmethod
    def _signal_frame(df):
        """Apply the confirmed-candle policy before indicators are computed."""
        if settings.REQUIRE_CLOSED_CANDLE:
            return IndicatorEngine.confirmed_candles(df)
        return df

    def _queue_pending_entry(self, symbol: str, snapshot: dict, assessment) -> Optional[Dict[str, Any]]:
        """
        Compute the AI's target entry zone and queue a pending order.
        Zone = min(EMA20, close - PULLBACK_ATR * ATR), i.e. buy the pullback
        toward dynamic support instead of chasing the current close.
        Returns the queued action summary, or None if price is already inside
        the zone (caller should then buy immediately at market).
        """
        close = snapshot["close"]
        atr = snapshot.get("atr_14") or close * 0.01
        ema20 = snapshot.get("ema_20") or close

        zone = min(ema20, close - settings.PENDING_ENTRY_PULLBACK_ATR * atr)
        # If the zone is at/above market, price is already there — buy now.
        if zone >= close * 0.999:
            return None

        # Shift the AI's SL/TP down by the same delta so the R:R structure is
        # preserved relative to the limit entry, not the chase price.
        delta = close - zone
        sl = assessment.recommended_stop_loss - delta
        tp = assessment.recommended_take_profit - delta

        valid, reason = self._validate_stops(zone, sl, tp)
        if not valid:
            logger.info(f"Pending entry for {symbol} rejected at zone {zone:.4f}: {reason}")
            return None

        expires = datetime.now(timezone.utc) + timedelta(hours=settings.PENDING_ENTRY_EXPIRY_HOURS)
        self.db.save_pending_entry(
            symbol=symbol,
            target_entry=zone,
            stop_loss=sl,
            take_profit=tp,
            confidence=assessment.confidence,
            rationale=assessment.rationale,
            expires_at=expires.isoformat()
        )
        logger.info(
            f"Queued pending entry {symbol}: zone {zone:.4f} (mkt {close:.4f}), "
            f"SL {sl:.4f}, TP {tp:.4f}, expires {settings.PENDING_ENTRY_EXPIRY_HOURS}h"
        )
        return {
            "type": "PENDING_ENTRY_QUEUED",
            "symbol": symbol,
            "target_entry": zone,
            "market_price": close,
            "stop_loss": sl,
            "take_profit": tp,
            "confidence": assessment.confidence
        }

    def _process_pending_entry(
        self, pending: dict, available_usdt: float, open_count: int
    ) -> Optional[Dict[str, Any]]:
        """
        Check one pending order against the live price:
          - price <= target zone  -> validate stops vs fill, size, buy, mark FILLED
          - price < stop_loss     -> thesis invalidated, CANCELLED
          - past expires_at       -> EXPIRED
        Returns the buy action summary when filled, else None.
        """
        symbol = pending["symbol"]

        # Expiry check first — stale analyses must not fill later
        try:
            expires = datetime.fromisoformat(pending["expires_at"])
        except (TypeError, ValueError):
            self.db.update_pending_entry_status(pending["id"], "CANCELLED")
            return None
        if datetime.now(timezone.utc) > expires:
            self.db.update_pending_entry_status(pending["id"], "EXPIRED")
            logger.info(f"Pending entry {symbol} #{pending['id']} expired unfilled")
            return None

        if self.db.get_active_position(symbol):
            self.db.update_pending_entry_status(pending["id"], "CANCELLED")
            return None
        if open_count >= settings.MAX_OPEN_POSITIONS:
            return None  # keep waiting; a slot may free up before expiry

        price = self.client.get_ticker_price(symbol)

        # Price fell through the stop before ever reaching the zone — setup is dead
        if price < pending["stop_loss"]:
            self.db.update_pending_entry_status(pending["id"], "CANCELLED")
            logger.info(
                f"Pending entry {symbol} cancelled: price {price:.4f} broke SL "
                f"{pending['stop_loss']:.4f} before fill"
            )
            return None

        if price > pending["target_entry"]:
            return None  # zone not touched yet — keep waiting

        # Zone reached: re-validate levels against the actual fill price
        valid, reason = self._validate_stops(price, pending["stop_loss"], pending["take_profit"])
        if not valid:
            self.db.update_pending_entry_status(pending["id"], "CANCELLED")
            logger.info(f"Pending entry {symbol} cancelled at fill: {reason}")
            return None

        size_res = RiskManager.calculate_spot_position_size(
            available_usdt=available_usdt,
            current_price=price,
            stop_loss_price=pending["stop_loss"],
            symbol=symbol
        )
        if not size_res.is_valid:
            self.db.update_pending_entry_status(pending["id"], "CANCELLED")
            logger.info(f"Pending entry {symbol} cancelled at fill: {size_res.reason}")
            return None

        action = self._execute_buy(
            symbol=symbol,
            quantity=size_res.quantity,
            price=price,
            stop_loss=pending["stop_loss"],
            take_profit=pending["take_profit"],
            rationale=f"LIMIT-ZONE FILL @ {price:.4f} (target {pending['target_entry']:.4f}) — {pending['rationale']}"
        )
        self.db.update_pending_entry_status(pending["id"], "FILLED")
        action["notional_usdt"] = size_res.notional_value_usdt
        action["type"] = f"PENDING_{action.get('type', 'BUY')}"
        return action

    @staticmethod
    def _validate_stops(price: float, stop_loss, take_profit) -> tuple:
        """
        Validate AI-provided SL/TP before entering. For a long spot position:
        SL must be below entry, TP above entry, both positive and within a sane
        distance (0.1%..50%) to avoid broken/unprotected or instantly-triggered trades.
        """
        try:
            sl = float(stop_loss)
            tp = float(take_profit)
        except (TypeError, ValueError):
            return False, "non-numeric SL/TP from AI"

        if price <= 0 or sl <= 0 or tp <= 0:
            return False, f"non-positive price levels (price={price}, sl={sl}, tp={tp})"
        if sl >= price:
            return False, f"stop-loss {sl} not below entry {price}"
        if tp <= price:
            return False, f"take-profit {tp} not above entry {price}"

        sl_dist = (price - sl) / price * 100.0
        tp_dist = (tp - price) / price * 100.0
        if sl_dist < 0.1 or sl_dist > 50.0:
            return False, f"stop-loss distance {sl_dist:.2f}% outside sane range"
        if tp_dist < 0.1 or tp_dist > 50.0:
            return False, f"take-profit distance {tp_dist:.2f}% outside sane range"

        # Reward must justify the risk: reject setups where TP distance is too
        # small relative to SL distance (fees make low-R:R trades net negative).
        rr_ratio = tp_dist / sl_dist
        if rr_ratio < settings.MIN_RISK_REWARD_RATIO:
            return False, (
                f"risk:reward {rr_ratio:.2f} below minimum {settings.MIN_RISK_REWARD_RATIO} "
                f"(SL {sl_dist:.2f}% vs TP {tp_dist:.2f}%)"
            )
        return True, ""

    @staticmethod
    def _ai_exit_allowed(
        entry_price: float,
        current_price: float,
        entry_time: Optional[str]
    ) -> tuple:
        """
        Anti-churn gate for AI/regime exits. Hard stops (SL/TP/trailing/panic) never
        pass through here — they always fire immediately.

        An AI exit is allowed only when BOTH:
          1. The position has been held at least MIN_HOLD_MINUTES, AND
          2. The move is large enough to matter after fees: |pnl_pct| >= AI_EXIT_MIN_EDGE_PERCENT
             (round-trip fees are ~0.2%, so sub-0.2% exits just donate fees to the exchange).
        Fails CLOSED (blocks exit) if entry_time is missing/unparseable — an unknown-age
        position must not be sold on a heuristic.
        """
        if settings.STRICT_SL_TP_EXIT_ONLY:
            return False, "strict SL/TP-only mode: AI exits disabled"

        hold_min = db_minutes_since(entry_time)
        if hold_min is None:
            return False, "entry_time missing/unparseable; blocking AI exit (fail-closed)"
        if hold_min < settings.MIN_HOLD_MINUTES:
            return False, f"held {hold_min:.1f}m < min {settings.MIN_HOLD_MINUTES}m"

        if entry_price > 0:
            pnl_pct = ((current_price - entry_price) / entry_price) * 100.0
            if abs(pnl_pct) < settings.AI_EXIT_MIN_EDGE_PERCENT:
                return False, f"move {pnl_pct:+.2f}% < edge {settings.AI_EXIT_MIN_EDGE_PERCENT}%"

        return True, ""

    def reentry_blocked(self, symbol: str) -> bool:
        """True if the symbol was closed too recently to re-enter (anti-churn cooldown)."""
        last_close = self.db.get_last_close_time(symbol)
        if last_close is None:
            return False
        elapsed = (datetime.now(timezone.utc) - last_close).total_seconds() / 60.0
        return elapsed < settings.SYMBOL_REENTRY_COOLDOWN_MINUTES

    def panic_sell_all(self, reason: str = "EMERGENCY_PANIC_SELL") -> Dict[str, Any]:
        """Emergency flatten: close every open position to USDT through the standard sell path."""
        closed: List[str] = []
        errors: List[str] = []
        for pos in self.db.get_all_active_positions():
            symbol = pos["symbol"]
            try:
                curr_price = self.client.get_ticker_price(symbol)
                self._execute_sell(
                    symbol=symbol,
                    quantity=pos["quantity"],
                    exit_price=curr_price,
                    exit_reason=reason
                )
                closed.append(symbol)
            except Exception as e:
                logger.error(f"Panic sell failed for {symbol}: {e}")
                errors.append(f"{symbol}: {e}")
        return {"closed_positions": closed, "errors": errors}

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
            # Atomic: debit balance (incl. buy-side fee) + save position in one transaction
            opened = self.db.paper_open_position(
                symbol=symbol,
                quantity=quantity,
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit
            )
            return {
                "type": "PAPER_BUY",
                "symbol": symbol,
                "quantity": quantity,
                "price": price,
                "cost_usdt": opened["total_cost_usdt"],
                "buy_fee_usdt": opened["buy_fee_usdt"],
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "rationale": rationale
            }
        else:
            # Live Binance Spot Execution — use the REAL fill price from the exchange
            # Exchange-compliant quantity: un-rounded quantities are rejected (LOT_SIZE).
            try:
                filters = self.client.get_exchange_filters(symbol)
                quantity = self.client.round_to_step(quantity, filters["step_size"])
            except Exception as e:
                logger.warning(f"Could not fetch exchange filters for {symbol}, using raw quantity: {e}")
            order = self.client.place_spot_order(
                symbol=symbol,
                side="BUY",
                quantity=quantity,
                order_type="MARKET"
            )
            fill_price = BinanceSpotClient.extract_fill_price(order, price)
            filled_qty = float(order.get("executedQty") or quantity)
            self.db.save_active_position(
                symbol=symbol,
                quantity=filled_qty,
                entry_price=fill_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                is_paper=False
            )

            # Exchange-side protection: attach an OCO (TP + SL) so the position is
            # protected even if this process stops. Stop-limit is placed slightly
            # below the stop trigger to improve fill odds in fast markets.
            protection_id = None
            if settings.PROTECT_WITH_EXCHANGE_OCO:
                try:
                    filters = self.client.get_exchange_filters(symbol)
                    oco_qty = self.client.round_to_step(filled_qty, filters["step_size"])
                    tick = filters["tick_size"]
                    tp_px = self.client.round_to_tick(take_profit, tick, "nearest")
                    stop_px = self.client.round_to_tick(stop_loss, tick, "nearest")
                    stop_limit = self.client.round_to_tick(stop_loss * 0.995, tick, "down")
                    oco = self.client.place_spot_oco_sell(
                        symbol=symbol,
                        quantity=oco_qty,
                        take_profit_price=tp_px,
                        stop_price=stop_px,
                        stop_limit_price=stop_limit
                    )
                    protection_id = oco.get("orderListId")
                    if protection_id is not None:
                        self.db.set_protection_order_id(symbol, protection_id)
                except Exception as e:
                    logger.error(
                        f"OCO protection placement failed for {symbol}: {e}. "
                        f"Position relies on local sentinel only — investigate before trusting."
                    )
            return {
                "protection_order_id": protection_id,
                "type": "LIVE_SPOT_BUY",
                "symbol": symbol,
                "quantity": filled_qty,
                "price": fill_price,
                "cost_usdt": round(filled_qty * fill_price, 2),
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
        if self.is_paper:
            # Atomic: close position + record history + credit net proceeds in one transaction
            closed_info = self.db.paper_close_position(
                symbol=symbol,
                sell_price=exit_price,
                exit_reason=exit_reason
            )
            return {
                "type": "PAPER_SELL",
                "symbol": symbol,
                "quantity": quantity,
                "exit_price": exit_price,
                "proceeds_usdt": closed_info["proceeds_usdt"] if closed_info else 0.0,
                "fee_usdt": closed_info["fee_usdt"] if closed_info else 0.0,
                "pnl_usdt": closed_info["pnl_usdt"] if closed_info else 0.0,
                "pnl_net_usdt": closed_info["pnl_net_usdt"] if closed_info else 0.0,
                "pnl_pct": closed_info["pnl_pct"] if closed_info else 0.0,
                "reason": exit_reason
            }
        else:
            # Live Binance Spot Execution
            # 0. Release exchange-side protection first — an active OCO locks the
            #    base-asset balance, which would make the manual/panic sell fail.
            pos = self.db.get_active_position(symbol)
            protection_id = pos.get("protection_order_id") if pos else None
            if protection_id:
                try:
                    self.client.cancel_order_list(symbol, protection_id)
                except Exception as e:
                    logger.warning(f"Could not cancel OCO protection {protection_id} for {symbol}: {e}")

            # 1. Verify we actually own the asset before selling (no short-selling)
            base_quote = get_base_and_quote(symbol)
            if base_quote:
                base_asset, _ = base_quote
                owned = self.client.get_spot_account_balance(base_asset)
                ShariahComplianceGuard.audit_spot_balance_before_sale(base_asset, quantity, owned)

            # 2. Place the sell with exchange-compliant quantity
            try:
                filters = self.client.get_exchange_filters(symbol)
                quantity = self.client.round_to_step(quantity, filters["step_size"])
            except Exception as e:
                logger.warning(f"Could not fetch exchange filters for {symbol}, using raw quantity: {e}")

            order = self.client.place_spot_order(
                symbol=symbol,
                side="SELL",
                quantity=quantity,
                order_type="MARKET"
            )
            fill_price = BinanceSpotClient.extract_fill_price(order, exit_price)
            filled_qty = float(order.get("executedQty") or quantity)
            closed_info = self.db.close_active_position(
                symbol=symbol,
                sell_price=fill_price,
                exit_reason=exit_reason
            )
            return {
                "type": "LIVE_SPOT_SELL",
                "symbol": symbol,
                "quantity": filled_qty,
                "exit_price": fill_price,
                "proceeds_usdt": round(filled_qty * fill_price, 2),
                "binance_order_id": order.get("orderId"),
                "pnl_usdt": closed_info["pnl_usdt"] if closed_info else 0.0,
                "pnl_net_usdt": closed_info["pnl_net_usdt"] if closed_info else 0.0,
                "pnl_pct": closed_info["pnl_pct"] if closed_info else 0.0,
                "reason": exit_reason
            }

"""
Antigravity Direct AI Trader.
Runs an autonomous AI analysis cycle and directly places trades with ZERO user intervention.
"""

import sys
import json
from datetime import datetime, timezone

from ai_commander import AICommander
from config.settings import settings
from storage.database import Database

def run_ai_trading_turn():
    commander = AICommander()
    db = Database()
    data = commander.get_market_overview()

    print("=" * 70)
    print("       ANTIGRAVITY AUTONOMOUS AI TRADING CYCLE (DIRECT EXECUTION)")
    print(f"       Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} | Zero Intervention Mode")
    print("=" * 70)

    cash = data["cash_balance_usdt"]
    positions = data["open_positions"]
    pairs = data["pairs"]

    print(f"[*] Available Cash: ${cash:,.2f} USDT | Open Positions: {len(positions)}")

    # 1. Manage any active open positions first (Trailing stops / profit exits)
    for pos in positions:
        sym = pos["symbol"]
        entry = pos["entry_price"]
        sl = pos["stop_loss"]
        tp = pos["take_profit"]
        highest = pos["highest_price"]
        curr_price = commander.client.get_ticker_price(sym)

        # Update high watermark so trailing stop works
        if curr_price > highest:
            commander.db.update_position_highest_price(sym, curr_price)
            highest = curr_price

        # Use the full RiskManager exit evaluation (SL / TP / trailing stop)
        from risk.risk_manager import RiskManager
        should_exit, exit_reason = RiskManager.evaluate_position_exit(
            entry_price=entry,
            current_price=curr_price,
            stop_loss=sl,
            take_profit=tp,
            highest_price_seen=highest
        )

        if should_exit:
            print(f"[!] Exit Triggered for {sym}: {exit_reason}")
            res = commander.execute_ai_order(sym, "SELL", exit_reason)
            print(f"    Executed Exit: {res}")
        else:
            pnl_pct = ((curr_price - entry) / entry) * 100
            print(f"[-] Holding {sym}: Price ${curr_price:,.2f} | Unrealized PnL: {pnl_pct:+.2f}%")

    # 2. Analyze market opportunities for new entries
    candidate_setups = []

    for sym, pdata in pairs.items():
        if "error" in pdata:
            continue
        snap = pdata["snapshot"]
        recent = pdata["recent_candles"]
        price = snap["close"]
        rsi = snap["rsi_14"]
        macd_hist = snap["macd_hist"]
        prev_macd_hist = snap["prev_macd_hist"]
        regime = snap["regime"]
        atr = snap["atr_14"]

        # Check if we already hold an open position in this coin
        if any(p["symbol"] == sym for p in positions):
            continue

        # AI Decision Logic:
        # We look for two distinct Halal Spot setups:
        # A) Trend Continuation (Strong Bullish + RSI healthy + volume)
        # B) Oversold Bounce Reversal (RSI < 25 + Lower shadow hammer + MACD histogram curling up)
        
        last_candle = recent[-1]
        prev_candle = recent[-2] if len(recent) > 1 else last_candle
        # Use the candle's own open (consistent OHLC), not the snapshot's latest open
        candle_open = last_candle.get("open", last_candle["close"])
        lower_shadow = min(last_candle["close"], candle_open) - last_candle["low"]
        body = abs(last_candle["close"] - candle_open)
        is_hammer_wick = lower_shadow > (body * 1.5) if body > 0 else False
        macd_curling_up = macd_hist > prev_macd_hist

        score = 0.0
        reasons = []

        # Scoring mirrors strategy/signals.py exactly so both entry paths apply
        # the same conviction standard and can actually reach the 0.80 threshold.
        # Criterion A: Trend Structure (max 0.55)
        if regime == "STRONG_BULLISH":
            score += 0.55
            reasons.append("Strong bullish structure (above 200 EMA, 20>50 EMA)")
        elif regime == "MODERATE_BULLISH":
            score += 0.35
            reasons.append("Price above 200 EMA (Long-term Bullish structure)")

        # Criterion B: Healthy RSI (max 0.25)
        if 42 <= rsi <= 65:
            score += 0.25
            reasons.append(f"RSI in optimal bullish accumulation zone ({rsi:.1f})")
        elif rsi < 35 and regime in ["STRONG_BULLISH", "MODERATE_BULLISH"]:
            score += 0.20
            reasons.append(f"Oversold pullback in macro uptrend (RSI {rsi:.1f})")
            if is_hammer_wick:
                score += 0.05
                reasons.append("Bullish rejection hammer wick")

        # Criterion C: MACD Momentum Expansion (0.15)
        if macd_hist > 0 and macd_curling_up:
            score += 0.15
            reasons.append("MACD histogram expanding upwards")

        # Criterion D: Volume Confirmation (0.10)
        if snap["vol_ratio"] > 1.1:
            score += 0.10
            reasons.append(f"Volume surge {snap['vol_ratio']:.2f}x average")

        print(f"  > {sym:<8}: ${price:>9,.2f} | RSI {rsi:>4.1f} | AI Conviction: {score:.2f} | Notes: {'; '.join(reasons) if reasons else 'No confluence'}")

        # Shared conviction threshold (same policy as the main engine — no bypasses)
        if score >= settings.AI_CONFIDENCE_THRESHOLD:
            candidate_setups.append({
                "symbol": sym,
                "price": price,
                "score": score,
                "atr": atr,
                "reasons": "; ".join(reasons)
            })

    # 3. Direct Autonomous Order Placement (Zero Human Intervention)
    if candidate_setups and cash >= 20.0:
        # Sort by conviction score
        candidate_setups.sort(key=lambda x: x["score"], reverse=True)
        best = candidate_setups[0]
        sym = best["symbol"]
        price = best["price"]
        atr = best["atr"]

        sl = round(price - (settings.ATR_STOP_LOSS_MULTIPLIER * atr), 4)
        tp = round(price + (settings.ATR_TAKE_PROFIT_MULTIPLIER * atr), 4)
        rationale = f"AI Direct Approval: {best['reasons']} (Conviction {best['score']:.2f})"

        print(f"\n[+] AI DECISION: HIGH-CONVICTION OPPORTUNITY DETECTED ON {sym}!")
        print(f"    Target Entry: ${price:,.2f} | Stop-Loss: ${sl:,.2f} | Take-Profit: ${tp:,.2f}")
        print(f"    Executing order autonomously without human intervention...")

        order_res = commander.execute_ai_order(
            symbol=sym,
            action="BUY",
            rationale=rationale,
            stop_loss=sl,
            take_profit=tp
        )

        if order_res.get("success"):
            print(f"[OK] ORDER PLACED SUCCESSFULLY: {order_res['type']} {sym} - Qty: {order_res['quantity']} @ ${order_res['price']:,.2f}")
        else:
            print(f"[!] Order rejected by risk manager: {order_res.get('reason')}")
    else:
        print(f"\n[-] AI DECISION: HOLD 100% CASH. No setup reached the {settings.AI_CONFIDENCE_THRESHOLD:.2f} conviction threshold.")
        print("    Capital preservation in effect. Waiting for market stabilization.")

    print("=" * 70)

if __name__ == "__main__":
    run_ai_trading_turn()

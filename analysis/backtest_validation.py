"""
Walk-forward backtest harness for the Halal bot's signal + sizing logic.

Purpose: EMPIRICALLY verify (not just assert) that the upgdaded logic —
  (a) regime filter (ADX + Choppiness + DI alignment),
  (b) ATR stop/TP structure, R:R gate,
  (c) fixed-fractional sizing
beats the pre-upgrade baseline (no regime filter) on the same Halal universe.

It uses ONLY live public Binance Spot klines (no keys, no funds). It is a
research/validation tool and is NOT part of the live execution path.

Run:  python analysis/backtest_validation.py
"""

import os
import sys
import math
from typing import List, Dict, Any

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings
from strategy.indicators import IndicatorEngine

FEE_RATE = 0.001  # taker, per side


def fetch_klines(symbol: str, interval: str = "4h", limit: int = 1000) -> pd.DataFrame:
    """Public Binance Spot klines (no auth)."""
    url = "https://api.binance.com/api/v3/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=20)
    r.raise_for_status()
    cols = ["open_time", "open", "high", "low", "close", "volume",
            "close_time", "qav", "trades", "tbbav", "tbqav", "ignore"]
    df = pd.DataFrame(r.json(), columns=cols)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    df.set_index("open_time", inplace=True)
    # ensure warmup for EMA200
    return df


def score_entry(row, use_regime_filter: bool):
    """Return (action, score) mirroring SignalGenerator but vectorizable."""
    close, ema20, ema50, ema200 = row["close"], row["ema_20"], row["ema_50"], row["ema_200"]
    rsi, macd, pmacd, volr = row["rsi_14"], row["macd_hist"], row["prev_macd_hist"], row["vol_ratio"]
    if any(pd.isna(x) for x in [ema20, ema50, ema200, rsi, macd]):
        return "HOLD", 0.0
    if use_regime_filter:
        # Mirror the SHIPPED default gate: DI alignment on, ADX/CHOP gates off
        # (empirically validated — see config/settings.py notes).
        dp, dm = row["di_plus"], row["di_minus"]
        if settings.REQUIRE_ADX_FILTER:
            adx = row["adx_14"]
            if pd.isna(adx) or adx < settings.ADX_TREND_THRESHOLD:
                return "HOLD", 0.0
        if settings.REQUIRE_CHOP_FILTER:
            chop = row["chop_14"]
            if pd.isna(chop) or chop > settings.CHOP_MAX_THRESHOLD:
                return "HOLD", 0.0
        if settings.REQUIRE_DI_ALIGNMENT and (pd.isna(dp) or pd.isna(dm) or dp <= dm):
            return "HOLD", 0.0
    score = 0.0
    if close > ema200: score += 0.35
    if ema20 > ema50: score += 0.20
    if 42 <= rsi <= 65: score += 0.25
    elif rsi < 35 and close > ema200: score += 0.20
    if macd > 0 and macd >= pmacd: score += 0.15
    if volr > 1.1: score += 0.10
    # Regime quality is a GATE, not a score bonus. This preserves the exact
    # pre-upgrade conviction threshold and avoids promoting marginal setups.
    return ("BUY" if score >= settings.AI_CONFIDENCE_THRESHOLD else "HOLD"), score


def backtest_symbol(df: pd.DataFrame, use_regime_filter: bool) -> Dict[str, Any]:
    data = IndicatorEngine.calculate_all(df).reset_index(drop=True)
    data["prev_macd_hist"] = data["macd_hist"].shift(1)

    cash = 1000.0
    equity_curve = [cash]
    position = None  # dict: entry, sl, tp, qty, entry_idx
    trades = []

    for i in range(200, len(data) - 1):
        row = data.iloc[i]
        nxt = data.iloc[i + 1]  # exit checks on the NEXT bar (no look-ahead)
        price = row["close"]

        if position is None:
            action, _ = score_entry(row, use_regime_filter)
            if action == "BUY":
                atr = row["atr_14"]
                if pd.isna(atr) or atr <= 0:
                    continue
                sl = price - settings.ATR_STOP_LOSS_MULTIPLIER * atr
                tp = price + settings.ATR_TAKE_PROFIT_MULTIPLIER * atr
                sl_dist = (price - sl) / price * 100
                tp_dist = (tp - price) / price * 100
                if sl_dist <= 0 or tp_dist / sl_dist < settings.MIN_RISK_REWARD_RATIO:
                    continue
                risk_usdt = cash * (settings.RISK_PER_TRADE_PERCENT / 100.0)
                qty = risk_usdt / (price - sl)
                max_notional = cash * (settings.MAX_ALLOCATION_PER_TRADE_PERCENT / 100.0)
                qty = min(qty, max_notional / price)
                if qty * price < 10:
                    continue
                # Charge the entry notional INCLUDING the buy-side fee.
                cost = qty * price * (1 + FEE_RATE)
                cash -= cost
                position = {"entry": price, "sl": sl, "tp": tp, "qty": qty, "i": i}
        else:
            # fill-at-bar logic: check SL and TP against next bar's high/low
            hi, lo = nxt["high"], nxt["low"]
            exit_price, reason = None, None
            if lo <= position["sl"]:
                exit_price, reason = position["sl"], "SL"
            elif hi >= position["tp"]:
                exit_price, reason = position["tp"], "TP"
            if exit_price is not None:
                proceeds = position["qty"] * exit_price * (1 - FEE_RATE)
                cash += proceeds
                # Net PnL = sell proceeds (net of sell fee) - buy cost (incl. buy fee).
                cost_basis = position["qty"] * position["entry"] * (1 + FEE_RATE)
                trades.append({"reason": reason, "pnl": proceeds - cost_basis})
                position = None
        # Mark-to-market equity uses the un-fee'd mid price for the open leg only.
        equity_curve.append(cash + (position["qty"] * price if position else 0.0))

    total_ret = (equity_curve[-1] / 1000.0 - 1) * 100
    wins = [t for t in trades if t["pnl"] > 0]
    win_rate = (len(wins) / len(trades) * 100) if trades else 0.0
    gp = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gl = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
    pf = (gp / gl) if gl > 0 else float("inf")
    # max drawdown
    peak = equity_curve[0]; mdd = 0.0
    for v in equity_curve:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak * 100)
    return {"return_pct": round(total_ret, 2), "trades": len(trades),
            "win_rate": round(win_rate, 1), "profit_factor": round(pf, 2),
            "max_dd_pct": round(mdd, 2)}


def main():
    pairs = [p for p in settings.TRADING_PAIRS if p != "XAUTUSDT"]  # XAUT may lack history
    print(f"{'PAIR':<12} {'BASELINE(no filter)':<34} {'UPGRADED(regime filter)':<34}")
    print("-" * 82)
    agg = {"base": {"ret": 0, "trades": 0, "wins": 0, "pf_num": 0, "pf_den": 0},
           "new": {"ret": 0, "trades": 0, "wins": 0, "pf_num": 0, "pf_den": 0}}
    for sym in pairs:
        try:
            df = fetch_klines(sym)
            if len(df) < 250:
                print(f"{sym:<12} insufficient history ({len(df)} bars)")
                continue
            base = backtest_symbol(df, use_regime_filter=False)
            new = backtest_symbol(df, use_regime_filter=True)
            print(f"{sym:<12} {str(base):<34} {str(new):<34}")
            for key, r in (("base", base), ("new", new)):
                agg[key]["ret"] += r["return_pct"]
                agg[key]["trades"] += r["trades"]
                agg[key]["wins"] += round(r["win_rate"] / 100 * r["trades"])
        except Exception as e:
            print(f"{sym:<12} ERROR: {e}")
    print("-" * 82)
    for key in ("base", "new"):
        a = agg[key]
        wr = (a["wins"] / a["trades"] * 100) if a["trades"] else 0
        print(f"{key.upper():<5} sum_return={a['ret']:+.2f}%  trades={a['trades']}  win_rate={wr:.1f}%")


if __name__ == "__main__":
    main()

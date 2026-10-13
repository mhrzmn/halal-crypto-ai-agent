"""Diagnostic: isolate which regime sub-filter helps or hurts per Halal pair.

Purpose: the aggregate backtest showed the combined regime gate slightly HURT
overall (NEAR -4.3 pts). Before shipping a filter that trades one pair's edge for
another's, decompose its components:
  - ADX only
  - CHOP only
  - DI alignment only
  - ADX + CHOP (no DI)
  - full gate (ADX + CHOP + DI)
This is a research tool, not part of the live path.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings
from strategy.indicators import IndicatorEngine
from analysis.backtest_validation import fetch_klines, FEE_RATE

VARIANTS = ["baseline", "adx_only", "chop_only", "di_only", "adx_chop", "full"]


def gate_ok(row, variant: str) -> bool:
    adx, chop, dp, dm = row["adx_14"], row["chop_14"], row["di_plus"], row["di_minus"]
    if variant == "baseline":
        return True
    if pd.isna(adx) or pd.isna(chop):
        return False
    adx_ok = adx >= settings.ADX_TREND_THRESHOLD
    chop_ok = chop <= settings.CHOP_MAX_THRESHOLD
    di_ok = (not pd.isna(dp) and not pd.isna(dm)) and dp > dm
    if variant == "adx_only": return adx_ok
    if variant == "chop_only": return chop_ok
    if variant == "di_only": return di_ok
    if variant == "adx_chop": return adx_ok and chop_ok
    if variant == "full": return adx_ok and chop_ok and di_ok
    return True


def score(row):
    close, ema20, ema50, ema200 = row["close"], row["ema_20"], row["ema_50"], row["ema_200"]
    rsi, macd, pmacd, volr = row["rsi_14"], row["macd_hist"], row["prev_macd_hist"], row["vol_ratio"]
    if any(pd.isna(x) for x in [ema20, ema50, ema200, rsi, macd]):
        return 0.0
    s = 0.0
    if close > ema200: s += 0.35
    if ema20 > ema50: s += 0.20
    if 42 <= rsi <= 65: s += 0.25
    elif rsi < 35 and close > ema200: s += 0.20
    if macd > 0 and macd >= pmacd: s += 0.15
    if volr > 1.1: s += 0.10
    return s


def run(df, variant):
    data = IndicatorEngine.calculate_all(df).reset_index(drop=True)
    data["prev_macd_hist"] = data["macd_hist"].shift(1)
    cash, pos, trades = 1000.0, None, []
    for i in range(200, len(data) - 1):
        row, nxt = data.iloc[i], data.iloc[i + 1]
        price = row["close"]
        if pos is None:
            if gate_ok(row, variant) and score(row) >= settings.AI_CONFIDENCE_THRESHOLD:
                atr = row["atr_14"]
                if pd.isna(atr) or atr <= 0:
                    continue
                sl = price - settings.ATR_STOP_LOSS_MULTIPLIER * atr
                tp = price + settings.ATR_TAKE_PROFIT_MULTIPLIER * atr
                if (price - sl) <= 0:
                    continue
                qty = min(cash * settings.RISK_PER_TRADE_PERCENT / 100 / (price - sl),
                          cash * settings.MAX_ALLOCATION_PER_TRADE_PERCENT / 100 / price)
                if qty * price < 10:
                    continue
                cash -= qty * price * (1 + FEE_RATE)
                pos = {"entry": price, "sl": sl, "tp": tp, "qty": qty}
        else:
            hi, lo = nxt["high"], nxt["low"]
            ex = pos["sl"] if lo <= pos["sl"] else (pos["tp"] if hi >= pos["tp"] else None)
            if ex is not None:
                cash += pos["qty"] * ex * (1 - FEE_RATE)
                trades.append(pos["qty"] * (ex - pos["entry"]) - pos["qty"] * (pos["entry"] + ex) * FEE_RATE)
                pos = None
    return round((cash - 1000) / 10, 2), len(trades)


def main():
    pairs = [p for p in settings.TRADING_PAIRS if p != "XAUTUSDT"]
    data = {}
    for s in pairs:
        try:
            df = fetch_klines(s)
            if len(df) >= 250:
                data[s] = df
        except Exception as e:
            print(f"{s} skip: {e}")
    hdr = f"{'PAIR':<11}" + "".join(f"{v:>12}" for v in VARIANTS)
    print(hdr); print("-" * len(hdr))
    totals = {v: 0.0 for v in VARIANTS}
    for s, df in data.items():
        row = f"{s:<11}"
        for v in VARIANTS:
            ret, _ = run(df, v)
            totals[v] += ret
            row += f"{ret:>12.2f}"
        print(row)
    print("-" * len(hdr))
    print(f"{'TOTAL':<11}" + "".join(f"{totals[v]:>12.2f}" for v in VARIANTS))


if __name__ == "__main__":
    main()

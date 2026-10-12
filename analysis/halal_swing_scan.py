"""
Halal high-liquidity swing-potential scanner (read-only, public Binance API).

Ranks the project's halal-whitelisted base assets (BTC, ETH, SOL, LINK, AVAX,
POL, NEAR, DOT, ADA) against USDT by:
  - Liquidity gate: 24h quote volume (USDT)
  - Volatility: daily ATR% and 4h ATR% (profit potential per swing)
  - Trend: price vs EMA50/EMA200 on 1d and 4h (closed candles)
  - Estimated swing move: daily ATR% x expected hold days, trend-adjusted

No API keys required (public market data endpoints only).
"""

import json
import math
import sys
import time

import requests

BASE = "https://api.binance.com"
HALAL_BASES = ["BTC", "ETH", "SOL", "LINK", "AVAX", "POL", "NEAR", "DOT", "ADA"]
QUOTE = "USDT"
MIN_24H_QUOTE_VOLUME = 10_000_000  # USD liquidity gate
HOLD_DAYS = 4  # expected swing hold for move estimation


def get(path, params=None):
    r = requests.get(BASE + path, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def ema(values, period):
    k = 2.0 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def atr_pct(klines, period=14):
    # klines: list of [openTime, open, high, low, close, ...]; use closed candles only
    closed = klines[:-1] if len(klines) > 1 else klines
    trs = []
    prev_close = float(closed[0][4])
    for k in closed[1:]:
        high, low, close = float(k[2]), float(k[3]), float(k[4])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
        prev_close = close
    if len(trs) < period:
        return None
    atr = sum(trs[-period:]) / period
    last_close = float(closed[-1][4])
    return atr / last_close * 100.0


def analyze(symbol):
    d = get("/api/v3/klines", {"symbol": symbol, "interval": "1d", "limit": 260})
    h4 = get("/api/v3/klines", {"symbol": symbol, "interval": "4h", "limit": 260})

    d_closed = d[:-1]
    closes_d = [float(k[4]) for k in d_closed]
    closes_h = [float(k[4]) for k in h4[:-1]]

    price = closes_d[-1]
    ema50_d = ema(closes_d[-60:], 50)
    ema200_d = ema(closes_d, 200) if len(closes_d) >= 200 else None
    ema50_h = ema(closes_h[-60:], 50)
    ema200_h = ema(closes_h, 200) if len(closes_h) >= 200 else None

    atr_d = atr_pct(d, 14)
    atr_h = atr_pct(h4, 14)

    # Trend scoring: +1 above, -1 below for each of 4 references
    score = 0
    refs = [(price, ema50_d), (price, ema200_d), (price, ema50_h), (price, ema200_h)]
    for p, e in refs:
        if e is not None:
            score += 1 if p > e else -1

    est_move = atr_d * math.sqrt(HOLD_DAYS) if atr_d else None  # ~random-walk scaling
    return {
        "symbol": symbol,
        "price": price,
        "atr_1d_pct": atr_d,
        "atr_4h_pct": atr_h,
        "ema50_1d": ema50_d,
        "ema200_1d": ema200_d,
        "trend_score": score,  # -4..+4
        "est_swing_move_pct": est_move,
    }


def main():
    tickers = get("/api/v3/ticker/24hr")
    vol_map = {t["symbol"]: float(t["quoteVolume"]) for t in tickers}

    rows = []
    for base in HALAL_BASES:
        symbol = base + QUOTE
        qv = vol_map.get(symbol, 0.0)
        try:
            info = analyze(symbol)
        except Exception as exc:
            print(f"WARN {symbol}: {exc}", file=sys.stderr)
            continue
        info["quote_volume_24h"] = qv
        info["liquid"] = qv >= MIN_24H_QUOTE_VOLUME
        # Opportunity score: expected % move, boosted for uptrend alignment,
        # penalized for counter-trend. Liquidity is a gate, not a score.
        trend_mult = {4: 1.3, 3: 1.15, 2: 1.0, 1: 0.85, 0: 0.7}.get(
            info["trend_score"], 0.5 if info["trend_score"] < 0 else 0.7
        )
        if info["trend_score"] < 0:
            trend_mult = 0.5
        info["opportunity_score"] = round(info["est_swing_move_pct"] * trend_mult, 2)
        rows.append(info)
        time.sleep(0.15)

    rows.sort(key=lambda r: (r["liquid"], r["opportunity_score"]), reverse=True)

    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "quote": QUOTE, "hold_days_assumed": HOLD_DAYS, "results": rows}
    with open("analysis/halal_swing_scan.json", "w") as f:
        json.dump(out, f, indent=2)

    hdr = f"{'#':<3}{'Pair':<10}{'Price':>12}{'24hVol($M)':>12}{'ATR1d%':>8}{'ATR4h%':>8}{'Trend':>7}{'EstMove%':>9}{'Score':>7}{'Liquid':>8}"
    print(hdr)
    print("-" * len(hdr))
    for i, r in enumerate(rows, 1):
        print(f"{i:<3}{r['symbol']:<10}{r['price']:>12,.4g}{r['quote_volume_24h']/1e6:>12,.0f}"
              f"{r['atr_1d_pct']:>8.2f}{r['atr_4h_pct']:>8.2f}{r['trend_score']:>+7d}"
              f"{r['est_swing_move_pct']:>9.2f}{r['opportunity_score']:>7.2f}"
              f"{'YES' if r['liquid'] else 'no':>8}")


if __name__ == "__main__":
    main()

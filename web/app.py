"""
FastAPI Backend & Real-Time Trading Controller.
Serves the live visual dashboard, streams equity curves, handles Demo/Real toggles,
model switching, emergency controls, and runs the token-optimized autonomous scheduler.
"""

import os
import time
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from config.settings import settings
from config.halal_whitelist import HALAL_WHITELIST, HARAM_BLACKLIST, is_pair_halal
from core.binance_client import BinanceSpotClient
from core.shariah_guard import ShariahComplianceGuard
from storage.database import Database
from strategy.indicators import IndicatorEngine
from strategy.ai_predictor import AIPredictor, AIPredictionResult
from risk.risk_manager import RiskManager
from execution.bot_engine import BotEngine

app = FastAPI(title="Halal Crypto AI Trading Dashboard")

# Templates
templates = Jinja2Templates(directory="web/templates")

# Global instances
db = Database()
client = BinanceSpotClient()
# Market data for DISPLAY always comes from the real public Binance API,
# even when BINANCE_USE_TESTNET=true (klines/ticker are public, no keys needed).
# The trading `client` above still respects the testnet flag for order placement.
market_client = BinanceSpotClient(use_testnet=False)
predictor = AIPredictor()
engine = BotEngine(binance_client=client, database=db)

# State for the adaptive token-saving scheduler
scheduler_state = {
    "is_running": True,
    "current_model": settings.AI_PROVIDER,
    "last_ai_scan_timestamp": 0,
    "next_recheck_minutes": 15,
    "target_profit_percent": 5.0,
    "active_scan_in_progress": False
}

class SettingsPayload(BaseModel):
    is_paper: Optional[bool] = None
    model_provider: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    custom_base_url: Optional[str] = None
    custom_model_name: Optional[str] = None
    custom_api_key: Optional[str] = None
    target_profit_percent: Optional[float] = None
    reset_demo_balance: Optional[float] = None

@app.on_event("startup")
async def startup_event():
    """Start the lightweight background price & stop-loss sentinel."""
    asyncio.create_task(autonomous_background_loop())

async def autonomous_background_loop():
    """
    Lightweight background sentinel:
    1. Every 15s: Free public check on open positions (SL/TP triggers & equity snapshot).
    2. Every adaptive N minutes: Full AI prediction & scan cycle (token-optimized).
    """
    while True:
        try:
            if scheduler_state["is_running"]:
                await run_sentinel_cycle()
        except Exception as e:
            print(f"[Sentinel Error]: {e}")
        await asyncio.sleep(15)

async def run_sentinel_cycle():
    """Execute rapid position checks and trigger AI rechecks when timer elapses."""
    now = time.time()
    positions = db.get_all_active_positions()
    is_paper = settings.PAPER_TRADING

    # 1. Zero-token Stop-Loss / Take-Profit sentinel
    invested_val = 0.0
    for pos in positions:
        sym = pos["symbol"]
        qty = pos["quantity"]
        entry = pos["entry_price"]
        sl = pos["stop_loss"]
        tp = pos["take_profit"]
        highest = pos["highest_price"]

        try:
            # Blocking HTTP call moved off the event loop
            curr_price = await asyncio.to_thread(market_client.get_ticker_price, sym)
            invested_val += (curr_price * qty)

            if curr_price > highest:
                db.update_position_highest_price(sym, curr_price)
                highest = curr_price

            should_exit, reason = RiskManager.evaluate_position_exit(
                entry_price=entry,
                current_price=curr_price,
                stop_loss=sl,
                take_profit=tp,
                highest_price_seen=highest
            )

            if should_exit:
                # Route through the engine: atomic close + balance credit (paper)
                # or ownership-audited live sell with real fill price.
                await asyncio.to_thread(
                    engine._execute_sell, sym, qty, curr_price, reason
                )
                print(f"[Sentinel Exit Triggered]: {sym} closed at ${curr_price:.2f} ({reason})")
        except Exception as e:
            print(f"Error checking position {sym}: {e}")

    # Record equity snapshot for the live graph
    try:
        cash = db.get_paper_balance() if is_paper else await asyncio.to_thread(client.get_spot_account_balance, "USDT")
        total_equity = cash + invested_val
        db.record_portfolio_snapshot(total_equity, cash, invested_val)
    except Exception as e:
        print(f"[Sentinel] Could not record equity snapshot: {e}")

    # 2. Check if adaptive strategic AI sleep has elapsed
    time_since_ai_scan = (now - scheduler_state["last_ai_scan_timestamp"]) / 60.0
    if time_since_ai_scan >= scheduler_state["next_recheck_minutes"] and not scheduler_state["active_scan_in_progress"]:
        await execute_full_ai_scan()

async def execute_full_ai_scan():
    """
    Run one consolidated trading cycle through the shared BotEngine,
    then generate and persist a fresh AI market prediction so the
    dashboard "AI Prediction Brain" card always reflects the latest scan.
    """
    scheduler_state["active_scan_in_progress"] = True
    try:
        result = await asyncio.to_thread(engine.scan_and_execute_cycle)

        for action in result.get("actions_taken", []):
            print(f"[Engine Action]: {action.get('type')} {action.get('symbol')} ({action.get('reason', action.get('rationale', ''))})")
        for err in result.get("errors", []):
            print(f"[Engine Error]: {err}")

        # Generate and persist a fresh forecast for EVERY scanned pair —
        # the dashboard shows one Brain row per trading pair.
        scanned = result.get("pairs_scanned") or []
        symbols = [p["symbol"] for p in scanned] or list(settings.TRADING_PAIRS)
        rechecks = []
        for sym in symbols:
            try:
                recheck = await asyncio.to_thread(_generate_and_save_prediction, sym)
                if recheck:
                    rechecks.append(recheck)
            except Exception as e:
                print(f"[Prediction Error {sym}]: {e}")
        if rechecks:
            scheduler_state["next_recheck_minutes"] = max(5, min(60, min(rechecks)))

        scheduler_state["last_ai_scan_timestamp"] = time.time()
    finally:
        scheduler_state["active_scan_in_progress"] = False


def _generate_and_save_prediction(symbol: str) -> Optional[int]:
    """Run AIPredictor on fresh candles and store the forecast in the DB."""
    df = market_client.get_klines(symbol, interval=settings.CANDLE_TIMEFRAME, limit=settings.CANDLE_LIMIT)
    df = BotEngine._signal_frame(df)
    df_calc = IndicatorEngine.calculate_all(df)
    snapshot = IndicatorEngine.get_latest_snapshot(df_calc)

    pos = db.get_active_position(symbol)
    prediction = predictor.predict_market_movement(
        symbol=symbol,
        df_candles=df,
        snapshot=snapshot,
        has_open_position=bool(pos),
        entry_price=pos["entry_price"] if pos else None
    )

    action = "BUY" if prediction.predicted_direction in ("BULLISH_EXPANSION", "MEAN_REVERSION_BOUNCE") else \
             ("SELL" if prediction.predicted_direction == "BEARISH_CONTINUATION" else "HOLD")

    db.save_ai_prediction(
        symbol=symbol,
        predicted_direction=prediction.predicted_direction,
        target_price=prediction.target_price,
        invalidation_price=prediction.invalidation_price,
        action=action,
        confidence=prediction.confidence,
        current_price=float(snapshot["close"]),
        next_recheck_minutes=prediction.next_recheck_minutes,
        thesis=prediction.thesis,
        model_used=predictor.model_name
    )
    return prediction.next_recheck_minutes

# -------------------------------------------------------------
# REST API ENDPOINTS
# -------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """Serve the single-page dashboard."""
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/api/status")
async def get_dashboard_status():
    """Live status summary for UI polling."""
    is_paper = settings.PAPER_TRADING
    cash = db.get_paper_balance() if is_paper else await asyncio.to_thread(client.get_spot_account_balance, "USDT")
    positions = db.get_all_active_positions()

    # Calculate live prices & unrealized PnL for positions
    invested_val = 0.0
    active_cards = []
    for p in positions:
        try:
            curr_p = await asyncio.to_thread(market_client.get_ticker_price, p["symbol"])
            unrealized_pnl = (curr_p - p["entry_price"]) * p["quantity"]
            unrealized_pct = ((curr_p - p["entry_price"]) / p["entry_price"]) * 100.0
            invested_val += (curr_p * p["quantity"])
            active_cards.append({
                "symbol": p["symbol"],
                "quantity": p["quantity"],
                "entry_price": p["entry_price"],
                "current_price": curr_p,
                "stop_loss": p["stop_loss"],
                "take_profit": p["take_profit"],
                "highest_price": p["highest_price"],
                "unrealized_pnl_usdt": round(unrealized_pnl, 2),
                "unrealized_pnl_pct": round(unrealized_pct, 2)
            })
        except Exception:
            invested_val += (p["entry_price"] * p["quantity"])

    total_equity = cash + invested_val
    perf = db.get_performance_summary()
    latest_pred = db.get_latest_ai_prediction()
    pair_predictions = db.get_latest_predictions_per_symbol(list(settings.TRADING_PAIRS))
    pending_entries = db.get_pending_entries()

    # Time remaining until next AI scan
    elapsed_seconds = time.time() - scheduler_state["last_ai_scan_timestamp"]
    total_wait_seconds = scheduler_state["next_recheck_minutes"] * 60
    remaining_seconds = max(0, int(total_wait_seconds - elapsed_seconds))

    # Calculate goal progress
    start_equity = settings.INITIAL_PAPER_BALANCE_USDT
    target_equity = start_equity * (1.0 + (scheduler_state["target_profit_percent"] / 100.0))
    current_profit_pct = round(((total_equity - start_equity) / start_equity) * 100.0, 2)

    return {
        "is_paper": is_paper,
        "mode_label": "DEMO SANDBOX" if is_paper else "REAL BINANCE SPOT",
        "current_model": predictor.model_name,
        "cash_balance": round(cash, 2),
        "invested_value": round(invested_val, 2),
        "total_equity": round(total_equity, 2),
        "target_profit_percent": scheduler_state["target_profit_percent"],
        "current_profit_pct": current_profit_pct,
        "performance": perf,
        "active_positions": active_cards,
        "pending_entries": pending_entries,
        "latest_prediction": latest_pred,
        "pair_predictions": pair_predictions,
        "next_recheck_seconds": remaining_seconds,
        "next_recheck_minutes": scheduler_state["next_recheck_minutes"],
        "is_running": scheduler_state["is_running"],
        "scan_in_progress": scheduler_state["active_scan_in_progress"],
        "last_scan_at": scheduler_state["last_ai_scan_timestamp"],
        "trading_pairs": settings.TRADING_PAIRS,
        "custom_base_url": settings.CUSTOM_BASE_URL,
        "custom_model_name": settings.CUSTOM_MODEL_NAME
    }

@app.get("/api/price-chart")
async def get_price_chart(symbol: str = "BTCUSDT", interval: str = "15m", limit: int = 200):
    """Return real exchange OHLC candles for the price chart (lightweight-charts)."""
    symbol = (symbol or "BTCUSDT").upper()
    if symbol not in settings.TRADING_PAIRS:
        return JSONResponse(status_code=400, content={"error": f"Symbol {symbol} not in configured trading pairs"})

    allowed_intervals = {"5m", "15m", "1h", "4h", "1d"}
    if interval not in allowed_intervals:
        interval = settings.CANDLE_TIMEFRAME if settings.CANDLE_TIMEFRAME in allowed_intervals else "15m"
    limit = max(50, min(500, int(limit)))

    df = await asyncio.to_thread(market_client.get_klines, symbol, interval, limit)
    candles = []
    for ts, row in df.iterrows():
        candles.append({
            "time": int(ts.timestamp()),
            "open": round(float(row["open"]), 6),
            "high": round(float(row["high"]), 6),
            "low": round(float(row["low"]), 6),
            "close": round(float(row["close"]), 6),
            "volume": round(float(row["volume"]), 2)
        })

    # Overlay open position levels so the trader sees SL/TP against real price action
    pos = db.get_active_position(symbol)
    levels = None
    if pos:
        levels = {
            "entry": pos["entry_price"],
            "stop_loss": pos["stop_loss"],
            "take_profit": pos["take_profit"]
        }

    return {"symbol": symbol, "interval": interval, "candles": candles, "position_levels": levels}

# Supported chart timeframes: query param `range` -> hours of history (None = all)
CHART_RANGES_HOURS = {
    "1h": 1.0,
    "6h": 6.0,
    "24h": 24.0,
    "7d": 24.0 * 7,
    "30d": 24.0 * 30,
    "all": None,
}

@app.get("/api/chart-data")
async def get_chart_data(range: str = "24h"):
    """Return historical equity data for Chart.js rendering, filtered by timeframe."""
    range_key = (range or "24h").lower()
    if range_key not in CHART_RANGES_HOURS:
        range_key = "24h"
    hours = CHART_RANGES_HOURS[range_key]

    if hours is None:
        snapshots = db.get_portfolio_snapshots(limit=100000, max_points=500)
    else:
        # Show intraday ranges at full resolution, downsample long ranges
        max_pts = 300 if hours <= 24 else 500
        snapshots = db.get_portfolio_snapshots(hours=hours, max_points=max_pts)

    labels = []
    equity_points = []
    cash_points = []
    # Show date+time for multi-day ranges, time only for intraday
    show_date = hours is None or hours > 24

    for s in snapshots:
        ts = s["timestamp"]
        if "T" in ts:
            time_part = ts.split("T")[1][:5]
            date_part = ts.split("T")[0][5:]  # MM-DD
            labels.append(f"{date_part} {time_part}" if show_date else time_part)
        else:
            labels.append(ts[-5:])
        equity_points.append(s["total_equity"])
        cash_points.append(s["cash_balance"])

    return {
        "labels": labels,
        "equity": equity_points,
        "cash": cash_points,
        "range": range_key
    }

@app.get("/api/trades")
async def get_recent_trades():
    """Return trade history with fee transparency."""
    trades = db.get_trade_history(limit=1000)
    return {"trades": trades}

@app.get("/api/ai-forecasts")
async def get_ai_forecasts():
    """Return recent AI market predictions."""
    preds = db.get_recent_ai_predictions(limit=15)
    return {"predictions": preds}

@app.post("/api/settings")
async def update_settings(payload: SettingsPayload):
    """Update settings on the fly and persist to .env."""
    import dotenv
    env_file = ".env"

    if payload.is_paper is not None:
        settings.PAPER_TRADING = payload.is_paper
        try:
            dotenv.set_key(env_file, "PAPER_TRADING", "true" if payload.is_paper else "false")
        except Exception as e:
            print(f"[Dotenv write warning]: {e}")

    if payload.model_provider:
        predictor.model_name = payload.model_provider
        if "gemini" in payload.model_provider:
            predictor.provider = "gemini"
            settings.AI_PROVIDER = "gemini"
        elif "gpt" in payload.model_provider:
            predictor.provider = "openai"
            settings.AI_PROVIDER = "openai"
        elif "deepseek" in payload.model_provider:
            predictor.provider = "deepseek"
            settings.AI_PROVIDER = "deepseek"
        elif payload.model_provider == "custom":
            predictor.provider = "custom"
            settings.AI_PROVIDER = "custom"
        elif payload.model_provider == "algorithmic":
            predictor.provider = "algorithmic"
            settings.AI_PROVIDER = "algorithmic"

        try:
            dotenv.set_key(env_file, "AI_PROVIDER", settings.AI_PROVIDER)
        except Exception:
            pass

    if payload.gemini_api_key:
        clean_key = payload.gemini_api_key.strip()
        settings.GEMINI_API_KEY = clean_key
        predictor.gemini_key = clean_key
        try:
            dotenv.set_key(env_file, "GEMINI_API_KEY", clean_key)
        except Exception:
            pass

    if payload.openai_api_key:
        clean_key = payload.openai_api_key.strip()
        settings.OPENAI_API_KEY = clean_key
        predictor.openai_key = clean_key
        try:
            dotenv.set_key(env_file, "OPENAI_API_KEY", clean_key)
        except Exception:
            pass

    if payload.custom_base_url is not None:
        clean_url = payload.custom_base_url.strip()
        settings.CUSTOM_BASE_URL = clean_url
        predictor.custom_base_url = clean_url
        if clean_url:
            predictor.provider = "custom"
            settings.AI_PROVIDER = "custom"
        try:
            dotenv.set_key(env_file, "CUSTOM_BASE_URL", clean_url)
            dotenv.set_key(env_file, "AI_PROVIDER", settings.AI_PROVIDER)
        except Exception:
            pass

    if payload.custom_model_name is not None and payload.custom_model_name.strip():
        clean_model = payload.custom_model_name.strip()
        settings.CUSTOM_MODEL_NAME = clean_model
        predictor.custom_model_name = clean_model
        predictor.model_name = clean_model
        try:
            dotenv.set_key(env_file, "CUSTOM_MODEL_NAME", clean_model)
        except Exception:
            pass

    if payload.custom_api_key is not None and payload.custom_api_key.strip():
        clean_key = payload.custom_api_key.strip()
        settings.CUSTOM_API_KEY = clean_key
        predictor.custom_api_key = clean_key
        try:
            dotenv.set_key(env_file, "CUSTOM_API_KEY", clean_key)
        except Exception:
            pass

    if payload.target_profit_percent is not None:
        scheduler_state["target_profit_percent"] = payload.target_profit_percent
    if payload.reset_demo_balance is not None:
        db.reset_demo_account(payload.reset_demo_balance)

    return {"status": "success", "message": "Settings updated and saved to .env successfully."}

@app.post("/api/force-scan")
async def force_ai_scan(background_tasks: BackgroundTasks):
    """Force an immediate full AI prediction scan (no-op while one is running)."""
    if scheduler_state["active_scan_in_progress"]:
        return {"status": "busy", "message": "An AI scan is already in progress."}
    background_tasks.add_task(execute_full_ai_scan)
    scheduler_state["active_scan_in_progress"] = True
    return {"status": "success", "message": "Triggered immediate AI market prediction."}

class TogglePayload(BaseModel):
    is_running: bool

@app.post("/api/toggle-bot")
async def toggle_bot(payload: TogglePayload):
    """Pause/resume the autonomous sentinel (safe kill switch — no funds moved)."""
    scheduler_state["is_running"] = payload.is_running
    return {"status": "success", "is_running": scheduler_state["is_running"]}

@app.post("/api/panic-sell")
async def panic_sell_all():
    """Emergency Flatten to Cash: Sells all active positions to USDT."""
    result = await asyncio.to_thread(engine.panic_sell_all)
    return {
        "status": "success" if not result["errors"] else "partial",
        "closed_positions": result["closed_positions"],
        "errors": result["errors"]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.app:app", host="127.0.0.1", port=8000, reload=False)

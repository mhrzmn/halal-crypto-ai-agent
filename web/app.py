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

app = FastAPI(title="Halal Crypto AI Trading Dashboard")

# Templates
templates = Jinja2Templates(directory="web/templates")

# Global instances
db = Database()
client = BinanceSpotClient()
predictor = AIPredictor()

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
            curr_price = client.get_ticker_price(sym)
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
                closed = db.close_active_position(sym, curr_price, reason)
                if is_paper and closed:
                    bal = db.get_paper_balance()
                    db.update_paper_balance(round(bal + (qty * curr_price), 2))
                print(f"[Sentinel Exit Triggered]: {sym} closed at ${curr_price:.2f} ({reason})")
        except Exception as e:
            print(f"Error checking position {sym}: {e}")

    # Record equity snapshot for the live graph
    cash = db.get_paper_balance() if is_paper else client.get_spot_account_balance("USDT")
    total_equity = cash + invested_val
    db.record_portfolio_snapshot(total_equity, cash, invested_val)

    # 2. Check if adaptive strategic AI sleep has elapsed
    time_since_ai_scan = (now - scheduler_state["last_ai_scan_timestamp"]) / 60.0
    if time_since_ai_scan >= scheduler_state["next_recheck_minutes"] and not scheduler_state["active_scan_in_progress"]:
        await execute_full_ai_scan()

async def execute_full_ai_scan():
    """Run pure AI market prediction across whitelisted pairs."""
    scheduler_state["active_scan_in_progress"] = True
    try:
        is_paper = settings.PAPER_TRADING
        cash = db.get_paper_balance() if is_paper else client.get_spot_account_balance("USDT")
        positions = db.get_all_active_positions()
        best_candidate = None
        min_recheck_time = 60

        for symbol in settings.TRADING_PAIRS:
            # Skip if we already own this asset
            if any(p["symbol"] == symbol for p in positions):
                continue

            try:
                df = client.get_klines(symbol, interval=settings.CANDLE_TIMEFRAME, limit=40)
                df_calc = IndicatorEngine.calculate_all(df)
                snapshot = IndicatorEngine.get_latest_snapshot(df_calc)

                pred = predictor.predict_market_movement(
                    symbol=symbol,
                    df_candles=df_calc,
                    snapshot=snapshot,
                    has_open_position=False
                )

                # Track lowest strategic wait time
                min_recheck_time = min(min_recheck_time, pred.next_recheck_minutes)

                # Save forecast to database
                db.save_ai_prediction(
                    symbol=symbol,
                    predicted_direction=pred.predicted_direction,
                    target_price=pred.target_price,
                    invalidation_price=pred.invalidation_price,
                    action=pred.action,
                    confidence=pred.confidence,
                    current_price=pred.current_price,
                    next_recheck_minutes=pred.next_recheck_minutes,
                    thesis=pred.thesis,
                    model_used=pred.model_used
                )

                if pred.action == "BUY" and pred.confidence >= settings.AI_CONFIDENCE_THRESHOLD:
                    if not best_candidate or pred.confidence > best_candidate.confidence:
                        best_candidate = pred
            except Exception as e:
                print(f"AI Scan Error for {symbol}: {e}")

        # Update adaptive timer based on AI recommendation
        scheduler_state["next_recheck_minutes"] = max(5, min_recheck_time)
        scheduler_state["last_ai_scan_timestamp"] = time.time()

        # Place trade if high-conviction candidate identified
        if best_candidate and cash >= 15.0:
            sym = best_candidate.symbol
            curr_p = best_candidate.current_price
            sl = best_candidate.invalidation_price
            tp = best_candidate.target_price

            size_res = RiskManager.calculate_spot_position_size(
                available_usdt=cash,
                current_price=curr_p,
                stop_loss_price=sl,
                symbol=sym
            )

            if size_res.is_valid:
                cost = round(size_res.quantity * curr_p, 2)
                if is_paper:
                    db.update_paper_balance(round(cash - cost, 2))
                    db.save_active_position(
                        symbol=sym,
                        quantity=size_res.quantity,
                        entry_price=curr_p,
                        stop_loss=sl,
                        take_profit=tp,
                        is_paper=True
                    )
                else:
                    client.place_spot_order(
                        symbol=sym,
                        side="BUY",
                        quantity=size_res.quantity,
                        order_type="MARKET"
                    )
                    db.save_active_position(
                        symbol=sym,
                        quantity=size_res.quantity,
                        entry_price=curr_p,
                        stop_loss=sl,
                        take_profit=tp,
                        is_paper=False
                    )
                print(f"[AI Trade Placed]: {sym} - Qty: {size_res.quantity} @ ${curr_p:.2f} ({best_candidate.thesis})")
    finally:
        scheduler_state["active_scan_in_progress"] = False

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
    cash = db.get_paper_balance() if is_paper else client.get_spot_account_balance("USDT")
    positions = db.get_all_active_positions()

    # Calculate live prices & unrealized PnL for positions
    invested_val = 0.0
    active_cards = []
    for p in positions:
        try:
            curr_p = client.get_ticker_price(p["symbol"])
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
        "latest_prediction": latest_pred,
        "next_recheck_seconds": remaining_seconds,
        "next_recheck_minutes": scheduler_state["next_recheck_minutes"],
        "custom_base_url": settings.CUSTOM_BASE_URL,
        "custom_model_name": settings.CUSTOM_MODEL_NAME
    }

@app.get("/api/chart-data")
async def get_chart_data():
    """Return historical equity data for Chart.js rendering."""
    snapshots = db.get_portfolio_snapshots(limit=100)
    labels = []
    equity_points = []
    cash_points = []

    for s in snapshots:
        t_str = s["timestamp"].split("T")[1][:5] if "T" in s["timestamp"] else s["timestamp"][-5:]
        labels.append(t_str)
        equity_points.append(s["total_equity"])
        cash_points.append(s["cash_balance"])

    return {
        "labels": labels,
        "equity": equity_points,
        "cash": cash_points
    }

@app.get("/api/trades")
async def get_recent_trades():
    """Return trade history with fee transparency."""
    trades = db.get_trade_history(limit=50)
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
    """Force an immediate full AI prediction scan."""
    background_tasks.add_task(execute_full_ai_scan)
    return {"status": "success", "message": "Triggered immediate AI market prediction."}

@app.post("/api/panic-sell")
async def panic_sell_all():
    """Emergency Flatten to Cash: Sells all active positions to USDT."""
    positions = db.get_all_active_positions()
    closed_items = []
    is_paper = settings.PAPER_TRADING

    for pos in positions:
        sym = pos["symbol"]
        qty = pos["quantity"]
        curr_p = client.get_ticker_price(sym)

        if not is_paper:
            client.place_spot_order(sym, "SELL", qty, order_type="MARKET")

        closed = db.close_active_position(sym, curr_p, "EMERGENCY_PANIC_SELL")
        if is_paper and closed:
            bal = db.get_paper_balance()
            db.update_paper_balance(round(bal + (qty * curr_p), 2))
        closed_items.append(sym)

    return {"status": "success", "closed_positions": closed_items}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.app:app", host="127.0.0.1", port=8000, reload=False)

"""
Enhanced SQLite Persistence Engine.
Tracks paper & live portfolios, active positions, detailed trade history with fees,
equity snapshots for live graphing, and AI prediction logs.
"""

import sqlite3
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from config.settings import settings

class Database:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.DB_PATH
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create database tables if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Paper Account Balance Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS paper_account (
                    id INTEGER PRIMARY KEY,
                    usdt_balance REAL NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # 2. Active Positions Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS active_positions (
                    symbol TEXT PRIMARY KEY,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    highest_price REAL NOT NULL,
                    entry_time TEXT NOT NULL,
                    is_paper INTEGER NOT NULL
                )
            """)

            # 3. Trade History Table with Fee Tracking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    buy_price REAL NOT NULL,
                    sell_price REAL NOT NULL,
                    fee_usdt REAL NOT NULL DEFAULT 0.0,
                    pnl_usdt REAL NOT NULL,
                    pnl_net_usdt REAL NOT NULL DEFAULT 0.0,
                    pnl_pct REAL NOT NULL,
                    exit_reason TEXT NOT NULL,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT NOT NULL,
                    is_paper INTEGER NOT NULL
                )
            """)

            # 4. Portfolio Snapshots (For Live Equity Curve Chart)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    total_equity REAL NOT NULL,
                    cash_balance REAL NOT NULL,
                    invested_value REAL NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)

            # 5. Full AI Predictions & Market Forecasts
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ai_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    predicted_direction TEXT NOT NULL,
                    target_price REAL NOT NULL,
                    invalidation_price REAL NOT NULL,
                    action TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    current_price REAL NOT NULL,
                    next_recheck_minutes INTEGER NOT NULL DEFAULT 15,
                    thesis TEXT NOT NULL,
                    model_used TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            # Initialize paper balance if empty
            cursor.execute("SELECT COUNT(*) FROM paper_account")
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    "INSERT INTO paper_account (id, usdt_balance, updated_at) VALUES (1, ?, ?)",
                    (settings.INITIAL_PAPER_BALANCE_USDT, datetime.utcnow().isoformat())
                )

            # Initialize initial portfolio snapshot if empty
            cursor.execute("SELECT COUNT(*) FROM portfolio_snapshots")
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    "INSERT INTO portfolio_snapshots (total_equity, cash_balance, invested_value, timestamp) VALUES (?, ?, 0.0, ?)",
                    (settings.INITIAL_PAPER_BALANCE_USDT, settings.INITIAL_PAPER_BALANCE_USDT, datetime.utcnow().isoformat())
                )
            conn.commit()

    def get_paper_balance(self) -> float:
        """Get current simulated USDT balance."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT usdt_balance FROM paper_account WHERE id = 1")
            row = cursor.fetchone()
            return float(row["usdt_balance"]) if row else settings.INITIAL_PAPER_BALANCE_USDT

    def update_paper_balance(self, new_balance: float) -> None:
        """Update simulated USDT balance."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE paper_account SET usdt_balance = ?, updated_at = ? WHERE id = 1",
                (new_balance, datetime.utcnow().isoformat())
            )
            conn.commit()

    def reset_demo_account(self, initial_balance: float = 1000.0) -> None:
        """Reset paper trading balance and clear active positions."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE paper_account SET usdt_balance = ?, updated_at = ? WHERE id = 1",
                (initial_balance, datetime.utcnow().isoformat())
            )
            cursor.execute("DELETE FROM active_positions WHERE is_paper = 1")
            cursor.execute(
                "INSERT INTO portfolio_snapshots (total_equity, cash_balance, invested_value, timestamp) VALUES (?, ?, 0.0, ?)",
                (initial_balance, initial_balance, datetime.utcnow().isoformat())
            )
            conn.commit()

    def get_active_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieve active position for a symbol."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM active_positions WHERE symbol = ?", (symbol.upper(),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_active_positions(self) -> List[Dict[str, Any]]:
        """Retrieve all open positions."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM active_positions")
            return [dict(row) for row in cursor.fetchall()]

    def save_active_position(
        self,
        symbol: str,
        quantity: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        is_paper: bool = True
    ) -> None:
        """Save a new opened spot position."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO active_positions
                (symbol, quantity, entry_price, stop_loss, take_profit, highest_price, entry_time, is_paper)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol.upper(), quantity, entry_price, stop_loss, take_profit,
                entry_price, datetime.utcnow().isoformat(), 1 if is_paper else 0
            ))
            conn.commit()

    def update_position_highest_price(self, symbol: str, highest_price: float) -> None:
        """Update high watermark for trailing stop calculations."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE active_positions SET highest_price = ? WHERE symbol = ?",
                (highest_price, symbol.upper())
            )
            conn.commit()

    def close_active_position(
        self,
        symbol: str,
        sell_price: float,
        exit_reason: str,
        fee_rate: float = 0.001  # Binance 0.1% spot fee
    ) -> Optional[Dict[str, Any]]:
        """Close an active position, calculate fees, and record trade history."""
        pos = self.get_active_position(symbol)
        if not pos:
            return None

        buy_price = pos["entry_price"]
        qty = pos["quantity"]

        # Fee calculation: 0.1% on buy notional + 0.1% on sell notional
        buy_notional = buy_price * qty
        sell_notional = sell_price * qty
        total_fee = round((buy_notional + sell_notional) * fee_rate, 4)

        gross_pnl = (sell_price - buy_price) * qty
        net_pnl = round(gross_pnl - total_fee, 4)
        pnl_pct = round(((sell_price - buy_price) / buy_price) * 100.0, 2)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trade_history
                (symbol, quantity, buy_price, sell_price, fee_usdt, pnl_usdt, pnl_net_usdt, pnl_pct, exit_reason, entry_time, exit_time, is_paper)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol.upper(), qty, buy_price, sell_price, total_fee, gross_pnl, net_pnl, pnl_pct,
                exit_reason, pos["entry_time"], datetime.utcnow().isoformat(), pos["is_paper"]
            ))

            cursor.execute("DELETE FROM active_positions WHERE symbol = ?", (symbol.upper(),))
            conn.commit()

        return {
            "symbol": symbol,
            "quantity": qty,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "fee_usdt": total_fee,
            "pnl_usdt": round(gross_pnl, 2),
            "pnl_net_usdt": net_pnl,
            "pnl_pct": pnl_pct,
            "exit_reason": exit_reason
        }

    def record_portfolio_snapshot(self, total_equity: float, cash_balance: float, invested_value: float) -> None:
        """Record an equity point for live chart rendering."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO portfolio_snapshots (total_equity, cash_balance, invested_value, timestamp)
                VALUES (?, ?, ?, ?)
            """, (round(total_equity, 2), round(cash_balance, 2), round(invested_value, 2), datetime.utcnow().isoformat()))
            conn.commit()

    def get_portfolio_snapshots(self, limit: int = 150) -> List[Dict[str, Any]]:
        """Retrieve historical equity snapshots."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT total_equity, cash_balance, invested_value, timestamp
                FROM portfolio_snapshots ORDER BY id DESC LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in reversed(rows)]

    def save_ai_prediction(
        self,
        symbol: str,
        predicted_direction: str,
        target_price: float,
        invalidation_price: float,
        action: str,
        confidence: float,
        current_price: float,
        next_recheck_minutes: int,
        thesis: str,
        model_used: str
    ) -> None:
        """Store comprehensive AI forecast."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO ai_predictions
                (symbol, predicted_direction, target_price, invalidation_price, action, confidence,
                 current_price, next_recheck_minutes, thesis, model_used, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol.upper(), predicted_direction, target_price, invalidation_price, action,
                confidence, current_price, next_recheck_minutes, thesis, model_used, datetime.utcnow().isoformat()
            ))
            conn.commit()

    def get_latest_ai_prediction(self) -> Optional[Dict[str, Any]]:
        """Fetch the most recent AI market prediction."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ai_predictions ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_recent_ai_predictions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch recent AI predictions."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ai_predictions ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def get_trade_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch past closed trades."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM trade_history ORDER BY id DESC LIMIT ?",
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_performance_summary(self) -> Dict[str, Any]:
        """Calculate complete statistical metrics for dashboard."""
        trades = self.get_trade_history(limit=500)
        total_trades = len(trades)
        wins = [t for t in trades if t.get("pnl_net_usdt", t.get("pnl_usdt", 0)) > 0]
        losses = [t for t in trades if t.get("pnl_net_usdt", t.get("pnl_usdt", 0)) <= 0]

        win_count = len(wins)
        loss_count = len(losses)
        win_rate = round((win_count / total_trades) * 100.0, 1) if total_trades > 0 else 0.0

        total_gross_pnl = sum(t.get("pnl_usdt", 0) for t in trades)
        total_fees = sum(t.get("fee_usdt", 0) for t in trades)
        total_net_pnl = sum(t.get("pnl_net_usdt", t.get("pnl_usdt", 0)) for t in trades)

        return {
            "total_trades": total_trades,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": win_rate,
            "total_gross_pnl": round(total_gross_pnl, 2),
            "total_fees_paid": round(total_fees, 2),
            "total_net_pnl": round(total_net_pnl, 2)
        }

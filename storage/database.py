"""
Enhanced SQLite Persistence Engine.
Tracks paper & live portfolios, active positions, detailed trade history with fees,
equity snapshots for live graphing, and AI prediction logs.
"""

import sqlite3
import os
import threading
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from config.settings import settings

# Binance spot taker/maker fee (0.1%)
DEFAULT_FEE_RATE = 0.001

def _utcnow() -> str:
    """Timezone-aware UTC ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()

def _parse_ts(value: str) -> Optional[datetime]:
    """Parse an ISO timestamp, normalizing naive values to UTC."""
    try:
        dt = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def minutes_since(ts: Optional[str]) -> Optional[float]:
    """Minutes elapsed since an ISO timestamp; None if unparseable (fail-open)."""
    if not ts:
        return None
    dt = _parse_ts(ts)
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0

class Database:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.DB_PATH
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        # Serializes balance/position mutations across CLI loop & web sentinel threads
        self._write_lock = threading.RLock()
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
                is_paper INTEGER NOT NULL,
                protection_order_id TEXT
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

            # 6. AI Decision Logs (per-scan action log used by BotEngine / AICommander)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ai_decision_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    current_price REAL NOT NULL,
                    rationale TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pending_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    target_entry REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    confidence REAL NOT NULL,
                    rationale TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    amend_count INTEGER NOT NULL DEFAULT 0,
                    amend_log TEXT NOT NULL DEFAULT ''
                )
            """)

            # --- Schema migrations for databases created by older versions ---
            pend_cols = {c[1] for c in cursor.execute("PRAGMA table_info(pending_entries)")}
            if "amend_count" not in pend_cols:
                cursor.execute("ALTER TABLE pending_entries ADD COLUMN amend_count INTEGER NOT NULL DEFAULT 0")
            if "amend_log" not in pend_cols:
                cursor.execute("ALTER TABLE pending_entries ADD COLUMN amend_log TEXT NOT NULL DEFAULT ''")

            # --- Schema migrations for databases created by older versions ---
            pos_cols = {c[1] for c in cursor.execute("PRAGMA table_info(active_positions)")}
            if "protection_order_id" not in pos_cols:
                cursor.execute("ALTER TABLE active_positions ADD COLUMN protection_order_id TEXT")

            trade_cols = {c[1] for c in cursor.execute("PRAGMA table_info(trade_history)")}
            if "fee_usdt" not in trade_cols:
                cursor.execute("ALTER TABLE trade_history ADD COLUMN fee_usdt REAL NOT NULL DEFAULT 0.0")
            if "pnl_net_usdt" not in trade_cols:
                cursor.execute("ALTER TABLE trade_history ADD COLUMN pnl_net_usdt REAL NOT NULL DEFAULT 0.0")
                # Backfill: net = gross - estimated 0.1% round-trip fee for legacy rows
                cursor.execute("""
                    UPDATE trade_history
                    SET fee_usdt = ROUND((buy_price * quantity + sell_price * quantity) * ?, 4),
                        pnl_net_usdt = ROUND(pnl_usdt - ((buy_price * quantity + sell_price * quantity) * ?), 4)
                """, (DEFAULT_FEE_RATE, DEFAULT_FEE_RATE))

            # Initialize paper balance if empty
            cursor.execute("SELECT COUNT(*) FROM paper_account")
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    "INSERT INTO paper_account (id, usdt_balance, updated_at) VALUES (1, ?, ?)",
                    (settings.INITIAL_PAPER_BALANCE_USDT, _utcnow())
                )

            # Initialize initial portfolio snapshot if empty
            cursor.execute("SELECT COUNT(*) FROM portfolio_snapshots")
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    "INSERT INTO portfolio_snapshots (total_equity, cash_balance, invested_value, timestamp) VALUES (?, ?, 0.0, ?)",
                    (settings.INITIAL_PAPER_BALANCE_USDT, settings.INITIAL_PAPER_BALANCE_USDT, _utcnow())
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
        with self._write_lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE paper_account SET usdt_balance = ?, updated_at = ? WHERE id = 1",
                (new_balance, _utcnow())
            )
            conn.commit()

    def reset_demo_account(self, initial_balance: float = 1000.0) -> None:
        """Reset paper trading balance and clear active positions."""
        with self._write_lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE paper_account SET usdt_balance = ?, updated_at = ? WHERE id = 1",
                (initial_balance, _utcnow())
            )
            cursor.execute("DELETE FROM active_positions WHERE is_paper = 1")
            cursor.execute(
                "INSERT INTO portfolio_snapshots (total_equity, cash_balance, invested_value, timestamp) VALUES (?, ?, 0.0, ?)",
                (initial_balance, initial_balance, _utcnow())
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Atomic paper-trading operations (balance + position in ONE transaction)
    # ------------------------------------------------------------------
    def paper_open_position(
        self,
        symbol: str,
        quantity: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        fee_rate: float = DEFAULT_FEE_RATE
    ) -> Dict[str, Any]:
        """
        Atomically debit the paper balance (including the buy-side taker fee)
        and record the new active position in a single transaction.
        """
        symbol = symbol.upper()
        notional = quantity * entry_price
        buy_fee = round(notional * fee_rate, 4)
        total_cost = notional + buy_fee
        with self._write_lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT usdt_balance FROM paper_account WHERE id = 1")
            row = cursor.fetchone()
            balance = float(row["usdt_balance"]) if row else settings.INITIAL_PAPER_BALANCE_USDT
            if total_cost > balance + 1e-9:
                raise ValueError(
                    f"Insufficient paper balance: need {total_cost:.2f} USDT "
                    f"(incl. {buy_fee:.2f} fee), have {balance:.2f} USDT."
                )
            cursor.execute(
                "UPDATE paper_account SET usdt_balance = ?, updated_at = ? WHERE id = 1",
                (round(balance - total_cost, 4), _utcnow())
            )
            cursor.execute("""
                INSERT OR REPLACE INTO active_positions
                (symbol, quantity, entry_price, stop_loss, take_profit, highest_price, entry_time, is_paper)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """, (symbol, quantity, entry_price, stop_loss, take_profit, entry_price, _utcnow()))
            conn.commit()
        return {
            "symbol": symbol,
            "quantity": quantity,
            "entry_price": entry_price,
            "notional_usdt": round(notional, 2),
            "buy_fee_usdt": buy_fee,
            "total_cost_usdt": round(total_cost, 2)
        }

    def paper_close_position(
        self,
        symbol: str,
        sell_price: float,
        exit_reason: str,
        fee_rate: float = DEFAULT_FEE_RATE
    ) -> Optional[Dict[str, Any]]:
        """
        Atomically close an active paper position, credit net proceeds
        (sell notional minus sell-side fee; the buy-side fee was already
        deducted at entry) and record the trade history in ONE transaction.
        """
        symbol = symbol.upper()
        with self._write_lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM active_positions WHERE symbol = ?", (symbol,))
            row = cursor.fetchone()
            if not row:
                return None
            pos = dict(row)

            qty = pos["quantity"]
            buy_price = pos["entry_price"]
            buy_notional = buy_price * qty
            sell_notional = sell_price * qty
            buy_fee = buy_notional * fee_rate
            sell_fee = sell_notional * fee_rate
            total_fee = round(buy_fee + sell_fee, 4)

            gross_pnl = (sell_price - buy_price) * qty
            net_pnl = round(gross_pnl - total_fee, 4)
            pnl_pct = round(((sell_price - buy_price) / buy_price) * 100.0, 2)

            exit_time = _utcnow()
            cursor.execute("""
                INSERT INTO trade_history
                (symbol, quantity, buy_price, sell_price, fee_usdt, pnl_usdt, pnl_net_usdt, pnl_pct, exit_reason, entry_time, exit_time, is_paper)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol, qty, buy_price, sell_price, total_fee, round(gross_pnl, 4), net_pnl, pnl_pct,
                exit_reason, pos["entry_time"], exit_time, pos["is_paper"]
            ))
            cursor.execute("DELETE FROM active_positions WHERE symbol = ?", (symbol,))

            cursor.execute("SELECT usdt_balance FROM paper_account WHERE id = 1")
            bal_row = cursor.fetchone()
            balance = float(bal_row["usdt_balance"]) if bal_row else settings.INITIAL_PAPER_BALANCE_USDT
            new_balance = round(balance + sell_notional - sell_fee, 4)
            cursor.execute(
                "UPDATE paper_account SET usdt_balance = ?, updated_at = ? WHERE id = 1",
                (new_balance, exit_time)
            )
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
            "proceeds_usdt": round(sell_notional - sell_fee, 2),
            "new_balance_usdt": new_balance,
            "exit_reason": exit_reason
        }

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
        """Save a new opened spot position (no balance mutation — live mode / legacy)."""
        with self._write_lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO active_positions
                (symbol, quantity, entry_price, stop_loss, take_profit, highest_price, entry_time, is_paper)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol.upper(), quantity, entry_price, stop_loss, take_profit,
                entry_price, _utcnow(), 1 if is_paper else 0
            ))
            conn.commit()

    def set_protection_order_id(self, symbol: str, order_list_id: Optional[str]) -> None:
        """Record the exchange-side OCO order list protecting this position (live mode)."""
        with self._write_lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE active_positions SET protection_order_id = ? WHERE symbol = ?",
                (str(order_list_id) if order_list_id is not None else None, symbol.upper())
            )
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
        fee_rate: float = DEFAULT_FEE_RATE
    ) -> Optional[Dict[str, Any]]:
        """Close an active position, calculate fees, and record trade history (no balance mutation — used in live mode)."""
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

        with self._write_lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trade_history
                (symbol, quantity, buy_price, sell_price, fee_usdt, pnl_usdt, pnl_net_usdt, pnl_pct, exit_reason, entry_time, exit_time, is_paper)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol.upper(), qty, buy_price, sell_price, total_fee, round(gross_pnl, 4), net_pnl, pnl_pct,
                exit_reason, pos["entry_time"], _utcnow(), pos["is_paper"]
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
            """, (round(total_equity, 2), round(cash_balance, 2), round(invested_value, 2), _utcnow()))
            conn.commit()

    def get_portfolio_snapshots(
        self,
        limit: int = 150,
        hours: Optional[float] = None,
        max_points: int = 500
    ) -> List[Dict[str, Any]]:
        """
        Retrieve historical equity snapshots.
        If `hours` is given, only snapshots from the last N hours are returned.
        Results older/newer than needed are downsampled to at most `max_points`
        evenly spaced points (always keeping the first and last point).
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if hours is not None:
                cursor.execute("""
                    SELECT total_equity, cash_balance, invested_value, timestamp
                    FROM portfolio_snapshots
                    WHERE timestamp >= ?
                    ORDER BY id ASC
                """, ((datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(),))
            else:
                cursor.execute("""
                    SELECT total_equity, cash_balance, invested_value, timestamp
                    FROM portfolio_snapshots ORDER BY id DESC LIMIT ?
                """, (limit,))
            rows = [dict(r) for r in cursor.fetchall()]
            if hours is None:
                rows.reverse()

        if len(rows) > max_points:
            step = len(rows) / (max_points - 1)
            sampled = [rows[int(i * step)] for i in range(max_points - 1)]
            sampled.append(rows[-1])
            return sampled
        return rows

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
                confidence, current_price, next_recheck_minutes, thesis, model_used, _utcnow()
            ))
            conn.commit()

    # ------------------------------------------------------------------
    # AI Decision Logs (used by BotEngine, AICommander and CLI report)
    # ------------------------------------------------------------------
    def log_ai_decision(
        self,
        symbol: str,
        action: str,
        confidence: float,
        current_price: float,
        rationale: str,
        provider: str
    ) -> None:
        """Store a single AI/quant decision entry for audit & reporting."""
        with self._write_lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO ai_decision_logs
                (symbol, action, confidence, current_price, rationale, provider, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol.upper(), action, float(confidence), float(current_price),
                str(rationale), str(provider), _utcnow()
            ))
            conn.commit()

    def get_recent_ai_logs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch most recent AI decision log entries."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM ai_decision_logs ORDER BY id DESC LIMIT ?", (limit,)
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_latest_ai_prediction(self) -> Optional[Dict[str, Any]]:
        """Fetch the most recent AI market prediction."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ai_predictions ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    # ---------------- Pending (limit-zone) entries ----------------

    def save_pending_entry(
        self,
        symbol: str,
        target_entry: float,
        stop_loss: float,
        take_profit: float,
        confidence: float,
        rationale: str,
        expires_at: str,
    ) -> int:
        """Queue an AI-approved entry that waits for price to reach the target zone."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO pending_entries
                (symbol, target_entry, stop_loss, take_profit, confidence, rationale, status, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
            """, (symbol, target_entry, stop_loss, take_profit, confidence, rationale,
                  datetime.now(timezone.utc).isoformat(), expires_at))
            return cursor.lastrowid

    def get_pending_entries(self, status: str = "PENDING") -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM pending_entries WHERE status = ? ORDER BY id ASC", (status,)
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_pending_entry_for_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM pending_entries WHERE symbol = ? AND status = 'PENDING' "
                "ORDER BY id DESC LIMIT 1", (symbol,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_pending_entry_status(self, entry_id: int, status: str) -> None:
        """status: FILLED | CANCELLED | EXPIRED"""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE pending_entries SET status = ? WHERE id = ?", (status, entry_id)
            )

    def amend_pending_entry(
        self,
        entry_id: int,
        target_entry: float,
        stop_loss: float,
        take_profit: float,
        confidence: float,
        rationale: str,
        expires_at: str,
        note: str,
    ) -> None:
        """
        Update a waiting pending order's zone/levels after fresh AI analysis.
        Appends an audit line (timestamp, old→new zone, reason) to amend_log
        and increments amend_count.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute(
                "SELECT target_entry, amend_count, amend_log FROM pending_entries WHERE id = ?",
                (entry_id,)
            ).fetchone()
            if not row:
                return
            ts = datetime.now(timezone.utc).isoformat()
            line = (
                f"[{ts}] zone {row['target_entry']:.6f} -> {target_entry:.6f} | {note}\n"
            )
            cursor.execute("""
                UPDATE pending_entries
                SET target_entry = ?, stop_loss = ?, take_profit = ?,
                    confidence = ?, rationale = ?, expires_at = ?,
                    amend_count = amend_count + 1,
                    amend_log = ? || ?
                WHERE id = ?
            """, (target_entry, stop_loss, take_profit, confidence, rationale,
                  expires_at, row["amend_log"], line, entry_id))

    def get_latest_predictions_per_symbol(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Fetch the most recent prediction for each given symbol."""
        results = []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for sym in symbols:
                cursor.execute(
                    "SELECT * FROM ai_predictions WHERE symbol = ? ORDER BY id DESC LIMIT 1",
                    (sym,),
                )
                row = cursor.fetchone()
                if row:
                    results.append(dict(row))
        return results

    def get_recent_ai_predictions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch recent AI predictions."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ai_predictions ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def get_mean_reversion_context(self) -> Dict[str, Any]:
        """(placeholder for future analytics)"""
        return {}

    def get_equity_series(self, limit: int = 1000) -> List[float]:
        """
        Return the ordered (oldest -> newest) total_equity series for drawdown
        and circuit-breaker calculations.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT total_equity FROM portfolio_snapshots ORDER BY id DESC LIMIT ?",
                (limit,)
            )
            rows = [float(r["total_equity"]) for r in cursor.fetchall()]
            rows.reverse()
            return rows

    # ---------------- Kill switch state persistence ----------------

    def get_last_close_time(self, symbol: str) -> Optional[datetime]:
        """Return the most recent exit time for a symbol (any trade), or None."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT exit_time FROM trade_history WHERE symbol = ? ORDER BY id DESC LIMIT 1",
                (symbol.upper(),)
            )
            row = cursor.fetchone()
            if not row or not row["exit_time"]:
                return None
            dt = _parse_ts(row["exit_time"])
            return dt

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

"""
Binance Spot API Client.
Strictly restricted to Spot Market endpoints (/api/v3/*).
Protected by ShariahComplianceGuard to eliminate Riba, Margin, and Derivatives.
"""

import time
import hmac
import hashlib
from typing import Dict, Any, List, Optional
from urllib.parse import urlencode
import requests
import pandas as pd

from config.settings import settings
from config.halal_whitelist import is_pair_halal, get_base_and_quote
from core.shariah_guard import ShariahComplianceGuard, ShariahViolationError

class BinanceSpotClient:
    """Production-ready Binance Spot Client with Shariah Guard."""

    LIVE_BASE_URL = "https://api.binance.com"
    TESTNET_BASE_URL = "https://testnet.binance.vision"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        use_testnet: Optional[bool] = None
    ):
        self.api_key = (api_key or settings.BINANCE_API_KEY or "").strip()
        self.api_secret = (api_secret or settings.BINANCE_API_SECRET or "").strip()
        # Explicit True/False always wins over the .env flag; None defers to settings.
        # (Previously `use_testnet or settings...` made it impossible to force LIVE
        # market data while BINANCE_USE_TESTNET=true, which broke chart accuracy.)
        self.use_testnet = settings.BINANCE_USE_TESTNET if use_testnet is None else use_testnet
        self.base_url = self.TESTNET_BASE_URL if self.use_testnet else self.LIVE_BASE_URL
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "HalalCryptoAIAgent/1.0",
            "Accept": "application/json"
        })
        if self.api_key:
            self.session.headers.update({"X-MBX-APIKEY": self.api_key})

    def _sign_params(self, params: Dict[str, Any]) -> str:
        """Create HMAC-SHA256 signature for authenticated requests."""
        if not self.api_secret:
            raise ValueError("Binance API Secret is required for authenticated requests.")
        query_string = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return f"{query_string}&signature={signature}"

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False
    ) -> Any:
        """Execute HTTP request with strict Shariah guard verification."""
        # Enforce endpoint sanitation
        ShariahComplianceGuard.sanitize_api_endpoint(endpoint)

        url = f"{self.base_url}{endpoint}"
        req_params = params.copy() if params else {}

        if signed:
            if not self.api_key or not self.api_secret:
                raise ValueError("Binance API Key and Secret are required for signed operations.")
            req_params["timestamp"] = int(time.time() * 1000)
            req_params["recvWindow"] = 5000
            query_string = self._sign_params(req_params)
            url = f"{url}?{query_string}"
            req_params = None

        max_retries = 3
        last_exception = None

        for attempt in range(max_retries):
            try:
                response = self.session.request(method=method, url=url, params=req_params, timeout=10)
                if response.status_code >= 400:
                    try:
                        err_data = response.json()
                        msg = err_data.get("msg", response.text)
                        code = err_data.get("code", response.status_code)
                        raise RuntimeError(f"Binance API Error [{code}]: {msg}")
                    except ValueError:
                        response.raise_for_status()
                return response.json()
            except (requests.exceptions.RequestException, requests.exceptions.ConnectionError) as e:
                last_exception = e
                if attempt < max_retries - 1:
                    time.sleep(1.0 * (attempt + 1))
                else:
                    raise last_exception

        raise last_exception if last_exception else RuntimeError("Request failed after retries.")

    def ping(self) -> bool:
        """Test connectivity to Binance Spot API."""
        try:
            res = self._request("GET", "/api/v3/ping")
            return res == {}
        except Exception:
            return False

    def get_server_time(self) -> int:
        """Fetch official Binance server timestamp."""
        res = self._request("GET", "/api/v3/time")
        return res.get("serverTime", int(time.time() * 1000))

    def get_ticker_price(self, symbol: str) -> float:
        """Get latest spot market price for a symbol."""
        ShariahComplianceGuard.audit_symbol(symbol)
        res = self._request("GET", "/api/v3/ticker/price", params={"symbol": symbol.upper()})
        return float(res["price"])

    def get_klines(
        self,
        symbol: str,
        interval: str = "15m",
        limit: int = 100
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candlestick data for a Halal symbol.
        Returns a clean pandas DataFrame with typed columns.
        """
        ShariahComplianceGuard.audit_symbol(symbol)
        raw_candles = self._request(
            "GET",
            "/api/v3/klines",
            params={
                "symbol": symbol.upper(),
                "interval": interval,
                "limit": limit
            }
        )

        columns = [
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
        ]
        df = pd.DataFrame(raw_candles, columns=columns)

        # Convert datatypes
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
        numeric_cols = ["open", "high", "low", "close", "volume", "quote_asset_volume"]
        for col in numeric_cols:
            df[col] = df[col].astype(float)

        df.set_index("open_time", inplace=True)
        return df

    @staticmethod
    def extract_fill_price(order_response: Dict[str, Any], fallback_price: float) -> float:
        """
        Extract the real average execution price from a Binance order response.
        MARKET orders include a `fills` array; falls back to `price`, then `fallback_price`.
        """
        try:
            fills = order_response.get("fills") or []
            if fills:
                total_qty = sum(float(f["qty"]) for f in fills)
                if total_qty > 0:
                    return sum(float(f["price"]) * float(f["qty"]) for f in fills) / total_qty
            price = float(order_response.get("price") or 0.0)
            if price > 0:
                return price
        except (TypeError, ValueError, KeyError):
            pass
        return fallback_price

    def get_exchange_filters(self, symbol: str) -> Dict[str, float]:
        """
        Fetch Binance trading rules for a symbol:
        step_size (LOT_SIZE), min_qty, min_notional, tick_size.
        """
        res = self._request("GET", "/api/v3/exchangeInfo", params={"symbol": symbol.upper()})
        info = (res.get("symbols") or [{}])[0]
        filters = {f["filterType"]: f for f in info.get("filters", [])}
        lot = filters.get("LOT_SIZE", {})
        notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL", {})
        price_f = filters.get("PRICE_FILTER", {})
        return {
            "step_size": float(lot.get("stepSize", 0.000001)),
            "min_qty": float(lot.get("minQty", 0.0)),
            "min_notional": float(notional.get("minNotional", 10.0)),
            "tick_size": float(price_f.get("tickSize", 0.0001)),
        }

    def round_to_step(self, quantity: float, step_size: float) -> float:
        """Round a quantity DOWN to the exchange step size (never oversell owned balance)."""
        import math
        if step_size <= 0:
            return quantity
        precision = max(0, round(-math.log10(step_size)))
        return math.floor(quantity / step_size) * round(step_size, precision) if precision > 0 else math.floor(quantity / step_size) * step_size

    @staticmethod
    def round_to_tick(price: float, tick_size: float, direction: str = "nearest") -> float:
        """
        Round a price to the exchange tick size (PRICE_FILTER compliance).
        direction: 'up' (ceiling), 'down' (floor), or 'nearest'.
        """
        import math
        if tick_size <= 0:
            return price
        precision = max(0, round(-math.log10(tick_size)))
        ratio = price / tick_size
        if direction == "up":
            rounded = math.ceil(ratio) * tick_size
        elif direction == "down":
            rounded = math.floor(ratio) * tick_size
        else:
            rounded = round(ratio) * tick_size
        return round(rounded, precision)

    def get_spot_account_balance(self, asset: str = "USDT") -> float:
        """Fetch available Spot balance for an asset."""
        account_info = self._request("GET", "/api/v3/account", signed=True)
        balances = account_info.get("balances", [])
        for b in balances:
            if b.get("asset") == asset.upper():
                return float(b.get("free", 0.0))
        return 0.0

    def place_spot_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: Optional[float] = None,
        order_type: str = "MARKET"
    ) -> Dict[str, Any]:
        """
        Execute an unleveraged Spot trade on Binance.
        Enforces Shariah audits prior to transmission.
        """
        ShariahComplianceGuard.audit_symbol(symbol)
        ShariahComplianceGuard.audit_order_type(side=side, order_type=order_type, leverage=1.0)

        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": f"{quantity:.6f}".rstrip("0").rstrip("."),
        }

        if order_type.upper() == "LIMIT":
            if price is None:
                raise ValueError("Price is required for LIMIT spot orders.")
            params["price"] = f"{price:.4f}"
            params["timeInForce"] = "GTC"

        return self._request("POST", "/api/v3/order", params=params, signed=True)

    # ------------------------------------------------------------------
    # Exchange-side protection (Spot OCO: take-profit + stop-loss)
    # ------------------------------------------------------------------
    def place_spot_oco_sell(
        self,
        symbol: str,
        quantity: float,
        take_profit_price: float,
        stop_price: float,
        stop_limit_price: float
    ) -> Dict[str, Any]:
        """
        Place an OCO order list that protects an existing LONG spot position:
          - above: LIMIT_MAKER take-profit sell at take_profit_price
          - below: STOP_LOSS_LIMIT sell triggering at stop_price, executing at stop_limit_price
        Whichever leg fills first cancels the other, so the position carries
        exchange-side protection even while this bot process is offline.

        Uses the current Spot endpoint POST /api/v3/orderList/oco.
        NOTE: verify on testnet (BINANCE_USE_TESTNET=true) before enabling in production.
        """
        ShariahComplianceGuard.audit_symbol(symbol)
        ShariahComplianceGuard.audit_order_type(side="SELL", order_type="OCO", leverage=1.0)

        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": "SELL",
            "quantity": f"{quantity:.6f}".rstrip("0").rstrip("."),
            "aboveType": "LIMIT_MAKER",
            "abovePrice": f"{take_profit_price:.4f}",
            "belowType": "STOP_LOSS_LIMIT",
            "belowStopPrice": f"{stop_price:.4f}",
            "belowPrice": f"{stop_limit_price:.4f}",
            "belowTimeInForce": "GTC",
        }
        return self._request("POST", "/api/v3/orderList/oco", params=params, signed=True)

    def cancel_order_list(self, symbol: str, order_list_id) -> Dict[str, Any]:
        """Cancel an OCO order list (e.g. before a manual/panic sell frees the locked balance)."""
        params = {"symbol": symbol.upper(), "orderListId": str(order_list_id)}
        return self._request("DELETE", "/api/v3/orderList", params=params, signed=True)

    def get_open_order_lists(self, symbol: Optional[str] = None) -> Any:
        """Fetch open OCO order lists (for reconciliation after restarts)."""
        params = {"symbol": symbol.upper()} if symbol else None
        return self._request("GET", "/api/v3/openOrderList", params=params, signed=True)

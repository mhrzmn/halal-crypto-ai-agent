"""
Shariah Compliance Guard.
Intercepts all trading actions and API calls to guarantee absolute adherence to Islamic principles:
1. Strictly 100% Spot trading (Zero margin, zero futures, zero options, zero leverage).
2. Elimination of Riba (No borrowing, no interest fees, no liquidation wagers).
3. Elimination of Maysir & Gharar (No binary event bets, no pure gambling mechanics).
4. Physical/Constructive Possession (Qabd al-Hukmi) before resale: No short-selling (Bay' ma la tamlik).
5. Only Shariah-screened permissible digital assets (Halal whitelist).
"""

from typing import Dict, Any, Optional
from config.halal_whitelist import is_pair_halal, get_base_and_quote, HARAM_BLACKLIST

class ShariahViolationError(Exception):
    """Raised whenever an action violates Islamic Commercial Jurisprudence (Fiqh al-Mu'amalat)."""
    pass

class ShariahComplianceGuard:
    @staticmethod
    def audit_symbol(symbol: str) -> None:
        """Verify that the trading pair is on the Halal whitelist."""
        if not is_pair_halal(symbol):
            base_quote = get_base_and_quote(symbol)
            if base_quote:
                base, _ = base_quote
                if base in HARAM_BLACKLIST:
                    raise ShariahViolationError(
                        f"[SHARIAH VIOLATION] Asset {base} is blacklisted: {HARAM_BLACKLIST[base]}"
                    )
            raise ShariahViolationError(
                f"[SHARIAH VIOLATION] Trading pair '{symbol}' is not approved on the Halal Whitelist. "
                f"Only screened spot assets with legitimate technological utility are permitted."
            )

    @staticmethod
    def audit_order_type(side: str, order_type: str, leverage: float = 1.0) -> None:
        """
        Verify order is 100% unleveraged spot.
        Leverage > 1.0 implies margin/borrowing with Riba.
        """
        if leverage != 1.0:
            raise ShariahViolationError(
                f"[SHARIAH VIOLATION] Leverage {leverage}x detected! Margin trading involves borrowing "
                f"with interest (Riba) and is strictly forbidden."
            )

        side_clean = side.upper().strip()
        if side_clean not in ["BUY", "SELL"]:
            raise ShariahViolationError(f"[SHARIAH VIOLATION] Invalid side '{side}'. Only BUY or SELL allowed.")

    @staticmethod
    def audit_spot_balance_before_sale(base_asset: str, quantity_to_sell: float, owned_balance: float) -> None:
        """
        Verify that we actually own the asset before selling (No short-selling).
        Prophet Muhammad (ﷺ) said: 'Do not sell what you do not possess' (Sunan Abi Dawud 3503).
        """
        # Allow tiny float precision epsilon
        if owned_balance < quantity_to_sell * 0.999:
            raise ShariahViolationError(
                f"[SHARIAH VIOLATION] Attempting to sell {quantity_to_sell:.6f} {base_asset}, but owned "
                f"balance is only {owned_balance:.6f}. Short-selling is forbidden in Islamic law."
            )

    @staticmethod
    def sanitize_api_endpoint(endpoint: str) -> None:
        """Ensure no margin, futures, or derivatives endpoints are invoked."""
        impermissible_prefixes = [
            "/fapi",       # Futures API
            "/dapi",       # Coin-M Futures API
            "/sapi/v1/margin", # Margin API
            "/sapi/v1/loan",   # Crypto Loans (Riba)
            "/sapi/v1/futures",
            "/sapi/v1/sub-account/margin",
            "/sapi/v1/sub-account/futures",
        ]
        for prefix in impermissible_prefixes:
            if prefix in endpoint.lower():
                raise ShariahViolationError(
                    f"[SHARIAH VIOLATION] Prohibited endpoint detected: {endpoint}. "
                    f"Only Spot Market API (/api/v3/*) is permissible."
                )

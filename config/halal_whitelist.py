"""
Halal Crypto Screener and Whitelist Specification
Based on contemporary Islamic Commercial Jurisprudence (Fiqh al-Mu'amalat)
and crypto screening criteria from recognized Shariah boards (Crypto-Halal, IFG, Amanah Advisors).

Key Shariah Standards for Crypto Assets:
1. Real Technological Utility (Maliyyah / Manfa'ah): Must have an underlying protocol, smart contract utility,
   or distributed consensus purpose, not a zero-utility speculative token.
2. Prohibition of Riba (Interest): Must not be a native governance/revenue-sharing token for an interest-based
   lending/borrowing protocol (e.g. AAVE, Compound, Maker).
3. Prohibition of Maysir (Gambling): Must not power or be derived from gambling/casino/lottery protocols.
4. Spot Only (Bay' al-Sarf / Bay' al-Sila'): Actual asset transfer into custody with immediate settlement.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class ShariahScreeningInfo:
    symbol: str
    name: str
    status: str  # 'HALAL', 'HARAM', 'DOUBTFUL'
    primary_utility: str
    shariah_notes: str

# Whitelist of permissible Spot cryptocurrencies
HALAL_WHITELIST: Dict[str, ShariahScreeningInfo] = {
    "BTC": ShariahScreeningInfo(
        symbol="BTC",
        name="Bitcoin",
        status="HALAL",
        primary_utility="Decentralized Digital Currency & Store of Value",
        shariah_notes="Widely recognized as permissible digital property (Mal) by majority of contemporary scholars. Spot purchase only."
    ),
    "ETH": ShariahScreeningInfo(
        symbol="ETH",
        name="Ethereum",
        status="HALAL",
        primary_utility="Decentralized Virtual Machine / Gas for Smart Contracts",
        shariah_notes="Valid digital asset with clear computational utility (gas). Spot trading without staking yields that involve lending."
    ),
    "SOL": ShariahScreeningInfo(
        symbol="SOL",
        name="Solana",
        status="HALAL",
        primary_utility="High-Performance Layer-1 Blockchain Network Utility",
        shariah_notes="Utility token used for transaction execution, validation, and network compute."
    ),
    "LINK": ShariahScreeningInfo(
        symbol="LINK",
        name="Chainlink",
        status="HALAL",
        primary_utility="Decentralized Oracle Service Infrastructure",
        shariah_notes="Provides decentralized data feeds to smart contracts. Real infrastructure service with valid utility."
    ),
    "AVAX": ShariahScreeningInfo(
        symbol="AVAX",
        name="Avalanche",
        status="HALAL",
        primary_utility="Layer-1 Subnet & Smart Contract Platform Utility",
        shariah_notes="Used for gas fees and subnet settlement. Permissible utility."
    ),
    "XAUT": ShariahScreeningInfo(
        symbol="XAUT",
        name="Tether Gold",
        status="HALAL",
        primary_utility="Gold-Backed Asset Token (1 token = 1 troy oz allocated physical gold)",
        shariah_notes="Fully backed by allocated physical gold in custody; spot purchase constitutes Bay' al-Sarf with immediate on-chain settlement into buyer custody. Treated as digital gold (Mal). No riba mechanism. Buyer should note counterparty/custody risk of the issuer."
    ),
    "POL": ShariahScreeningInfo(
        symbol="POL",
        name="Polygon (formerly MATIC)",
        status="HALAL",
        primary_utility="Ethereum Layer-2 Scaling & Gas Token",
        shariah_notes="Legitimate scaling solution infrastructure."
    ),
    "NEAR": ShariahScreeningInfo(
        symbol="NEAR",
        name="NEAR Protocol",
        status="HALAL",
        primary_utility="Layer-1 Sharded Smart Contract Cloud Platform",
        shariah_notes="Used to pay for storage and computation on the decentralized cloud."
    ),
    "DOT": ShariahScreeningInfo(
        symbol="DOT",
        name="Polkadot",
        status="HALAL",
        primary_utility="Interoperability Protocol & Parachain Governance",
        shariah_notes="Cross-chain bridging and shared security utility."
    ),
    "ADA": ShariahScreeningInfo(
        symbol="ADA",
        name="Cardano",
        status="HALAL",
        primary_utility="Layer-1 Proof-of-Stake Smart Contract Network",
        shariah_notes="Platform gas and consensus utility."
    ),
}

# Explicit blacklist of impermissible tokens to prevent accidental trading
HARAM_BLACKLIST: Dict[str, str] = {
    "AAVE": "Interest-based lending/borrowing protocol (Direct involvement in Riba).",
    "COMP": "Interest-based money market lending protocol (Riba).",
    "MKR": "Interest/stability fee generation via collateralized debt (Riba).",
    "CRV": "Liquidity pool provider heavily integrated with interest-bearing debt pools.",
    "DOGE": "Speculative meme token lacking clear underlying utility; excessive Gharar.",
    "SHIB": "Speculative meme token with excessive Gharar.",
    "PEPE": "Speculative meme token with no economic utility; pure Maysir-like speculation.",
    "FUN": "Casino and gaming gambling token (Maysir).",
    "WIN": "Gambling and casino platform token (Maysir).",
}

# Permissible quote currencies (Cash equivalents for Bay' al-Sarf spot exchange)
PERMISSIBLE_QUOTE_CURRENCIES = ["USDT", "FDUSD", "USDC"]

def is_asset_halal(base_asset: str) -> bool:
    """Check if the base asset symbol is verified Halal."""
    symbol_clean = base_asset.upper().strip()
    return symbol_clean in HALAL_WHITELIST and symbol_clean not in HARAM_BLACKLIST

def is_pair_halal(symbol_pair: str) -> bool:
    """
    Validate that a trading pair (e.g. BTCUSDT) consists of:
    1. A Halal whitelisted base asset
    2. A permissible cash-equivalent quote currency
    """
    pair = symbol_pair.upper().strip()
    for quote in PERMISSIBLE_QUOTE_CURRENCIES:
        if pair.endswith(quote):
            base = pair[:-len(quote)]
            return is_asset_halal(base)
    return False

def get_base_and_quote(symbol_pair: str) -> Optional[tuple[str, str]]:
    """Extract base and quote assets from symbol pair."""
    pair = symbol_pair.upper().strip()
    for quote in PERMISSIBLE_QUOTE_CURRENCIES:
        if pair.endswith(quote):
            base = pair[:-len(quote)]
            return base, quote
    return None

def get_screening_info(symbol: str) -> Optional[ShariahScreeningInfo]:
    """Retrieve Shariah screening report for a symbol."""
    return HALAL_WHITELIST.get(symbol.upper().strip())

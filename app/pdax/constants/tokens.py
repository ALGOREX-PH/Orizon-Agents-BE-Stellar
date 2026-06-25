"""
PDAX supported crypto tokens → network (case-sensitive, as of Aug 2024).

Use the Token Symbol exactly for crypto-in / crypto-out. Sending an asset over
the wrong network can make recovery impossible. For Orizon the relevant symbol
is USDCXLM (USDC on Stellar) — see STELLAR_TOKENS below.
"""
from __future__ import annotations

TOKEN_NETWORKS: dict[str, str] = {
    "AAVE": "Ethereum (ERC20)",
    "ADA": "Cardano",
    "ALGO": "Algorand",
    "APE": "Ethereum (ERC20)",
    "AVAX": "C-chain",
    "AXS": "Ronin",
    "BAT": "Ethereum (ERC20)",
    "BCH": "Bitcoin Cash (BCH)",
    "BNB": "BNB Smart Chain (BEP20)",
    "BTC": "BTC (SegWit)",
    "COMP": "Ethereum (ERC20)",
    "DOGE": "Dogecoin",
    "DOT": "Polkadot",
    "ENJ": "Ethereum (ERC20)",
    "ETH": "Ethereum (ERC20)",
    "GALA": "Ethereum (ERC20)",
    "GMT": "Solana",
    "GRT": "Ethereum (ERC20)",
    "HBAR": "Hedera",
    "LINK": "Ethereum (ERC20)",
    "LTC": "Litecoin",
    "MANA": "Ethereum (ERC20)",
    "POL": "Polygon",
    "PAXG": "Ethereum (ERC20)",
    "PEPE": "Ethereum (ERC20)",
    "PYUSD": "Ethereum (ERC20)",
    "RON": "Ronin",
    "SAND": "Ethereum (ERC20)",
    "SHIB": "Ethereum (ERC20)",
    "SLP": "Ronin",
    "SOL": "Solana",
    "SUSHI": "Ethereum (ERC20)",
    "TON": "TON",
    "UNI": "Ethereum (ERC20)",
    "USDCSOL": "Solana",
    "USDCXLM": "Stellar",
    "USDCPOL": "Polygon",
    "USDC": "Ethereum (ERC20)",
    "USDTPOL": "Polygon",
    "USDT": "Ethereum (ERC20)",
    "USDTTRX": "Tron (TRC20)",
    "WETHPOL": "Polygon",
    "XLM": "Stellar",
    "XRP": "Ripple",
    "XTZ": "Tezos",
    "YGGRON": "Ronin",
    "CELO": "Ethereum (ERC20)",
    "OP": "Ethereum (ERC20)",
    "NEAR": "Ethereum (ERC20)",
}

# Tokens native to Stellar — Orizon's settlement network.
STELLAR_TOKENS: frozenset[str] = frozenset({"USDCXLM", "XLM"})

SUPPORTED_TOKENS: frozenset[str] = frozenset(TOKEN_NETWORKS)


def network_for(token: str) -> str | None:
    return TOKEN_NETWORKS.get(token)


def is_supported_token(token: str) -> bool:
    return token in TOKEN_NETWORKS

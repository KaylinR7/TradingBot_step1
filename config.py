"""
Central config for the trading bot.
Reads MT5 login credentials from .env so we never hardcode secrets.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- MT5 account credentials (from your demo account email) ---
MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")

# --- Path to the MT5 terminal exe (only needed if it's not in the default location) ---
MT5_PATH = os.getenv("MT5_PATH", "")  # e.g. "C:\\Program Files\\IC Markets MT5 Terminal\\terminal64.exe"

# --- Instrument mapping: original plan -> MT5 symbol on IC Markets ---
# NOTE: exact symbol names can vary slightly by broker (e.g. "US500" vs "US500Cash").
# Confirmed working on Kaylin's IC Markets demo (as of step 1 test):
INSTRUMENTS = {
    "SPY_EQUIVALENT": "US500",     # S&P 500 index CFD -> mean reversion
    "BTC_EQUIVALENT": "BTCUSD",    # Bitcoin CFD -> momentum breakout
    "GLD_EQUIVALENT": "XAUUSD",    # Gold -> trend following
}

# Strategies currently enabled for live/paper trading. Mean reversion is
# disabled pending further research - backtesting (step 4) showed no edge
# over a persistently trending 3-4 week test window even after adding a
# hard stop loss, widening the entry threshold, and adding an ADX trend
# filter. Rather than keep tuning parameters against the same small
# dataset (which risks overfitting), it's parked until we can test it
# against a longer/different period or a different instrument.
ENABLED_STRATEGIES = {
    "mean_reversion": False,   # US500 - disabled, see note above
    "momentum_breakout": True,  # BTCUSD
    "trend_following": True,    # XAUUSD
}

# --- Risk settings (used later in risk_manager.py) ---
RISK_PER_TRADE_PCT = 1.0        # max 1% of equity risked per trade
MAX_PORTFOLIO_DRAWDOWN_PCT = 10.0  # circuit breaker
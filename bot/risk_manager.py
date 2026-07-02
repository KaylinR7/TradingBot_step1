"""
Risk management - the most important module in this bot.

Rules enforced here:
1. Position sizing is ATR-based: position size is calculated so that a
   1-ATR move against the trade equals exactly RISK_PER_TRADE_PCT of
   account equity. Quiet instruments get bigger positions, volatile
   instruments get smaller ones - dollar risk stays constant.
2. Every trade gets a hard stop loss at 1 ATR from entry. No exceptions,
   the stop is never moved further away or removed once set.
3. Correlation filter: prevents opening correlated positions on top of
   each other (e.g. don't add BTC long if index positions are already long).
4. Portfolio circuit breaker: if total equity drawdown from peak exceeds
   MAX_PORTFOLIO_DRAWDOWN_PCT, block all new trades until manually reviewed.
"""

import pandas as pd
import config


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Standard ATR (Average True Range) calculation.
    Requires df to have 'high', 'low', 'close' columns.
    """
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.rolling(period).mean()
    return atr


def calculate_position_size(account_equity: float, atr: float, price: float,
                             risk_pct: float = None) -> dict:
    """
    Calculate position size so that a 1-ATR adverse move costs exactly
    `risk_pct`% of account equity.

    Returns a dict with:
        risk_amount   - dollars risked on this trade
        stop_distance - price distance to the stop (1 ATR)
        position_size - number of units/lots to trade
        stop_price_offset - same as stop_distance, named for clarity when
                             computing actual stop price (entry +/- this)

    Note: for CFDs/forex, "position_size" here is in the same units the
    broker's order volume expects once we get to execution - we'll map
    this to lot sizes in main.py once we know the contract specs for
    each instrument.
    """
    if risk_pct is None:
        risk_pct = config.RISK_PER_TRADE_PCT

    if atr <= 0:
        raise ValueError("ATR must be positive - check there's enough candle history.")

    risk_amount = account_equity * (risk_pct / 100)
    stop_distance = atr  # 1 ATR stop, as specified

    # position size such that stop_distance * position_size == risk_amount
    position_size = risk_amount / stop_distance

    return {
        "risk_amount": round(risk_amount, 2),
        "stop_distance": round(stop_distance, 5),
        "position_size": round(position_size, 4),
        "stop_price_offset": round(stop_distance, 5),
    }


def get_stop_price(entry_price: float, stop_distance: float, direction: int) -> float:
    """
    direction: 1 for long, -1 for short.
    Long stop goes below entry, short stop goes above entry.
    """
    return entry_price - (stop_distance * direction)


class DrawdownGuard:
    """
    Tracks account equity peak and blocks new trades if drawdown from
    peak exceeds the configured max. This is the circuit breaker.
    """

    def __init__(self, max_drawdown_pct: float = None):
        self.max_drawdown_pct = max_drawdown_pct or config.MAX_PORTFOLIO_DRAWDOWN_PCT
        self.peak_equity = None
        self.tripped = False

    def update(self, current_equity: float) -> bool:
        """
        Call this with the latest account equity. Returns True if trading
        should be allowed to continue, False if the circuit breaker has
        tripped (drawdown exceeded).

        Once tripped, stays tripped until manually reset (reset_after_review()).
        """
        if self.peak_equity is None or current_equity > self.peak_equity:
            self.peak_equity = current_equity

        if self.tripped:
            return False

        drawdown_pct = (self.peak_equity - current_equity) / self.peak_equity * 100

        if drawdown_pct >= self.max_drawdown_pct:
            self.tripped = True
            print(f"[CIRCUIT BREAKER] Drawdown {drawdown_pct:.1f}% exceeds "
                  f"max {self.max_drawdown_pct}%. All new trades blocked. "
                  f"Peak equity: {self.peak_equity:.2f}, current: {current_equity:.2f}")
            return False

        return True

    def reset_after_review(self):
        """Call this manually after reviewing what caused the drawdown."""
        self.tripped = False
        print("[CIRCUIT BREAKER] Manually reset. Trading re-enabled.")


class CorrelationFilter:
    """
    Prevents opening correlated positions on top of each other.
    Specifically: if the index instruments (US500 / NAS100) are already
    long, block new long entries on BTCUSD (both are "risk-on" assets
    that tend to move together), and vice versa for shorts.
    """

    # Groups of instruments considered correlated with each other
    RISK_ON_GROUP = ["US500", "NAS100", "BTCUSD"]

    def __init__(self):
        self.open_positions = {}  # symbol -> direction (1 or -1)

    def register_open(self, symbol: str, direction: int):
        self.open_positions[symbol] = direction

    def register_closed(self, symbol: str):
        self.open_positions.pop(symbol, None)

    def is_allowed(self, symbol: str, direction: int) -> bool:
        """
        Returns False if opening this position would double up on
        correlated risk-on exposure already open elsewhere.
        """
        if symbol not in self.RISK_ON_GROUP:
            return True  # filter only applies within the risk-on group

        for open_symbol, open_direction in self.open_positions.items():
            if open_symbol == symbol:
                continue
            if open_symbol in self.RISK_ON_GROUP and open_direction == direction:
                print(f"[CORRELATION FILTER] Blocking {symbol} {'LONG' if direction == 1 else 'SHORT'} "
                      f"- {open_symbol} already {'LONG' if open_direction == 1 else 'SHORT'}")
                return False

        return True

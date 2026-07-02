"""
Strategy 1: Mean Reversion (indices - US500, later NAS100).

Logic:
- On 15-minute candles, compute a 20-period simple moving average and
  standard deviation of closing price.
- When price moves more than `entry_std` standard deviations away from
  the mean, expect a reversion back toward it.
    -> price far BELOW mean  => go LONG (expect bounce back up)
    -> price far ABOVE mean  => go SHORT (expect pullback down)
- Exit signal: price has returned to the moving average.

This module is pure logic - it does not place any trades. It takes a
DataFrame of candles and returns signals. Execution and risk sizing are
handled elsewhere (risk_manager.py, main.py) so this stays easy to test
and backtest in isolation.
"""

import pandas as pd


def add_indicators(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Add moving average, std dev, and upper/lower bands to the DataFrame."""
    df = df.copy()
    df["ma"] = df["close"].rolling(period).mean()
    df["std"] = df["close"].rolling(period).std()
    return df


def generate_signals(df: pd.DataFrame, entry_std: float = 1.5) -> pd.DataFrame:
    """
    Given a DataFrame with 'close', 'ma', 'std' columns, add a 'signal' column:
        1  = long entry signal
       -1  = short entry signal
        0  = no signal (either no edge, or price already near the mean)

    Also adds 'upper_band' and 'lower_band' for reference/plotting.
    """
    df = df.copy()
    df["upper_band"] = df["ma"] + entry_std * df["std"]
    df["lower_band"] = df["ma"] - entry_std * df["std"]

    df["signal"] = 0
    df.loc[df["close"] < df["lower_band"], "signal"] = 1   # oversold -> go long
    df.loc[df["close"] > df["upper_band"], "signal"] = -1  # overbought -> go short

    return df


def check_exit(current_price: float, ma: float, direction: int, tolerance: float = 0.001) -> bool:
    """
    Returns True if an open position should be closed because price has
    reverted back to the moving average.

    direction: 1 for long position, -1 for short position.
    tolerance: how close to the MA counts as "reverted" (as a fraction, e.g. 0.001 = 0.1%)
    """
    if ma == 0:
        return False

    distance_pct = abs(current_price - ma) / ma
    return distance_pct <= tolerance


def run_strategy(df: pd.DataFrame, ma_period: int = 20, entry_std: float = 1.5) -> pd.DataFrame:
    """
    Convenience function: adds indicators and signals in one call.
    Returns the full DataFrame ready for inspection or backtesting.
    """
    df = add_indicators(df, period=ma_period)
    df = generate_signals(df, entry_std=entry_std)
    return df

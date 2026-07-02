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
import numpy as np
from bot.risk_manager import calculate_atr


def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    ADX (Average Directional Index) - the standard measure of trend strength.
    Below ~20-25 = ranging market (good for mean reversion).
    Above ~25 = trending market (mean reversion should sit out).
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(period).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(period).mean() / atr

    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    adx = dx.rolling(period).mean()

    return adx


def add_indicators(df: pd.DataFrame, period: int = 20, atr_period: int = 14, adx_period: int = 14) -> pd.DataFrame:
    """
    Add moving average, std dev, upper/lower bands, ATR (for stop loss),
    and ADX (for the trend filter) to the DataFrame.
    """
    df = df.copy()
    df["ma"] = df["close"].rolling(period).mean()
    df["std"] = df["close"].rolling(period).std()
    df["atr"] = calculate_atr(df, period=atr_period)
    df["adx"] = calculate_adx(df, period=adx_period)
    return df


def generate_signals(df: pd.DataFrame, entry_std: float = 2.0, adx_threshold: float = 25.0) -> pd.DataFrame:
    """
    Given a DataFrame with 'close', 'ma', 'std', 'adx' columns, add a
    'signal' column:
        1  = long entry signal
       -1  = short entry signal
        0  = no signal

    Trend filter: mean reversion only makes sense in a ranging market.
    ADX above `adx_threshold` means a real trend is in play - skip the
    signal even if the std-dev bands were hit, since fading a strong
    trend is how mean reversion strategies blow up.

    Also adds 'upper_band' and 'lower_band' for reference/plotting.
    """
    df = df.copy()
    df["upper_band"] = df["ma"] + entry_std * df["std"]
    df["lower_band"] = df["ma"] - entry_std * df["std"]

    is_ranging = df["adx"] < adx_threshold

    df["signal"] = 0
    df.loc[(df["close"] < df["lower_band"]) & is_ranging, "signal"] = 1   # oversold -> go long
    df.loc[(df["close"] > df["upper_band"]) & is_ranging, "signal"] = -1  # overbought -> go short

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


def run_strategy(df: pd.DataFrame, ma_period: int = 20, entry_std: float = 2.0,
                  atr_period: int = 14, adx_period: int = 14, adx_threshold: float = 25.0) -> pd.DataFrame:
    """
    Convenience function: adds indicators and signals in one call.
    Returns the full DataFrame ready for inspection or backtesting.
    """
    df = add_indicators(df, period=ma_period, atr_period=atr_period, adx_period=adx_period)
    df = generate_signals(df, entry_std=entry_std, adx_threshold=adx_threshold)
    return df
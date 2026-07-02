"""
Helper for pulling historical price data from MT5 into a pandas DataFrame.
Used by strategies and the backtester.
"""

import pandas as pd
import MetaTrader5 as mt5


def get_candles(symbol: str, timeframe, count: int = 500) -> pd.DataFrame:
    """
    Fetch the most recent `count` candles for `symbol` at the given timeframe.

    timeframe: one of mt5.TIMEFRAME_M15, mt5.TIMEFRAME_H1, mt5.TIMEFRAME_H4, etc.

    Returns a DataFrame indexed by time, with columns:
        open, high, low, close, tick_volume, spread, real_volume
    """
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)

    if rates is None or len(rates) == 0:
        raise ValueError(
            f"No candle data returned for '{symbol}'. "
            f"Check the symbol is correct and visible in Market Watch, "
            f"and that MT5 is connected (mt5.initialize() was called)."
        )

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.set_index("time")
    return df

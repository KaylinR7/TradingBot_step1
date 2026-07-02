"""
Step: pull recent XAUUSD 4-hour history from MT5 and run the trend
following strategy against it.

Note: the 200-period EMA needs plenty of history to be meaningful, so
we pull more candles here (1000) than the other strategy tests.

Run with MT5 open and logged in:
    python test_trend_following.py
"""

import MetaTrader5 as mt5
import config
from bot.data_feed import get_candles
from bot.strategies.trend_following import run_strategy, simulate_trades, summarize_trades


def main():
    if not mt5.initialize():
        print("initialize() failed, error code =", mt5.last_error())
        return

    symbol = config.INSTRUMENTS["GLD_EQUIVALENT"]  # XAUUSD
    print(f"Fetching 4-hour candles for {symbol}...")

    df = get_candles(symbol, mt5.TIMEFRAME_H4, count=1000)
    print(f"Got {len(df)} candles, from {df.index[0]} to {df.index[-1]}\n")

    result = run_strategy(df, fast_period=50, slow_period=200, atr_period=14)

    raw_signal_count = (result["signal"] != 0).sum()
    print(f"Raw crossover signal count: {raw_signal_count}\n")

    trades = simulate_trades(result, trail_multiplier=3.0)

    print("=== Trade Summary ===")
    summarize_trades(trades)

    if len(trades) > 0:
        print("\n=== Trade Log (all trades) ===")
        print(trades.to_string(index=False))

    mt5.shutdown()


if __name__ == "__main__":
    main()

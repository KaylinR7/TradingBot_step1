"""
Step 2 test: pull recent US500 history from MT5 and run the mean
reversion strategy against it, so we can see real signals before
building anything else on top of it.

Run with MT5 open and logged in:
    python test_mean_reversion.py
"""

import MetaTrader5 as mt5
import config
from bot.data_feed import get_candles
from bot.strategies.mean_reversion import run_strategy


def main():
    if not mt5.initialize():
        print("initialize() failed, error code =", mt5.last_error())
        return

    symbol = config.INSTRUMENTS["SPY_EQUIVALENT"]  # US500
    print(f"Fetching 15-minute candles for {symbol}...")

    df = get_candles(symbol, mt5.TIMEFRAME_M15, count=500)
    print(f"Got {len(df)} candles, from {df.index[0]} to {df.index[-1]}\n")

    result = run_strategy(df, ma_period=20, entry_std=1.5)

    signals = result[result["signal"] != 0]
    print(f"Found {len(signals)} signal(s) in the last {len(df)} candles:\n")

    if len(signals) == 0:
        print("No signals fired. That's not necessarily wrong - mean reversion "
              "signals are meant to be relatively rare (only firing when price "
              "moves 1.5+ std devs from the mean). Try more candles or check "
              "back after a volatile session.")
    else:
        for time, row in signals.iterrows():
            direction = "LONG" if row["signal"] == 1 else "SHORT"
            print(f"  {time}  {direction:5s}  close={row['close']:.2f}  "
                  f"ma={row['ma']:.2f}  band=[{row['lower_band']:.2f}, {row['upper_band']:.2f}]")

    # Show the most recent few candles regardless, so we can sanity check
    # the indicators look reasonable even without a signal firing.
    print("\nMost recent 5 candles (for sanity check):")
    print(result[["close", "ma", "std", "lower_band", "upper_band", "signal"]].tail(5).to_string())

    mt5.shutdown()


if __name__ == "__main__":
    main()

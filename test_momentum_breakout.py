"""
Step: pull recent BTCUSD 1-hour history from MT5 and run the momentum
breakout strategy against it.

Run with MT5 open and logged in:
    python test_momentum_breakout.py
"""

import MetaTrader5 as mt5
import config
from bot.data_feed import get_candles
from bot.strategies.momentum_breakout import run_strategy
from bot.strategies.momentum_tracker import simulate_trades, summarize_trades


def main():
    if not mt5.initialize():
        print("initialize() failed, error code =", mt5.last_error())
        return

    symbol = config.INSTRUMENTS["BTC_EQUIVALENT"]  # BTCUSD
    print(f"Fetching 1-hour candles for {symbol}...")

    df = get_candles(symbol, mt5.TIMEFRAME_H1, count=500)
    print(f"Got {len(df)} candles, from {df.index[0]} to {df.index[-1]}\n")

    result = run_strategy(df, period=20, atr_period=14, volume_multiplier=1.5)

    raw_signal_count = (result["signal"] != 0).sum()
    print(f"Raw signal count (before position-state filtering): {raw_signal_count}\n")

    trades = simulate_trades(result)

    print("=== Trade Summary ===")
    summarize_trades(trades)

    if len(trades) > 0:
        print("\n=== Trade Log (most recent 10) ===")
        print(trades.tail(10).to_string(index=False))

    mt5.shutdown()


if __name__ == "__main__":
    main()

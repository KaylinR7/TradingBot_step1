"""
Turns raw per-candle signals into actual trades by tracking position state.

Rules:
- Only enter a new trade if we're currently flat (not already in a position).
- Once in a trade, ignore new entry signals - just watch for the exit condition.
- Exit when price reverts back to the moving average (see check_exit in
  mean_reversion.py), i.e. the mean-reversion thesis has played out.

This is deliberately broker/instrument agnostic and doesn't do any position
sizing (that's risk_manager.py's job later) - here we just track price points
so we can validate the entry/exit logic and see a realistic trade count.
"""

import pandas as pd
from bot.strategies.mean_reversion import check_exit


def simulate_trades(df: pd.DataFrame, exit_tolerance: float = 0.001, stop_multiplier: float = 0.75) -> pd.DataFrame:
    """
    Walk through the DataFrame (must already have 'signal', 'ma', and 'atr'
    columns from run_strategy()) and produce a list of completed trades.

    A trade exits on whichever comes first:
      - price reverts back to the moving average (the mean-reversion thesis
        playing out as intended), OR
      - price moves `stop_multiplier` x ATR against the entry (hard stop
        loss - this is what was missing before, and why an early backtest
        without it showed a much better win rate than reality: without a
        stop, a trending day just holds the loser indefinitely instead of
        cutting it).

    Returns a DataFrame with columns:
        entry_time, exit_time, direction, entry_price, exit_price,
        points_gained, exit_reason
    """
    trades = []
    position = None  # None if flat, else dict with entry info

    for time, row in df.iterrows():
        if position is None:
            if row["signal"] == 1 and not pd.isna(row.get("atr")):
                position = {
                    "direction": 1, "entry_time": time, "entry_price": row["close"],
                    "stop_price": row["close"] - row["atr"] * stop_multiplier,
                }
            elif row["signal"] == -1 and not pd.isna(row.get("atr")):
                position = {
                    "direction": -1, "entry_time": time, "entry_price": row["close"],
                    "stop_price": row["close"] + row["atr"] * stop_multiplier,
                }
        else:
            direction = position["direction"]
            stop_hit = (row["close"] <= position["stop_price"]) if direction == 1 else (row["close"] >= position["stop_price"])
            reverted = check_exit(row["close"], row["ma"], direction, tolerance=exit_tolerance)

            if stop_hit or reverted:
                exit_price = position["stop_price"] if stop_hit else row["close"]
                points = (exit_price - position["entry_price"]) * direction

                trades.append({
                    "entry_time": position["entry_time"],
                    "exit_time": time,
                    "direction": "LONG" if direction == 1 else "SHORT",
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "points_gained": points,
                    "exit_reason": "stop_loss" if stop_hit else "reverted_to_mean",
                })
                position = None

    return pd.DataFrame(trades)


def summarize_trades(trades: pd.DataFrame) -> None:
    """Print a quick summary: win rate, avg win/loss, total points."""
    if len(trades) == 0:
        print("No completed trades.")
        return

    wins = trades[trades["points_gained"] > 0]
    losses = trades[trades["points_gained"] <= 0]

    win_rate = len(wins) / len(trades) * 100
    avg_win = wins["points_gained"].mean() if len(wins) > 0 else 0
    avg_loss = losses["points_gained"].mean() if len(losses) > 0 else 0
    total_points = trades["points_gained"].sum()

    print(f"Total trades:   {len(trades)}")
    print(f"Win rate:       {win_rate:.1f}%  ({len(wins)} wins / {len(losses)} losses)")
    print(f"Avg win:        {avg_win:.2f} points")
    print(f"Avg loss:       {avg_loss:.2f} points")
    print(f"Total points:   {total_points:.2f}")
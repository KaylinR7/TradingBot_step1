"""
Simulates momentum breakout trades using a trailing stop, so we can see
real trade-level results the same way position_tracker.py does for
mean reversion.
"""

import pandas as pd
from bot.strategies.momentum_breakout import TrailingStop


def simulate_trades(df: pd.DataFrame) -> pd.DataFrame:
    """
    Walk through the DataFrame (must have 'signal' and 'atr' columns from
    run_strategy()) and produce completed trades using a 2x ATR trailing stop.

    Only enters when flat. Exits when the trailing stop is hit.
    """
    trades = []
    position = None  # None if flat, else dict with entry info + TrailingStop

    for time, row in df.iterrows():
        if position is None:
            if row["signal"] == 1 and not pd.isna(row["atr"]):
                trail = TrailingStop(row["close"], row["atr"], direction=1)
                position = {"direction": 1, "entry_time": time, "entry_price": row["close"], "trail": trail}
            elif row["signal"] == -1 and not pd.isna(row["atr"]):
                trail = TrailingStop(row["close"], row["atr"], direction=-1)
                position = {"direction": -1, "entry_time": time, "entry_price": row["close"], "trail": trail}
        else:
            trail = position["trail"]
            trail.update(row["close"])

            if trail.is_hit(row["close"]):
                direction = position["direction"]
                points = (row["close"] - position["entry_price"]) * direction

                trades.append({
                    "entry_time": position["entry_time"],
                    "exit_time": time,
                    "direction": "LONG" if direction == 1 else "SHORT",
                    "entry_price": position["entry_price"],
                    "exit_price": row["close"],
                    "points_gained": points,
                })
                position = None

    return pd.DataFrame(trades)


def summarize_trades(trades: pd.DataFrame) -> None:
    """Same summary format as position_tracker.py for consistency."""
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

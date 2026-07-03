"""
Strategy 3: Trend Following (XAUUSD, later USOIL).

Logic:
- On 4-hour candles, calculate 50-period and 200-period EMAs.
- Long entry: 50 EMA crosses above 200 EMA ("golden cross").
- Short entry (or exit long): 50 EMA crosses below 200 EMA ("death cross").
- Exit: trailing stop at 3x ATR (wider than momentum breakout's 2x, since
  trend trades are meant to be held through longer, slower-moving swings
  on a higher timeframe - a tighter stop would get shaken out by normal
  4H noise).

Same pattern as the other two strategies: pure logic, no execution.
Reuses TrailingStop from momentum_breakout.py since the mechanism is
identical, just with a different multiplier.
"""

import pandas as pd
from bot.risk_manager import calculate_atr
from bot.strategies.momentum_breakout import TrailingStop


def add_indicators(df: pd.DataFrame, fast_period: int = 50, slow_period: int = 200,
                    atr_period: int = 14) -> pd.DataFrame:
    """Add fast/slow EMAs and ATR to the DataFrame."""
    df = df.copy()
    df["ema_fast"] = df["close"].ewm(span=fast_period, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=slow_period, adjust=False).mean()
    df["atr"] = calculate_atr(df, period=atr_period)
    return df


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds a 'signal' column based on EMA crossovers (not just fast > slow,
    since that would fire on every candle while trending - we only want
    the crossover MOMENT):
        1  = golden cross just happened (fast crossed above slow) -> go long
       -1  = death cross just happened (fast crossed below slow) -> go short / exit long
        0  = no new crossover this candle
    """
    df = df.copy()

    fast_above_slow = df["ema_fast"] > df["ema_slow"]
    prev_fast_above_slow = fast_above_slow.shift(1, fill_value=False)

    golden_cross = fast_above_slow & (~prev_fast_above_slow)
    death_cross = (~fast_above_slow) & prev_fast_above_slow

    df["signal"] = 0
    df.loc[golden_cross, "signal"] = 1
    df.loc[death_cross, "signal"] = -1

    return df


def run_strategy(df: pd.DataFrame, fast_period: int = 50, slow_period: int = 200,
                  atr_period: int = 14) -> pd.DataFrame:
    """Convenience function: adds indicators and signals in one call."""
    df = add_indicators(df, fast_period=fast_period, slow_period=slow_period, atr_period=atr_period)
    df = generate_signals(df)
    return df


def simulate_trades(df: pd.DataFrame, trail_multiplier: float = 3.0) -> pd.DataFrame:
    """
    Same pattern as momentum_tracker.simulate_trades, but with a wider
    3x ATR trailing stop appropriate for trend following.

    Note: unlike momentum breakout, a death cross signal while long should
    EXIT the long (not just be ignored), since it means the trend has
    reversed. Same logic applies in reverse for shorts.
    """
    trades = []
    position = None

    for time, row in df.iterrows():
        if position is None:
            if row["signal"] == 1 and not pd.isna(row["atr"]):
                trail = TrailingStop(row["close"], row["atr"], direction=1, multiplier=trail_multiplier)
                position = {"direction": 1, "entry_time": time, "entry_price": row["close"], "trail": trail}
            elif row["signal"] == -1 and not pd.isna(row["atr"]):
                trail = TrailingStop(row["close"], row["atr"], direction=-1, multiplier=trail_multiplier)
                position = {"direction": -1, "entry_time": time, "entry_price": row["close"], "trail": trail}
        else:
            direction = position["direction"]
            trail = position["trail"]
            trail.update(row["close"])

            # Exit on trailing stop hit, OR on an opposite crossover signal
            # (trend has reversed - no point waiting for the wider trailing stop)
            opposite_signal = (row["signal"] == -1 and direction == 1) or (row["signal"] == 1 and direction == -1)
            stop_hit = trail.is_hit(row["close"])

            if stop_hit or opposite_signal:
                points = (row["close"] - position["entry_price"]) * direction
                trades.append({
                    "entry_time": position["entry_time"],
                    "exit_time": time,
                    "direction": "LONG" if direction == 1 else "SHORT",
                    "entry_price": position["entry_price"],
                    "exit_price": row["close"],
                    "points_gained": points,
                    "exit_reason": "trailing_stop" if stop_hit else "opposite_crossover",
                })
                position = None

    return pd.DataFrame(trades)


def summarize_trades(trades: pd.DataFrame) -> None:
    """Same summary format as the other strategies for consistency."""
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

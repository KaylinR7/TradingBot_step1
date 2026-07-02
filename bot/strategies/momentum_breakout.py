"""
Strategy 2: Momentum Breakout (BTCUSD).

Logic:
- On 1-hour candles, track the 20-period rolling high and low.
- Long entry: price breaks above the 20-period high, AND current volume
  is at least 1.5x the 20-period average volume (confirms real momentum,
  not a low-volume fakeout).
- Short entry (or exit long): price breaks below the 20-period low with
  the same volume confirmation.
- Exit: trailing stop at 2x ATR (handled by the trailing stop tracker
  below, since a trailing stop needs to be updated candle by candle as
  price moves in the trade's favor).

Same pattern as mean_reversion.py: pure logic here, no order execution.
"""

import pandas as pd
from bot.risk_manager import calculate_atr


def add_indicators(df: pd.DataFrame, period: int = 20, atr_period: int = 14) -> pd.DataFrame:
    """Add rolling high/low, average volume, and ATR to the DataFrame."""
    df = df.copy()

    # shift(1) so the current candle isn't included in its own breakout level -
    # otherwise every candle would trivially "break" its own high/low.
    df["rolling_high"] = df["high"].shift(1).rolling(period).max()
    df["rolling_low"] = df["low"].shift(1).rolling(period).min()
    df["avg_volume"] = df["tick_volume"].shift(1).rolling(period).mean()
    df["atr"] = calculate_atr(df, period=atr_period)

    return df


def generate_signals(df: pd.DataFrame, volume_multiplier: float = 1.5) -> pd.DataFrame:
    """
    Adds a 'signal' column:
        1  = long breakout (price broke above rolling high + volume confirmed)
       -1  = short breakout (price broke below rolling low + volume confirmed)
        0  = no signal
    """
    df = df.copy()

    volume_confirmed = df["tick_volume"] >= (df["avg_volume"] * volume_multiplier)
    broke_high = df["close"] > df["rolling_high"]
    broke_low = df["close"] < df["rolling_low"]

    df["signal"] = 0
    df.loc[broke_high & volume_confirmed, "signal"] = 1
    df.loc[broke_low & volume_confirmed, "signal"] = -1

    return df


def run_strategy(df: pd.DataFrame, period: int = 20, atr_period: int = 14,
                  volume_multiplier: float = 1.5) -> pd.DataFrame:
    """Convenience function: adds indicators and signals in one call."""
    df = add_indicators(df, period=period, atr_period=atr_period)
    df = generate_signals(df, volume_multiplier=volume_multiplier)
    return df


class TrailingStop:
    """
    Tracks a 2x ATR trailing stop for an open momentum trade.
    Unlike mean reversion's fixed exit, this stop only ever moves in the
    trade's favor (up for longs, down for shorts) and never retreats -
    that's what makes it "trailing".
    """

    def __init__(self, entry_price: float, atr: float, direction: int, multiplier: float = 2.0):
        self.direction = direction  # 1 = long, -1 = short
        self.multiplier = multiplier
        self.stop_distance = atr * multiplier

        if direction == 1:
            self.stop_price = entry_price - self.stop_distance
        else:
            self.stop_price = entry_price + self.stop_distance

    def update(self, current_price: float) -> None:
        """Call this on every new candle to potentially tighten the stop."""
        if self.direction == 1:
            new_stop = current_price - self.stop_distance
            if new_stop > self.stop_price:
                self.stop_price = new_stop
        else:
            new_stop = current_price + self.stop_distance
            if new_stop < self.stop_price:
                self.stop_price = new_stop

    def is_hit(self, current_price: float) -> bool:
        """Returns True if price has hit the trailing stop."""
        if self.direction == 1:
            return current_price <= self.stop_price
        else:
            return current_price >= self.stop_price

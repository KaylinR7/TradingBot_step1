"""
Step 4: Full backtester.

Runs all 3 strategies against their respective instruments using real
ATR-based position sizing (via risk_manager) and realistic slippage,
then reports the metrics that actually matter before risking real money:
win rate, profit factor, max drawdown, Sharpe ratio, total return.

Simplification note: each instrument gets its own independent equity
curve (starting from the same capital), then we combine them into a
portfolio view by summing dollar P&L. This does NOT fully model the
correlation filter (which depends on real-time position overlap across
instruments) - that's enforced properly in the live/paper trading loop
(main.py) where it actually matters. This backtest is for validating
strategy edge and risk-adjusted performance per instrument.
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # no display needed, just save the file
import matplotlib.pyplot as plt

import MetaTrader5 as mt5
import config
from bot.data_feed import get_candles
from bot.risk_manager import calculate_atr, calculate_position_size

from bot.strategies import mean_reversion
from bot.strategies import momentum_breakout
from bot.strategies import trend_following
from bot.strategies.momentum_tracker import simulate_trades as simulate_momentum
from bot.strategies.trend_following import simulate_trades as simulate_trend

SLIPPAGE_PCT = 0.05 / 100  # 0.05% per trade, applied to both entry and exit
STARTING_EQUITY = 10000.0  # backtest capital per instrument, independent of your live demo balance


def apply_slippage(price: float, direction: int, is_entry: bool) -> float:
    """
    Slippage always works against you: entries fill slightly worse,
    exits fill slightly worse too.
    direction: 1 = long, -1 = short.
    """
    adverse_direction = direction if is_entry else -direction
    return price * (1 + adverse_direction * SLIPPAGE_PCT)


def size_and_price_trades(trades: pd.DataFrame, price_df: pd.DataFrame, starting_equity: float) -> pd.DataFrame:
    """
    Takes a trades DataFrame (entry_time, exit_time, direction, entry_price,
    exit_price, points_gained) and:
      1. Applies slippage to entry/exit prices
      2. Sizes each trade using the real risk manager (1% risk, ATR-based),
         using the equity as of that point in the backtest (compounding)
      3. Computes dollar P&L per trade and a running equity curve

    Returns the trades DataFrame with added columns: position_size,
    dollar_pnl, equity_after.
    """
    if len(trades) == 0:
        return trades

    trades = trades.copy()
    equity = starting_equity
    dollar_pnls = []
    position_sizes = []
    equity_curve = []

    for _, trade in trades.iterrows():
        direction = 1 if trade["direction"] == "LONG" else -1

        entry_slipped = apply_slippage(trade["entry_price"], direction, is_entry=True)
        exit_slipped = apply_slippage(trade["exit_price"], direction, is_entry=False)

        # ATR at entry time, for position sizing
        atr_at_entry = price_df.loc[:trade["entry_time"], "atr"].iloc[-1] if "atr" in price_df.columns else None
        if atr_at_entry is None or pd.isna(atr_at_entry) or atr_at_entry <= 0:
            # fall back to a small default so the backtest doesn't crash;
            # in live trading we'd never enter without a valid ATR
            atr_at_entry = abs(entry_slipped) * 0.005

        sizing = calculate_position_size(equity, atr_at_entry, entry_slipped)
        position_size = sizing["position_size"]

        points = (exit_slipped - entry_slipped) * direction
        dollar_pnl = points * position_size

        equity += dollar_pnl

        dollar_pnls.append(round(dollar_pnl, 2))
        position_sizes.append(position_size)
        equity_curve.append(round(equity, 2))

    trades["position_size"] = position_sizes
    trades["dollar_pnl"] = dollar_pnls
    trades["equity_after"] = equity_curve

    return trades


def calculate_metrics(trades: pd.DataFrame, starting_equity: float) -> dict:
    """Compute win rate, profit factor, max drawdown, Sharpe ratio, total return."""
    if len(trades) == 0:
        return {
            "total_trades": 0, "win_rate": 0, "profit_factor": 0,
            "max_drawdown_pct": 0, "sharpe_ratio": 0, "total_return_pct": 0,
        }

    wins = trades[trades["dollar_pnl"] > 0]
    losses = trades[trades["dollar_pnl"] <= 0]

    total_trades = len(trades)
    win_rate = len(wins) / total_trades * 100

    gross_profit = wins["dollar_pnl"].sum()
    gross_loss = abs(losses["dollar_pnl"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    equity_curve = pd.concat([pd.Series([starting_equity]), trades["equity_after"]], ignore_index=True)
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max * 100
    max_drawdown_pct = drawdown.min()

    # Sharpe ratio on a per-trade return basis (not annualized - trade
    # frequency varies too much across these 3 strategies for that to be
    # meaningful here). This is a relative measure: higher is better,
    # negative means the strategy lost money on a risk-adjusted basis.
    trade_returns = trades["dollar_pnl"] / starting_equity
    sharpe_ratio = (trade_returns.mean() / trade_returns.std()) if trade_returns.std() > 0 else 0

    total_return_pct = (equity_curve.iloc[-1] - starting_equity) / starting_equity * 100

    return {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "sharpe_ratio": round(sharpe_ratio, 3),
        "total_return_pct": round(total_return_pct, 2),
    }


def run_mean_reversion_backtest(symbol: str):
    df = get_candles(symbol, mt5.TIMEFRAME_M15, count=2000)  # ~3 weeks of 15m bars
    result = mean_reversion.run_strategy(df, ma_period=20, entry_std=2.0, atr_period=14, adx_threshold=25.0)

    from bot.position_tracker import simulate_trades as simulate_mr
    trades = simulate_mr(result)
    trades = size_and_price_trades(trades, result, STARTING_EQUITY)
    return trades, result


def run_momentum_backtest(symbol: str):
    df = get_candles(symbol, mt5.TIMEFRAME_H1, count=2000)  # ~3 months of 1H bars
    result = momentum_breakout.run_strategy(df, period=20, atr_period=14, volume_multiplier=1.5)
    trades = simulate_momentum(result)
    trades = size_and_price_trades(trades, result, STARTING_EQUITY)
    return trades, result


def run_trend_backtest(symbol: str):
    df = get_candles(symbol, mt5.TIMEFRAME_H4, count=1000)  # ~5-6 months of 4H bars
    result = trend_following.run_strategy(df, fast_period=50, slow_period=200, atr_period=14)
    trades = simulate_trend(result, trail_multiplier=3.0)
    trades = size_and_price_trades(trades, result, STARTING_EQUITY)
    return trades, result


def plot_equity_curves(results: dict, filename: str = "backtest_results.png"):
    """results: dict of label -> trades DataFrame with 'equity_after' column."""
    plt.figure(figsize=(10, 6))

    for label, trades in results.items():
        if len(trades) == 0:
            continue
        equity_curve = pd.concat([pd.Series([STARTING_EQUITY]), trades["equity_after"]], ignore_index=True)
        plt.plot(equity_curve.values, label=label, marker="o", markersize=3)

    plt.axhline(y=STARTING_EQUITY, color="gray", linestyle="--", alpha=0.5, label="Starting equity")
    plt.title("Backtest Equity Curves (per instrument, independent starting capital)")
    plt.xlabel("Trade number")
    plt.ylabel("Equity ($)")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(filename, dpi=120)
    print(f"\nEquity curve chart saved to {filename}")


def print_summary_table(all_metrics: dict):
    print("\n" + "=" * 100)
    print(f"{'Instrument/Strategy':<28} {'Trades':>7} {'WinRate%':>9} {'ProfitFactor':>13} "
          f"{'MaxDD%':>8} {'Sharpe':>8} {'Return%':>9}")
    print("-" * 100)
    for label, m in all_metrics.items():
        print(f"{label:<28} {m['total_trades']:>7} {m['win_rate']:>9} {m['profit_factor']:>13} "
              f"{m['max_drawdown_pct']:>8} {m['sharpe_ratio']:>8} {m['total_return_pct']:>9}")
    print("=" * 100)

    for label, m in all_metrics.items():
        if m["sharpe_ratio"] < 0 and m["total_trades"] > 0:
            print(f"[FLAG] {label} has a negative Sharpe ratio ({m['sharpe_ratio']}) - "
                  f"consider revisiting its parameters before paper/live trading.")


def main():
    if not mt5.initialize():
        print("initialize() failed, error code =", mt5.last_error())
        return

    print(f"Starting equity per instrument: ${STARTING_EQUITY:,.2f}")
    print(f"Slippage: {SLIPPAGE_PCT * 100:.2f}% per fill\n")

    print("Running Mean Reversion backtest on US500...")
    mr_trades, mr_df = run_mean_reversion_backtest(config.INSTRUMENTS["SPY_EQUIVALENT"])

    print("Running Momentum Breakout backtest on BTCUSD...")
    mom_trades, mom_df = run_momentum_backtest(config.INSTRUMENTS["BTC_EQUIVALENT"])

    print("Running Trend Following backtest on XAUUSD...")
    trend_trades, trend_df = run_trend_backtest(config.INSTRUMENTS["GLD_EQUIVALENT"])

    results = {
        "Mean Reversion (US500)": mr_trades,
        "Momentum Breakout (BTCUSD)": mom_trades,
        "Trend Following (XAUUSD)": trend_trades,
    }

    all_metrics = {label: calculate_metrics(trades, STARTING_EQUITY) for label, trades in results.items()}

    # Combined portfolio: sum dollar P&L across all instruments as if run
    # in parallel (see the scoping note at the top of this file re: what
    # this does and doesn't capture about correlation).
    combined_pnl = pd.concat([t["dollar_pnl"] for t in results.values() if len(t) > 0])
    combined_trades_count = len(combined_pnl)
    combined_return_pct = combined_pnl.sum() / (STARTING_EQUITY * 3) * 100  # 3x capital deployed total
    print(f"\nCombined portfolio (sum of all 3, {STARTING_EQUITY * 3:,.0f} total capital deployed):")
    print(f"  Total trades: {combined_trades_count}")
    print(f"  Total P&L: ${combined_pnl.sum():,.2f}")
    print(f"  Combined return: {combined_return_pct:.2f}%")

    print_summary_table(all_metrics)

    plot_equity_curves(results)

    mt5.shutdown()


if __name__ == "__main__":
    main()
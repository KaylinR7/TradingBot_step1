"""
Step 3 test: verify ATR calculation and position sizing look sane against
real US500 data and your actual demo account equity.

Run with MT5 open and logged in:
    python test_risk_manager.py
"""

import MetaTrader5 as mt5
import config
from bot.data_feed import get_candles
from bot.risk_manager import calculate_atr, calculate_position_size, get_stop_price, DrawdownGuard, CorrelationFilter


def main():
    if not mt5.initialize():
        print("initialize() failed, error code =", mt5.last_error())
        return

    account = mt5.account_info()
    equity = account.equity
    print(f"Account equity: {equity} {account.currency}\n")

    symbol = config.INSTRUMENTS["SPY_EQUIVALENT"]  # US500
    df = get_candles(symbol, mt5.TIMEFRAME_M15, count=100)

    df["atr"] = calculate_atr(df, period=14)
    latest_atr = df["atr"].iloc[-1]
    latest_price = df["close"].iloc[-1]

    print(f"=== {symbol} ===")
    print(f"Latest price: {latest_price}")
    print(f"Latest 14-period ATR (15m candles): {latest_atr:.4f}\n")

    sizing = calculate_position_size(equity, latest_atr, latest_price)
    print("Position sizing for a 1% risk trade:")
    for k, v in sizing.items():
        print(f"  {k}: {v}")

    long_stop = get_stop_price(latest_price, sizing["stop_distance"], direction=1)
    short_stop = get_stop_price(latest_price, sizing["stop_distance"], direction=-1)
    print(f"\nIf LONG at {latest_price}: stop loss at {long_stop:.2f}")
    print(f"If SHORT at {latest_price}: stop loss at {short_stop:.2f}")

    # Sanity check: does risk_amount actually equal 1% of equity?
    expected_risk = equity * (config.RISK_PER_TRADE_PCT / 100)
    print(f"\nExpected risk amount (1% of equity): {expected_risk:.2f}")
    print(f"Calculated risk amount:               {sizing['risk_amount']:.2f}")
    print("Match!" if abs(expected_risk - sizing["risk_amount"]) < 0.01 else "MISMATCH - check the math")

    # Quick test of the drawdown guard with fake equity curve
    print("\n=== Drawdown Guard test (simulated equity curve) ===")
    guard = DrawdownGuard(max_drawdown_pct=10.0)
    fake_equity_curve = [1000, 1050, 1100, 1000, 950, 900, 990]  # dips ~18% from peak of 1100
    for eq in fake_equity_curve:
        allowed = guard.update(eq)
        print(f"  equity={eq}  trading_allowed={allowed}")

    # Quick test of the correlation filter
    print("\n=== Correlation Filter test ===")
    corr = CorrelationFilter()
    corr.register_open("US500", 1)  # US500 already long
    print("BTCUSD long allowed while US500 long?", corr.is_allowed("BTCUSD", 1))
    print("BTCUSD short allowed while US500 long?", corr.is_allowed("BTCUSD", -1))
    print("XAUUSD long allowed (not in risk-on group)?", corr.is_allowed("XAUUSD", 1))

    mt5.shutdown()


if __name__ == "__main__":
    main()

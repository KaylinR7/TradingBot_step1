"""
Pre-flight check before running the live bot. Validates:
  - MT5 connection
  - Symbol contract specs (needed for correct lot sizing)
  - Lot size conversion from risk-manager units to broker lots
  - That "Algo Trading" is enabled (orders will be rejected otherwise)

Does NOT place any real orders. Run this first:
    python test_execution_dryrun.py
"""

import MetaTrader5 as mt5
import config
from bot.data_feed import get_candles
from bot.risk_manager import calculate_atr, calculate_position_size, get_stop_price
from bot.main import get_lot_size, get_account_equity


def main():
    if not mt5.initialize(login=config.MT5_LOGIN, password=config.MT5_PASSWORD, server=config.MT5_SERVER):
        print("initialize() failed:", mt5.last_error())
        return

    term = mt5.terminal_info()
    print(f"Terminal connected: {term.connected}")
    print(f"Algo trading enabled: {term.trade_allowed}")
    if not term.trade_allowed:
        print("  >> WARNING: enable the 'Algo Trading' button in the MT5 toolbar, "
              "or orders will be rejected when the bot runs.")

    equity = get_account_equity()
    print(f"Account equity: ${equity:.2f}\n")

    for label, symbol in config.INSTRUMENTS.items():
        info = mt5.symbol_info(symbol)
        if info is None:
            print(f"[SKIP] {symbol} not found")
            continue

        print(f"=== {symbol} ===")
        print(f"  contract_size: {info.trade_contract_size}")
        print(f"  volume_min: {info.volume_min}  volume_max: {info.volume_max}  volume_step: {info.volume_step}")

        # Simulate what the bot would do for a hypothetical signal
        tf = mt5.TIMEFRAME_H1 if symbol == config.INSTRUMENTS["BTC_EQUIVALENT"] else mt5.TIMEFRAME_H4
        df = get_candles(symbol, tf, count=100)
        df["atr"] = calculate_atr(df, period=14)
        atr = df["atr"].iloc[-1]
        price = df["close"].iloc[-1]

        risk_pct = config.get_risk_pct(symbol)
        sizing = calculate_position_size(equity, atr, price, risk_pct=risk_pct)
        lots = get_lot_size(symbol, sizing["position_size"])
        long_stop = get_stop_price(price, sizing["stop_distance"], 1)

        # What the intended risk was, vs what the actual risk will be given
        # broker lot rounding + contract size. These should match closely;
        # a big gap means the account is too small to trade this instrument
        # at the target risk %.
        actual_risk = sizing["stop_distance"] * lots * info.trade_contract_size

        print(f"  latest price: {price:.2f}  ATR: {atr:.4f}")
        print(f"  risk %: {risk_pct}%   risk-manager units: {sizing['position_size']}  ->  broker lots: {lots}")
        print(f"  intended risk: ${sizing['risk_amount']:.2f}   actual risk at {lots} lots: ${actual_risk:.2f}")
        if lots > 0 and abs(actual_risk - sizing["risk_amount"]) > sizing["risk_amount"] * 0.5:
            print(f"  >> WARNING: actual risk (${actual_risk:.2f}) is far from target (${sizing['risk_amount']:.2f}). "
                  f"Account may be too small to trade {symbol} at {config.RISK_PER_TRADE_PCT}% risk.")
        print(f"  if LONG now: entry ~{price:.2f}, stop {long_stop:.2f}")
        print()

    mt5.shutdown()
    print("Dry run complete. No orders were placed.")


if __name__ == "__main__":
    main()
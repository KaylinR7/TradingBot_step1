"""
Step 1: Confirm Python can connect to your running MT5 terminal
and pull a live quote for each instrument we plan to trade.

Run this with the MT5 terminal open and logged into your demo account.
    python test_connection.py
"""

import MetaTrader5 as mt5
import config


def connect():
    # If MT5 terminal is already open and logged in, mt5.initialize() with
    # no args will just attach to it. We pass login details too in case
    # it needs to log in fresh.
    if config.MT5_PATH:
        ok = mt5.initialize(
            path=config.MT5_PATH,
            login=config.MT5_LOGIN,
            password=config.MT5_PASSWORD,
            server=config.MT5_SERVER,
        )
    else:
        ok = mt5.initialize(
            login=config.MT5_LOGIN,
            password=config.MT5_PASSWORD,
            server=config.MT5_SERVER,
        )

    if not ok:
        print("initialize() failed, error code =", mt5.last_error())
        return False

    account_info = mt5.account_info()
    if account_info is None:
        print("Connected, but couldn't read account info. Error:", mt5.last_error())
        return False

    print("Connected successfully.")
    print(f"  Login:    {account_info.login}")
    print(f"  Server:   {account_info.server}")
    print(f"  Balance:  {account_info.balance} {account_info.currency}")
    print(f"  Equity:   {account_info.equity} {account_info.currency}")
    return True


def check_instruments():
    print("\nChecking instrument symbols...")
    for label, symbol in config.INSTRUMENTS.items():
        info = mt5.symbol_info(symbol)
        if info is None:
            print(f"  [MISSING] {label} -> '{symbol}' not found in Market Watch. "
                  f"Check the exact symbol name in your terminal (right-click Market Watch -> Show All).")
            continue

        # Make sure it's visible/selected so we can pull quotes
        if not info.visible:
            mt5.symbol_select(symbol, True)

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            print(f"  [NO TICK] {label} -> '{symbol}' found but no live tick yet.")
        else:
            print(f"  [OK] {label} -> '{symbol}'  bid={tick.bid}  ask={tick.ask}")


if __name__ == "__main__":
    if connect():
        check_instruments()
        mt5.shutdown()

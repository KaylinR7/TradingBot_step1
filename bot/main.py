"""
bot/main.py - the live/paper trading loop.

Runs continuously, checking each instrument at its appropriate interval:
  - BTCUSD: every 1 hour (momentum breakout on H1 candles)
  - XAUUSD: every 4 hours (trend following on H4 candles)

On each check:
  1. Pull latest candles from MT5
  2. Run the relevant strategy to get the current signal
  3. If there's a signal and we're flat, check the correlation filter and
     risk manager, then send the order to MT5
  4. If we're already in a position, check for exit conditions and close
     if needed
  5. Log everything to CSV files for the daily briefing

All order execution uses MT5's market orders with an explicit stop loss
set at the time of entry (not a trailing stop managed externally - MT5
handles the stop internally for safety).
"""

import time
import csv
import os
import logging
from datetime import datetime, timezone

import MetaTrader5 as mt5
import pandas as pd

import config
from bot.data_feed import get_candles
from bot.risk_manager import (
    calculate_atr, calculate_position_size, get_stop_price,
    DrawdownGuard, CorrelationFilter
)
from bot.strategies.momentum_breakout import run_strategy as run_momentum, TrailingStop
from bot.strategies.trend_following import run_strategy as run_trend, simulate_trades

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# --- CSV log files ---
TRADES_CSV = "trades.csv"
DAILY_PNL_CSV = "daily_pnl.csv"

TRADE_FIELDS = ["timestamp", "symbol", "direction", "entry_price", "exit_price",
                 "position_size", "profit_loss", "exit_reason"]
PNL_FIELDS = ["date", "starting_equity", "ending_equity", "daily_pnl", "daily_pnl_pct"]


def ensure_csv_headers():
    for path, fields in [(TRADES_CSV, TRADE_FIELDS), (DAILY_PNL_CSV, PNL_FIELDS)]:
        if not os.path.exists(path):
            with open(path, "w", newline="") as f:
                csv.DictWriter(f, fieldnames=fields).writeheader()


def log_trade(record: dict):
    with open(TRADES_CSV, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=TRADE_FIELDS).writerow(record)


def log_daily_pnl(starting_equity: float, ending_equity: float):
    daily_pnl = ending_equity - starting_equity
    with open(DAILY_PNL_CSV, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=PNL_FIELDS).writerow({
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "starting_equity": round(starting_equity, 2),
            "ending_equity": round(ending_equity, 2),
            "daily_pnl": round(daily_pnl, 2),
            "daily_pnl_pct": round(daily_pnl / starting_equity * 100, 3),
        })


# --- MT5 order helpers ---

def get_account_equity() -> float:
    info = mt5.account_info()
    return info.equity if info else 0.0


def get_open_position(symbol: str):
    """Returns the open MT5 position for a symbol, or None if flat."""
    positions = mt5.positions_get(symbol=symbol)
    return positions[0] if positions else None


def get_lot_size(symbol: str, units: float) -> float:
    """
    Convert raw position_size units from risk_manager to MT5 lots,
    correctly accounting for the instrument's contract size.

    The risk manager computes `units` such that:
        stop_distance (in price points) * units == risk_amount ($)
    But for MT5, P&L per lot = price_move * contract_size * lots.
    So to preserve the intended dollar risk:
        units == contract_size * lots   =>   lots = units / contract_size

    This matters a lot for instruments like XAUUSD where contract_size
    is 100 - without dividing, a "0.24 unit" position would be sized as
    0.24 lots, risking 100x too much. (Verified in the dry-run: gold's
    contract_size is 100 vs 1.0 for US500/BTCUSD.)
    """
    info = mt5.symbol_info(symbol)
    if info is None:
        return 0.0  # signal failure rather than silently trading minimum

    contract_size = info.trade_contract_size
    lots = units / contract_size

    min_lot = info.volume_min
    max_lot = info.volume_max
    step = info.volume_step

    # Round to the nearest valid step
    lots = round(lots / step) * step

    # Only clamp UP to minimum if we're within one step of it - otherwise
    # a position that's genuinely too small to trade at the intended risk
    # should be flagged, not silently inflated to the minimum (which would
    # risk more than 1%).
    if lots < min_lot:
        if lots >= min_lot * 0.5:
            lots = min_lot
        else:
            log.warning(f"{symbol}: computed lots {lots:.4f} is well below broker minimum "
                        f"{min_lot} - trading minimum would exceed intended 1% risk. Skipping.")
            return 0.0

    lots = min(max_lot, lots)
    return round(lots, 2)


def send_order(symbol: str, direction: int, lots: float, stop_price: float) -> bool:
    """
    Send a market order with a hard stop loss set at entry time.
    direction: 1 = buy, -1 = sell.
    Returns True if the order was filled successfully.
    """
    order_type = mt5.ORDER_TYPE_BUY if direction == 1 else mt5.ORDER_TYPE_SELL
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        log.error(f"No tick data for {symbol}, aborting order")
        return False

    price = tick.ask if direction == 1 else tick.bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lots,
        "type": order_type,
        "price": price,
        "sl": round(stop_price, 5),
        "tp": 0.0,
        "deviation": 20,  # max slippage in points
        "magic": 12345,   # unique bot ID for filtering in MT5
        "comment": "trading_bot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error(f"Order failed for {symbol}: retcode={result.retcode} comment={result.comment}")
        return False

    log.info(f"Order filled: {symbol} {'BUY' if direction == 1 else 'SELL'} "
             f"{lots} lots @ {price:.2f}  SL={stop_price:.2f}")
    return True


def close_position(symbol: str, position) -> float:
    """Close an open MT5 position. Returns the profit/loss."""
    direction = -1 if position.type == mt5.POSITION_TYPE_BUY else 1
    order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY

    tick = mt5.symbol_info_tick(symbol)
    price = tick.bid if direction == -1 else tick.ask

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": position.volume,
        "type": order_type,
        "position": position.ticket,
        "price": price,
        "deviation": 20,
        "magic": 12345,
        "comment": "trading_bot_close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error(f"Close failed for {symbol}: retcode={result.retcode}")
        return 0.0

    profit = position.profit
    log.info(f"Closed: {symbol}  P&L={profit:.2f}")
    return profit


# --- Per-strategy check functions ---

def check_momentum(symbol: str, equity: float, corr: CorrelationFilter,
                   trailing_stops: dict) -> None:
    """Check BTCUSD for momentum breakout signals or exit conditions."""
    try:
        df = get_candles(symbol, mt5.TIMEFRAME_H1, count=100)
        result = run_momentum(df, period=20, atr_period=14, volume_multiplier=1.5)
        latest = result.iloc[-1]
        position = get_open_position(symbol)

        if position:
            # Update/check trailing stop
            if symbol not in trailing_stops:
                direction = 1 if position.type == mt5.POSITION_TYPE_BUY else -1
                atr = latest["atr"]
                trailing_stops[symbol] = TrailingStop(position.price_open, atr, direction, multiplier=2.0)

            trail = trailing_stops[symbol]
            tick = mt5.symbol_info_tick(symbol)
            if tick:
                trail.update(tick.bid)
                if trail.is_hit(tick.bid):
                    profit = close_position(symbol, position)
                    corr.register_closed(symbol)
                    direction = 1 if position.type == mt5.POSITION_TYPE_BUY else -1
                    log_trade({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "symbol": symbol,
                        "direction": "LONG" if direction == 1 else "SHORT",
                        "entry_price": position.price_open,
                        "exit_price": tick.bid,
                        "position_size": position.volume,
                        "profit_loss": profit,
                        "exit_reason": "trailing_stop",
                    })
                    trailing_stops.pop(symbol, None)
        else:
            signal = int(latest["signal"])
            if signal != 0 and not pd.isna(latest["atr"]):
                if not corr.is_allowed(symbol, signal):
                    return
                sizing = calculate_position_size(equity, latest["atr"], latest["close"],
                                                 risk_pct=config.get_risk_pct(symbol))
                stop = get_stop_price(latest["close"], sizing["stop_distance"], signal)
                lots = get_lot_size(symbol, sizing["position_size"])
                if send_order(symbol, signal, lots, stop):
                    corr.register_open(symbol, signal)
                    trailing_stops[symbol] = TrailingStop(latest["close"], latest["atr"], signal, multiplier=2.0)
                    log_trade({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "symbol": symbol,
                        "direction": "LONG" if signal == 1 else "SHORT",
                        "entry_price": latest["close"],
                        "exit_price": "",
                        "position_size": lots,
                        "profit_loss": "",
                        "exit_reason": "",
                    })
    except Exception as e:
        log.error(f"Error in check_momentum ({symbol}): {e}")


def check_trend(symbol: str, equity: float, corr: CorrelationFilter,
                trailing_stops: dict) -> None:
    """Check XAUUSD for trend following signals or exit conditions."""
    try:
        df = get_candles(symbol, mt5.TIMEFRAME_H4, count=500)
        result = run_trend(df, fast_period=50, slow_period=200, atr_period=14)
        latest = result.iloc[-1]
        position = get_open_position(symbol)

        if position:
            if symbol not in trailing_stops:
                direction = 1 if position.type == mt5.POSITION_TYPE_BUY else -1
                trailing_stops[symbol] = TrailingStop(position.price_open, latest["atr"], direction, multiplier=3.0)

            trail = trailing_stops[symbol]
            tick = mt5.symbol_info_tick(symbol)
            current_price = tick.bid if tick else latest["close"]
            trail.update(current_price)

            direction = 1 if position.type == mt5.POSITION_TYPE_BUY else -1
            opposite = (latest["signal"] == -1 and direction == 1) or (latest["signal"] == 1 and direction == -1)

            if trail.is_hit(current_price) or opposite:
                profit = close_position(symbol, position)
                corr.register_closed(symbol)
                exit_reason = "opposite_crossover" if opposite else "trailing_stop"
                log_trade({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "symbol": symbol,
                    "direction": "LONG" if direction == 1 else "SHORT",
                    "entry_price": position.price_open,
                    "exit_price": current_price,
                    "position_size": position.volume,
                    "profit_loss": profit,
                    "exit_reason": exit_reason,
                })
                trailing_stops.pop(symbol, None)
        else:
            signal = int(latest["signal"])
            if signal != 0 and not pd.isna(latest["atr"]):
                sizing = calculate_position_size(equity, latest["atr"], latest["close"],
                                                 risk_pct=config.get_risk_pct(symbol))
                stop = get_stop_price(latest["close"], sizing["stop_distance"], signal)
                lots = get_lot_size(symbol, sizing["position_size"])
                if send_order(symbol, signal, lots, stop):
                    corr.register_open(symbol, signal)
                    trailing_stops[symbol] = TrailingStop(latest["close"], latest["atr"], signal, multiplier=3.0)
                    log_trade({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "symbol": symbol,
                        "direction": "LONG" if signal == 1 else "SHORT",
                        "entry_price": latest["close"],
                        "exit_price": "",
                        "position_size": lots,
                        "profit_loss": "",
                        "exit_reason": "",
                    })
    except Exception as e:
        log.error(f"Error in check_trend ({symbol}): {e}")


# --- Main loop ---

def main():
    log.info("Starting trading bot...")
    ensure_csv_headers()

    if not mt5.initialize(
        login=config.MT5_LOGIN,
        password=config.MT5_PASSWORD,
        server=config.MT5_SERVER,
    ):
        log.error(f"MT5 initialize() failed: {mt5.last_error()}")
        return

    log.info(f"Connected to MT5 - account {config.MT5_LOGIN} on {config.MT5_SERVER}")

    guard = DrawdownGuard()
    corr = CorrelationFilter()
    trailing_stops = {}

    # Check intervals in seconds
    MOMENTUM_INTERVAL = 60 * 60       # 1 hour
    TREND_INTERVAL = 60 * 60 * 4      # 4 hours

    last_momentum_check = 0
    last_trend_check = 0
    last_daily_log_date = None
    day_start_equity = get_account_equity()

    log.info(f"Starting equity: ${day_start_equity:.2f}. Bot is running.")

    try:
        while True:
            now = time.time()
            equity = get_account_equity()

            if not guard.update(equity):
                log.warning("Circuit breaker active - sleeping 60s before retry")
                time.sleep(60)
                continue

            today = datetime.now(timezone.utc).date()
            if last_daily_log_date != today and today > (last_daily_log_date or today):
                log_daily_pnl(day_start_equity, equity)
                day_start_equity = equity
                last_daily_log_date = today

            if now - last_momentum_check >= MOMENTUM_INTERVAL:
                log.info("Checking BTCUSD momentum...")
                check_momentum(config.INSTRUMENTS["BTC_EQUIVALENT"], equity, corr, trailing_stops)
                last_momentum_check = now

            if now - last_trend_check >= TREND_INTERVAL:
                log.info("Checking XAUUSD trend...")
                check_trend(config.INSTRUMENTS["GLD_EQUIVALENT"], equity, corr, trailing_stops)
                last_trend_check = now

            time.sleep(30)

    except KeyboardInterrupt:
        log.info("Bot stopped by user (Ctrl+C).")
    finally:
        mt5.shutdown()
        log.info("MT5 connection closed.")


if __name__ == "__main__":
    main()

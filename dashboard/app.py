"""
dashboard/app.py - Flask backend for the trading bot dashboard.

Serves a single-page dashboard and JSON endpoints that pull:
  - live account equity/balance and open positions from MT5
  - trade history and daily P&L from the CSV logs the bot writes

Runs its own MT5 connection (read-only usage) so it can run alongside
the bot without interfering. Start it with:
    python run_dashboard.py
then open http://127.0.0.1:5000 in your browser.
"""

import os
import csv
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template
import MetaTrader5 as mt5

import config

app = Flask(__name__)

TRADES_CSV = "trades.csv"
DAILY_PNL_CSV = "daily_pnl.csv"

_mt5_ready = False


def ensure_mt5():
    """Initialize MT5 once; reused across requests. Returns True if connected."""
    global _mt5_ready
    if _mt5_ready:
        # verify still alive
        if mt5.account_info() is not None:
            return True
        _mt5_ready = False

    ok = mt5.initialize(
        login=config.MT5_LOGIN,
        password=config.MT5_PASSWORD,
        server=config.MT5_SERVER,
    )
    if not ok:
        # fall back to attaching to an already-running terminal
        ok = mt5.initialize()

    _mt5_ready = ok and mt5.account_info() is not None
    return _mt5_ready


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/account")
def api_account():
    """Live account snapshot: balance, equity, profit, margin."""
    if not ensure_mt5():
        return jsonify({"connected": False})

    info = mt5.account_info()
    if info is None:
        return jsonify({"connected": False})

    return jsonify({
        "connected": True,
        "login": info.login,
        "server": info.server,
        "currency": info.currency,
        "balance": round(info.balance, 2),
        "equity": round(info.equity, 2),
        "profit": round(info.profit, 2),
        "margin": round(info.margin, 2),
        "margin_free": round(info.margin_free, 2),
        "updated": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
    })


@app.route("/api/positions")
def api_positions():
    """Currently open positions with live unrealized P&L."""
    if not ensure_mt5():
        return jsonify({"connected": False, "positions": []})

    positions = mt5.positions_get()
    if positions is None:
        return jsonify({"connected": True, "positions": []})

    result = []
    for p in positions:
        result.append({
            "symbol": p.symbol,
            "direction": "LONG" if p.type == mt5.POSITION_TYPE_BUY else "SHORT",
            "volume": p.volume,
            "entry_price": round(p.price_open, 2),
            "current_price": round(p.price_current, 2),
            "sl": round(p.sl, 2) if p.sl else None,
            "profit": round(p.profit, 2),
        })

    return jsonify({"connected": True, "positions": result})


def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


@app.route("/api/trades")
def api_trades():
    """Full trade history from the CSV log, plus summary stats."""
    rows = _read_csv(TRADES_CSV)

    # Only completed trades (those with a profit_loss value) count for stats
    completed = [r for r in rows if r.get("profit_loss") not in (None, "", "None")]
    parsed = []
    for r in completed:
        try:
            parsed.append(float(r["profit_loss"]))
        except (ValueError, KeyError):
            pass

    wins = [p for p in parsed if p > 0]
    losses = [p for p in parsed if p <= 0]

    stats = {
        "total_trades": len(parsed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(parsed) * 100, 1) if parsed else 0,
        "total_pnl": round(sum(parsed), 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
    }

    # Return most recent trades first for the table
    return jsonify({"trades": list(reversed(rows)), "stats": stats})


@app.route("/api/equity_curve")
def api_equity_curve():
    """Daily equity history from the daily_pnl CSV, for charting."""
    rows = _read_csv(DAILY_PNL_CSV)
    points = []
    for r in rows:
        try:
            points.append({
                "date": r["date"],
                "equity": float(r["ending_equity"]),
                "daily_pnl": float(r["daily_pnl"]),
            })
        except (ValueError, KeyError):
            pass
    return jsonify({"points": points})

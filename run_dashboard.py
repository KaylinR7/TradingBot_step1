"""
Run the trading bot dashboard.

Make sure MT5 is open and logged in, then run:
    python run_dashboard.py

Open http://127.0.0.1:5000 in your browser.
The dashboard reads live data from MT5 and the bot's CSV logs, and
refreshes every 5 seconds. It runs independently of the bot, so you can
have both running at the same time.
"""

from dashboard.app import app

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)

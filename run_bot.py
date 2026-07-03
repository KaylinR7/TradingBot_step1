"""
Run the live/paper trading bot.

Make sure:
  1. MT5 terminal is open and logged into your demo account
  2. .env has your correct demo credentials
  3. "Algo Trading" button is enabled in the MT5 toolbar (green)

Then run:
    python run_bot.py

Stop it any time with Ctrl+C.
"""

from bot.main import main

if __name__ == "__main__":
    main()

# TradingBot

Multi-instrument algo trading bot on MetaTrader 5 (IC Markets demo account).

## Step 1 setup

1. Install MT5 terminal, log into your IC Markets demo account, leave it running.
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in your demo login/password/server.
4. In the MT5 terminal's Market Watch, right-click -> "Show All" and confirm the
   symbol names match what's in `config.py` (`US500`, `NAS100`, `BTCUSD`,
   `XAUUSD`, `USOIL`). Some brokers suffix these differently
   (e.g. `US500Cash`, `BTCUSD.a`) — update `config.py` if so.
5. Run: `python test_connection.py`

You should see your account balance/equity and a live bid/ask for each
instrument. If any instrument shows `[MISSING]`, fix the symbol name in
`config.py` and rerun.

## Project structure (coming next steps)

```
bot/
  strategies/
    mean_reversion.py     # US500, NAS100
    momentum_breakout.py  # BTCUSD
    trend_following.py    # XAUUSD, USOIL
  risk_manager.py         # ATR-based position sizing, stop losses
  portfolio.py
  main.py
config.py
test_connection.py
```

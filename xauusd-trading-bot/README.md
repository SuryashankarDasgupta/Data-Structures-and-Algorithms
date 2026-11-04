# XAUUSD Trading Bot (TradingView → webhook → broker)

A risk-managed gold (XAUUSD) trading setup:

| Part | File | What it does |
|---|---|---|
| **Strategy** | `pine/xauusd_trend_pullback.pine` | TradingView Pine v5 strategy: backtest in Strategy Tester, fire webhook alerts |
| **Bridge** | `bridge/` | Receives alerts, re-checks risk, places orders (paper by default, OANDA optional), journals everything |
| **Backtester** | `backtest/` | Same rules in Python/pandas, runs on any OHLC CSV (e.g. TradingView export) |
| **Tests** | `tests/` | 36 unit/integration tests: `python -m unittest discover -s tests -t .` |

> ⚠️ **Read the results section before using real money.** With default settings this strategy
> **lost money** on real 2024–2026 gold data. This is a framework for testing ideas safely, not a money machine.

---

## Strategy rules

* **Trend:** EMA21 > EMA50 > EMA200 and close > EMA200 (longs; mirrored for shorts), ADX(14) ≥ 20
* **Entry trigger:** bar pulls back to EMA21 and closes back on the trend side with a trend-coloured candle
* **Stop:** 1.5 × ATR(14), fixed at signal time · **Target:** 2R
* **Size:** `equity × 0.5% ÷ stop distance` ounces, capped at 100 oz
* **Exits:** stop/target, close crossing EMA200 against the trade, flat Friday 20:00 UTC
* **Guards:** entries only 07:00–20:00 UTC, max 2% intraday loss, max 6 fills/day

## 1. Backtest in TradingView

1. Open a chart of **`OANDA:XAUUSD`** (or `FOREXCOM:XAUUSD`), timeframe **1h** to start.
2. Pine Editor → paste `pine/xauusd_trend_pullback.pine` → **Add to chart**.
3. Open **Strategy Tester** to see trades, net profit, drawdown, profit factor.
4. Change inputs (gear icon) to explore. Note that tuning until the past looks good (*curve fitting*) usually fails live.
   Check any change on a period you did not tune on.

TradingView XAUUSD quantity = **ounces** (1 standard lot = 100 oz). Spread is modelled as $0.15/oz per side.

## 2. Paper trade with webhooks

```bash
cd xauusd-trading-bot
cp .env.example .env            # set WEBHOOK_SECRET (>=16 chars)
set -a; . ./.env; set +a
python -m bridge.server         # listens on :8080
```

TradingView only posts to **ports 80/443 over the public internet**, so expose the bridge with e.g.
`cloudflared tunnel --url http://localhost:8080` or a small VPS behind Caddy/nginx with HTTPS.
Webhooks need a paid TradingView plan.

Create the alert in TradingView: **Alerts → Create**:

* **Condition:** `XAUUSD Trend Pullback (risk-managed)` → *Order fills only*
* **Webhook URL:** `https://<your-host>/webhook`
* **Message** (exactly, with your secret):

```json
{"secret":"YOUR_WEBHOOK_SECRET","price":{{strategy.order.price}},"signal":{{strategy.order.alert_message}}}
```

The secret lives only in the alert, not in the script. Check the bridge:

```bash
curl localhost:8080/status          # balance, open position, entries today
python -m bridge.report             # daily review (P&L, orders, rejected alerts)
touch KILL_SWITCH                   # instantly block new entries (closes still work)
```

### What the bridge enforces (even if Pine inputs are wrong)

* shared-secret auth (constant-time compare), optional IP allowlist, 16 KB body limit
* symbol whitelist, required stop on every entry (no unprotected trades)
* stale-alert rejection (older than bar close + 120 s), duplicate-alert suppression
* one position at a time, max trades/day, daily-loss lock-out, kill-switch file
* size capped by both `MAX_UNITS` and `MAX_RISK_PCT` of balance
* single writer: one order at a time, and **no blind retries**. On a network error it checks the
  position and marks the order `unknown` for review rather than risking a double fill.
* every alert, decision and order is journaled in SQLite (`journal.sqlite3`)

## 3. Broker execution (OANDA practice)

TradingView cannot place orders on your behalf by itself, so the bridge sends them to a broker. OANDA is supported
via its v20 REST API (`XAU_USD`). Stops are attached **on fill** so positions are protected immediately.

```bash
BROKER=oanda OANDA_ENV=practice OANDA_ACCOUNT_ID=... OANDA_TOKEN=... python -m bridge.server
```

Live trading is refused unless `OANDA_ENV=live` **and** `ALLOW_LIVE_TRADING=yes-i-understand-the-risk`.
Check that OANDA (and leveraged gold CFDs) are available and legal where you live. In several countries,
including India, retail trading of offshore forex/CFDs is restricted.

Other brokers (MT5, IBKR, etc.) can be added by implementing the 4-method `Broker` protocol in `bridge/brokers.py`.

## 4. Offline backtest (Python)

```bash
pip install -r requirements.txt
python -m backtest.run data.csv --trades trades.csv       # TradingView "Export chart data" CSV works
python -m backtest.run data.csv --rr 3 --adx-min 25 --use-session false
python -m backtest.run --synthetic                        # smoke test only (fake data)
```

The fill model mirrors TradingView's: orders fill at next bar open, stop/target from fill price,
TradingView's intrabar high/low ordering, gaps fill at the open. Expect small differences from
EMA seeding and data-vendor prices.

## Results so far (be honest with yourself)

Real hourly COMEX gold futures (GC=F, Jun 2024 → Nov 2026, ~13.7k bars), $10k start, default settings:

| Variant | Return | Trades | Win % | Profit factor | Max DD |
|---|---|---|---|---|---|
| Default | **−3.8%** | 192 | 33.3 | 0.93 | −9.2% |
| No session filter | −4.8% | 264 | 33.3 | 0.93 | −8.5% |
| RR 3 | −8.0% | 181 | 26.5 | 0.84 | −11.2% |
| ADX ≥ 25 | −2.6% | 143 | 33.6 | 0.93 | −7.0% |

Over the same period gold itself rose **~75%** ($2,327 → $4,070), so buying and holding beat this strategy by a wide
margin. The risk controls work (drawdowns are small and controlled), but **this strategy has no proven edge**.
Use the framework to test your own ideas: backtest → walk-forward on unseen data → weeks of paper trading →
tiny live size, and only if each step holds up.

*Educational software. Not financial advice. Leveraged gold trading can lose more than your deposit.*

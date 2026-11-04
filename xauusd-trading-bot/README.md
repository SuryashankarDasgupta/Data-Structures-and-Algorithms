# XAUUSD Trading Bot (TradingView → webhook → broker)

A research-backed, risk-managed gold (XAUUSD) trend-following system:

| Part | File | What it does |
|---|---|---|
| **Strategy** | `pine/xauusd_daily_trend.pine` | TradingView Pine v5 strategy for the **daily** chart: backtest in Strategy Tester, send webhook alerts |
| **Bridge** | `bridge/` | Receives alerts, re-checks risk, places orders and trails the broker stop (paper by default, OANDA optional), journals everything |
| **Backtester** | `backtest/` | The same rules in Python, run on any OHLC CSV (e.g. a TradingView export) |
| **News calendar** | `data/high_impact_usd.csv` | FOMC, NFP and CPI release dates 2015 → latest schedule (official sources) |
| **Tests** | `tests/` | 64 tests: `python -m unittest discover -s tests -t .` |

> **Bottom line:** over 2000–2026 this made **3.7%/yr with a −8.8% worst drawdown** at 1% risk per trade.
> Buying and holding gold made 10.9%/yr but fell **−44%** on the way. The bot earns about **1.7× more return per unit of
> drawdown**, but it does **not** beat buy-and-hold on raw return. Nothing here turns $70 into $13k.

---

## Strategy rules

Use on a **daily** chart (`OANDA:XAUUSD`, 1D).

* **Entry (long):** EMA20 > EMA200 **and** close > EMA20 → buy at the next open
* **Initial stop:** signal close − 2 × ATR(14)
* **Trailing stop:** highest high since entry − 2.5 × ATR(14), recomputed each daily close, **only ever moves up**
* **Trend exit:** EMA20 falls below EMA200 → sell at the next open
* **Size:** `equity × risk% ÷ (2 × ATR)` ounces, capped at 1× equity notional (no leverage), whole ounces
* **Shorts:** off by default (they lowered returns and raised drawdown on gold, see below)
* **High-impact news:** no new entry when an FOMC decision, NFP or CPI release falls on the next trading session (see [News](#high-impact-news))

There is no fixed profit target. Trend following makes its money from a few large winners (win rate ~42%, average
winner ≈ 2.5× average loser), so cutting winners short hurts.

## Research: what actually works on gold

I checked what "profitable gold traders" use and then tested each idea on real data. **Rule:** tune on one period
and judge only on a period the strategy has never seen. Data: COMEX gold futures (GC=F), daily 2000–2026 (6,570 bars)
and hourly Jun 2024–Nov 2026 (13.7k bars). Costs: $0.30/oz round trip.

**Sources:** most "profitable gold EA / signal" claims online are vendor marketing with unaudited, often
implausible stats (e.g. [MQL5 listings](https://www.mql5.com/en/signals/2387828),
[London-breakout EA write-ups](https://www.mql5.com/en/blogs/post/767326)). The ideas with real evidence behind them:

* **Time-series momentum / trend following** works across futures including commodities
  (Moskowitz, Ooi & Pedersen, 2012).
* **Gold's overnight effect:** overnight returns are positive and daytime returns negative
  ([Blose, Gondhalekar & Kort 2018](https://ideas.repec.org/a/spr/jecfin/v42y2018i3d10.1007_s12197-017-9403-0.html);
  [CBS thesis on hat-shaped seasonality](https://research.cbs.dk/en/studentProjects/gold-price-dynamics-around-the-clock/)).
* **Prop-firm-style risk rules:** ~1% risk per trade, daily loss caps
  ([example](https://www.mql5.com/en/blogs/post/768516)).

**Results (tuning period → unseen period, annual return / max drawdown):**

| Idea | Tuning period | Unseen period | Verdict |
|---|---|---|---|
| Hourly EMA pullback (old version of this bot) | +6.4% / −3.8% | **−6.2%** / −10.9% | ❌ failed |
| Hourly pullback + daily trend filter | +8.4% / −3.7% | **−3.9%** / −7.5% | ❌ failed |
| London open breakout of Asian range | **−12.9%** / −20% | +13.4% / −2.5% | ❌ flips sign = noise |
| Overnight long (22→07 UTC) | +3.0% / −6.1% | **−1.4%** / −4.2% | ❌ effect gone in 2025–26 |
| Daily Donchian breakouts (Turtle-style) | +1.5–2.2% | +2.4–3.7% | ✅ works, larger drawdowns |
| **Daily EMA trend + ATR trailing stop** | **+4.2% / −7.8%** | **+2.6% / −6.0%** | ✅ **most robust** |

Robustness check on the winner: **80 out of 80** parameter combinations (EMA 20/50/100 × 100/200, trail 2.5–4 ATR,
stop 2–3 ATR, long-only or long+short) were profitable in the unseen 2016–2026 period, median profit factor 1.7.
Long-only beat long+short in both periods. I picked the best setting on the tuning period, and its unseen-period
result was in line with its neighbours, so it isn't a lucky outlier. A "drawdown brake" (halving risk after a 5–10% drawdown)
did **not** improve results and was left out.

## Results with default settings (1% risk, $25k start)

| Period | Bot annual return | Bot max DD | Profit factor | Trades | Gold annual return | Gold max DD |
|---|---|---|---|---|---|---|
| 2000–2015 (tuning) | 4.2% | −7.8% | 1.81 | 169 | 9.2% | −44.4% |
| 2016–2026 (unseen) | 2.6% | −6.2% | 1.84 | 99 | 13.1% | −26.7% |
| 2000–2026 | 3.7% | −8.8% | 1.87 | 277 | 10.9% | −44.4% |

Year by year (bot % vs gold %): 2013 **−2.0 vs −28**, 2014 −1.6 vs −1, 2015 −1.9 vs −10, 2019 +10.3 vs +19,
2020 +6.4 vs +25, 2024 +6.8 vs +27, 2025 +11.8 vs +64. The bot keeps losses small in bear years and captures part of
each bull run. It's in the market about 48% of the time, so idle cash could also earn interest.

### Last 10 years (4 Nov 2016 → 4 Nov 2026), default settings incl. news filter

| | 1% risk (default) | 2% risk | Gold buy & hold |
|---|---|---|---|
| $25,000 becomes | **$32,436** (+29.7%) | $41,710 (+66.8%) | ~$78,150 (+212.6%) |
| Annual return | 2.64% | 5.25% | 12.07% |
| Max drawdown | **−6.2%** | −12.2% | −26.7% |
| Trades / win rate | 98 / 39.8% | 98 / 40.8% | – |
| Profit factor | 1.83 | 1.89 | – |
| Avg win / avg loss | +$449 / −$162 | +$958 / −$350 | – |
| Best / worst trade | +$1,846 / −$392 | +$4,671 / −$1,176 | – |

| Year | 2016* | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Bot (1% risk) | −1.1 | +1.1 | −2.6 | +10.5 | +5.0 | −2.9 | +0.1 | +3.1 | +6.8 | +10.2 | −2.7 |
| Gold | −11.8 | +13.6 | −2.1 | +18.9 | +24.7 | −3.5 | −0.1 | +13.4 | +27.5 | +64.4 | −6.2 |

\* partial years. The worst losing year was −2.9%. Gold had an exceptional decade, which a trend system with
small, risk-capped positions captures only partly.

### Profitability and drawdown by period (last 10 years, default settings)

Equity marked at daily closes, $25k start on 4 Nov 2016. "Flat" = no open position, so no gain or loss.

| | Daily | Weekly | Monthly | Yearly |
|---|---|---|---|---|
| Periods | 2,514 | 523 | 121 | 11 |
| **Profitable** | **29.4%** | **33.3%** | **43.0%** | **63.6%** |
| Losing | 24.8% | 30.4% | 38.0% | 36.4% |
| Flat (out of market) | 45.8% | 36.3% | 19.0% | 0% |
| Profitable when in a trade | 54.3% | 52.3% | 53.1% | 63.6% |
| Average return | +0.01% | +0.05% | +0.22% | +2.5% |
| Best period | +2.25% | +2.62% | +4.76% | +10.49% |
| Worst period | −1.26% | −1.29% | −1.83% | −2.91% |
| Avg drawdown within period | −0.06% | −0.26% | −0.76% | −3.34% |
| **Worst drawdown within period** | **−1.26%** | **−1.68%** | **−2.02%** | **−5.94%** |
| Gold buy & hold: profitable | 53.6% | 56.4% | 57.0% | 54.5% |
| Gold buy & hold: worst drawdown | −10.8% | −10.8% | −17.6% | −26.7% |

Reproduce with `python -m backtest.run gold_daily.csv --start 2016-11-04 --periods`. Note: `--start` warms the
indicators up on all earlier data, so the account size and open positions at the start date can differ slightly
from a run that begins in 2015.

### The risk dial: you choose the drawdown

Return and drawdown scale together. Pick the drawdown you can live with:

| Risk per trade | Annual return | Max drawdown (2000–2026) |
|---|---|---|
| 0.5% | 1.8% | −4.2% |
| **1.0% (default)** | **3.7%** | **−8.8%** |
| 2.0% | 6.4% | −17.5% |

Expect live drawdowns to be **worse** than any backtest. Settings above 2% aren't recommended.

## High-impact news

Gold reacts most to three scheduled US releases: **FOMC rate decisions** (14:00 New York), **Non-Farm Payrolls**
and **CPI** (both 08:30 New York). The calendar in `data/high_impact_usd.csv` comes from official sources:
[federalreserve.gov](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) meeting calendars (including the
emergency cuts of 3 and 15 March 2020) and the BLS release archives for
[NFP](https://www.bls.gov/bls/news-release/empsit.htm) and [CPI](https://www.bls.gov/bls/news-release/cpi.htm).
It holds 89 FOMC decisions (2016+), 142 NFP and 141 CPI releases (2015+). October 2025 is missing because those
reports weren't published during the government shutdown.

**How much do they move gold?** (daily bars, Nov 2016 – Nov 2026)

| Day type | Days | Avg close-to-close move | Avg high-low range |
|---|---|---|---|
| NFP | 115 | 0.86% | 1.58% |
| CPI | 111 | 0.74% | 1.48% |
| FOMC | 74 | 0.54% | 1.67% |
| No release | 2,207 | 0.75% | 1.33% |

Release days have **10–25% wider intraday ranges** but barely larger daily closes: the spike mostly reverses within
the day. That matters for stops, much less for a strategy holding for weeks.

**Options** (*News handling* input in Pine, `news_mode` in the backtester):

| Mode | What it does | 10-yr annual return | Max DD | Trades |
|---|---|---|---|---|
| Off | ignore news | 2.77% | −6.2% | 100 |
| **Block entries (default)** | no new entry if a release is on the next session | 2.64% | −6.2% | 98 |
| Tighten stop | block + raise the stop to close − 1×ATR before a release | 2.75% | −6.5% | 124 |
| Go flat | block + close positions before every release | 2.14% | −8.1% | 224 |

None of them improves the backtest: stepping aside costs fees and misses moves, and the 2–2.5×ATR stops already
absorb most news spikes. **Block entries** is the default as cheap insurance (−0.13%/yr, 2 trades in 10 years,
which is within noise). It protects against what a backtest can't model: spreads widening 5–10× and fills slipping
right at release time. Choose *Off* if you prefer the best backtest number.

**The bridge** also checks the calendar using exact release times (DST handled) and rejects new entries from
`NEWS_BLOCK_HOURS` (24) before a release to `NEWS_BLOCK_AFTER_MIN` (30) after it. Closes and stop updates are
never blocked. `/status` shows the next events and warns if the calendar is stale.

**Keeping the calendar current:**

```bash
python -m bridge.news            # show next events, warn if no NFP/CPI in the next 3 weeks
python -m bridge.news update     # add this week's FOMC/NFP/CPI from the ForexFactory feed (optional)
python -m bridge.news pine       # copy the CSV dates into the Pine script, then re-paste it in TradingView
```

You can also add rows to the CSV by hand from the Fed and BLS schedules (`date,event,description`), or put
dates in the Pine input *Extra event dates* (`YYYYMMDD,YYYYMMDD`).

## 1. Backtest in TradingView

1. Open **`OANDA:XAUUSD`**, timeframe **1D**.
2. Pine Editor → paste `pine/xauusd_daily_trend.pine` → **Add to chart** → **Strategy Tester**.
3. Change *Properties → Initial capital* to your account size. At gold ≈ $4,000 with daily-ATR stops, 1% risk needs
   roughly **$12k+** to trade even 1 oz. Below that, either use a broker that allows fractional ounces (set
   *Quantity step*) or accept that it will skip trades.

## 2. Paper trade with webhooks

```bash
cd xauusd-trading-bot
cp .env.example .env            # set WEBHOOK_SECRET (>=16 chars)
set -a; . ./.env; set +a
python -m bridge.server         # listens on :8080
```

TradingView only posts to **ports 80/443 over the public internet**: use `cloudflared tunnel --url http://localhost:8080`
or a VPS behind Caddy/nginx with HTTPS. Webhooks need a paid TradingView plan.

Create the alert in TradingView: **Alerts → Create**:

* **Condition:** `XAUUSD Daily Trend (risk-managed)` → *Order fills and alert() function calls*
* **Webhook URL:** `https://<your-host>/webhook`
* **Message** (exactly, with your secret):

```json
{"secret":"YOUR_WEBHOOK_SECRET","price":{{strategy.order.price}},"signal":{{strategy.order.alert_message}}}
```

**Trailing the broker stop (recommended):** put the same secret in the script input *Secret for stop-update alerts*.
At each daily close where the stop moves, the script sends an `update_stop` alert and the bridge moves the broker's
stop (tighten-only). Without it, the broker keeps the initial stop and the position is closed when TradingView's stop
fill alert arrives. If you use this, keep the script private.

```bash
curl localhost:8080/status          # balance, open position, entries today
python -m bridge.report             # daily review (P&L, orders, rejected alerts)
touch KILL_SWITCH                   # instantly block new entries (closes and stop updates still work)
```

### What the bridge enforces (even if Pine inputs are wrong)

* shared-secret auth (constant-time compare), optional IP allowlist, 16 KB body limit
* symbol whitelist, required stop on every entry (no unprotected trades)
* stop updates are **tighten-only** and refused if on the wrong side of price
* stale-alert rejection, duplicate-alert suppression, one position at a time
* max trades/day, daily-loss lock-out, kill-switch file
* size capped by `MAX_UNITS`, `MAX_RISK_PCT` of balance **and** `MAX_LEVERAGE` (notional ÷ balance, default 1 = no leverage)
* one order at a time, **no blind retries**: on a network error it checks the position and marks the order `unknown`
* every alert, decision and order journaled in SQLite (`journal.sqlite3`)

## 3. Broker execution (OANDA practice)

TradingView can't place orders by itself, so the bridge sends them to OANDA's v20 REST API (`XAU_USD`). The stop is
attached **on fill** and trailed via `update_stop`.

```bash
BROKER=oanda OANDA_ENV=practice OANDA_ACCOUNT_ID=... OANDA_TOKEN=... python -m bridge.server
```

Live trading is refused unless `OANDA_ENV=live` **and** `ALLOW_LIVE_TRADING=yes-i-understand-the-risk`.
Check that the broker and leveraged gold CFDs are legal where you live. In several countries, including India, retail
trading of offshore forex/CFDs is restricted. Other brokers can be added by implementing the 5-method `Broker`
protocol in `bridge/brokers.py`.

## 4. Offline backtest (Python)

```bash
pip install -r requirements.txt
python -m backtest.run gold_daily.csv --trades trades.csv     # TradingView "Export chart data" CSV works
python -m backtest.run gold_daily.csv --risk-pct 2 --trail-atr 3
python -m backtest.run gold_daily.csv --allow-shorts true
python -m backtest.run --synthetic                            # smoke test only (fake data)
```

## Caveats

* GC=F is continuous front-month futures, which includes small roll gaps. Spot XAUUSD will differ slightly.
* 26 years is one history. Gold had a long secular bull market, which favours long-only trend following.
  A decade-long sideways market would mean long flat or slightly negative periods (as in 2012–2018).
* Backtests exclude swap/financing costs on CFDs, which reduce returns on longer holds.
* The news calendar starts in 2015 (FOMC 2016), so news filtering only affects backtests from then on.

*Educational software. Not financial advice. Leveraged gold trading can lose more than your deposit.*

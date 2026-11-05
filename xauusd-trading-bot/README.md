# XAUUSD + Crypto Trend Bot (24/7 scanner · TradingView webhooks · broker bridge)

A research-backed, risk-managed daily trend-following system. It started as a gold (XAUUSD) bot and now runs a
**multi-market portfolio (gold + BTC + ETH by default)** with a scanner that checks every market around the clock.

| Part | File | What it does |
|---|---|---|
| **24/7 scanner** | `bridge/scanner.py`, `bridge/feeds.py`, `bridge/live_strategy.py` | Checks every market every 5 min, acts on completed daily bars: entries, trailing stops, exits |
| **Strategy (TradingView)** | `pine/xauusd_daily_trend.pine` | Pine v5 strategy for the gold **daily** chart: backtest in Strategy Tester, send webhook alerts |
| **Bridge** | `bridge/` | Receives alerts / scanner signals, re-checks risk, places orders (paper by default, OANDA optional), journals everything |
| **Backtesters** | `backtest/` | Single-market (`backtest.run`) and multi-market portfolio (`backtest.portfolio_run`) with the same rules |
| **Data** | `backtest/download.py`, `data/high_impact_usd.csv` | 20+ years of daily prices (forex closes repaired); FOMC/NFP/CPI calendar |
| **Tests** | `tests/` | 107 tests: `python -m unittest discover -s tests -t .` |

> **Bottom line (20-year backtest, Nov 2006 → Nov 2026, $25k start, default 1% risk per position, 20-day breakout
> entry confirmed by MACD):** gold + BTC + ETH turned **$25,000 into $134,077: 8.8%/yr with a −8.1% worst drawdown**,
> profitable in 17 of 21 calendar years, average **+0.66R per trade**, 51% winners. At 2% risk: $591,985, 17.2%/yr, −15.6%.
> (The earlier EMA-trend entry: 9.5%/yr, −10.5%, +0.46R per trade.) Gold alone at 2% risk: 5.4%/yr, −17.7%.
> **Forex lost heavily after 2016** (−5.5%/yr, −57% drawdown) and is off by default. Crypto history only starts in 2014-2017, so the
> first 8 years are gold only, and most of the crypto profit came from the 2016-2021 bull markets.
> Nothing here turns $70 into $13k, or makes 30% a week.

---

## Multi-market portfolio and 24/7 scanner

### Research: which markets?

Same daily rules on every market, **no per-market tuning**. Decisions were made on 2006-2015 (tuning) and checked on
2016-2026 (unseen), as for gold. Data: Yahoo Finance daily bars; forex closes repaired (Yahoo's forex "close" is a
snapshot just after the open, so each close is replaced by the next bar's open), costs 0.01-0.015% per side for
forex/gold and 0.10% for crypto.

| Market group (1% risk per position) | 2006-2015 (tuning) | 2016-2026 (unseen) | Verdict |
|---|---|---|---|
| 12 forex pairs (majors + crosses), long/short | +5.5%/yr, −26% DD | **−5.5%/yr, −57% DD** | ❌ excluded |
| Gold (long only) | +2.8%/yr, −8% DD | +3.3%/yr, −7% DD | ✅ |
| BTC, ETH (long only) | profitable, PF 2.3-3.8 | profitable, PF 1.3-1.4 | ✅ |
| 6 other coins | profitable | mixed (PF 0.9-1.7) | optional (survivorship bias) |
| Shorting crypto or gold | – | lower returns or losses | ❌ off |

Forex made money in 2006-2015 but with deep drawdowns (return/drawdown 0.21 vs gold's 0.35), then collapsed in
2016-2026, which matches the industry record of forex trend profits fading after ~2010. **Be aware:** dropping forex
partly uses hindsight from the 2016-2026 period, so the default portfolio's "unseen" figures are somewhat flattering.
Picking today's top coins for a backtest flatters crypto (**survivorship bias**: many 2017-era coins died).
BTC and ETH, the two largest coins since 2016, are the least affected, so they're the default.

### Strategy families tested (Nov 2026)

Before settling on the entry rule I tested the strategy types most often credited to successful traders, on gold,
BTC and ETH, tuning on 2006-2020 and judging on 2021-2026 (same costs, 1% risk per trade). What the evidence said
going in: trend following/breakouts have the longest record; published tests of volatility-breakout and Bollinger
systems mostly fail to beat buy-and-hold; FOMC studies mostly find reversals, not drift, after announcements.

| Family | Rule tested | Result on unseen data | Verdict |
|---|---|---|---|
| **Breakout (swing/position)** | close > previous 20-day high, exit by 2.5×ATR trailing stop | better than trend in tuning *and* unseen; 83 of 90 nearby settings also better | ✅ **new default** |
| Trend (previous default) | EMA20 > EMA200 and close > EMA20 | solid but lower return per drawdown | available (`ENTRY_MODE=trend`) |
| Turtle 20/10, 55/20 | Donchian breakout and channel exit | biggest profit per trade (+1.4 to +2.5R), but drawdowns −19% to −28% | ❌ too deep |
| Swing pullback | RSI(2) < 10 in an uptrend, exit above EMA5 | ≈ 0%/yr | ❌ |
| Day trading | Larry Williams volatility breakout | lost money on every market (−1% to −8%/yr) | ❌ |
| News-based | follow / fade the FOMC, NFP, CPI day move for 5 days | −1.1% / +1.0%/yr, inconsistent | ❌ |
| Long + short | shorts allowed | slightly better on crypto, worse on gold | ❌ off |
| Exit tweaks | breakeven at 1R, 3R/5R targets, 2.0-3.5 ATR trails | no consistent gain, results flip between markets | ❌ |
| Two strategies at once | trend + Turtle on the same market | no better at equal risk; needs two positions per market | ❌ |

**Indicator filters (TradingView-style), tested on top of the breakout:** RSI(14) above 50/60 or below 70/80,
Bollinger Bands (close above the upper band, squeeze, no squeeze), EMA/SMA filters (close above EMA200, EMA20 > EMA50,
SMA50 > SMA200, close above SMA50), MACD (above signal, above zero), ADX (above/below 20/25), Stochastic, volatility
regime, and indicator exits (close below EMA20/SMA50/Bollinger middle, RSI < 40, MACD cross). Of 25 rules, only
**MACD above its signal line** improved both the tuning and the unseen period, and 6 of 8 nearby MACD settings did
too, so it is now on by default (`MACD_FILTER=on`, standard 12/26/9). The gain is modest: same return, slightly smaller
drawdown, profit factor 2.48 → 2.65, longest time below a high ~3.1 → ~1.6 years. With 25 rules tested, one could pass
by luck; the neighbour check makes that less likely, not impossible. RSI > 50 changes nothing (a 20-day breakout
almost always has RSI above 50); RSI < 70, Bollinger squeezes, ADX and Stochastic filters made results worse.

**Candle structure, tested on top of breakout + MACD (Nov 2026):** none adopted.

| Candle rule | Tuning (2006-20) | Unseen (2021-26) | Profit per trade | Verdict |
|---|---|---|---|---|
| Current (no candle rule) | 1.29 | 1.18 | +0.65R | baseline |
| Breakout candle closes in top 25% / top half of its range | 1.53 / 1.41 | 0.90 / 1.11 | +0.63R / +0.64R | ❌ worse unseen |
| Big body (≥ 50% of range) / no long upper wick | 1.23 / 1.40 | 1.09 / 0.90 | +0.65R / +0.63R | ❌ |
| Bullish candle / not a doji / previous candle bullish | 1.21 / 1.28 / 1.41 | 1.18 / 1.18 / 1.01 | ≈ | ❌ no gain |
| Wide-range bar (≥ 1.2 ATR) / no blow-off bar (< 2 ATR) | 1.18 / 0.86 | 1.21 / 0.80 | +0.65R / +0.55R | ❌ |
| Entry patterns in an uptrend: bullish engulfing, hammer/pin bar, hammer at EMA20, inside-bar breakout, three white soldiers, morning star | 0.25-0.86 | −0.18-1.22 | +0.05 to +0.83R | ❌ all weaker than breakouts in tuning |
| Exits: bearish engulfing, shooting star, evening star, weak close | 0.87-1.06 | 1.18-1.40 | +0.37 to +0.60R | ❌ worse in tuning, and they cut winners short |

(Numbers are return ÷ max drawdown, gold + BTC + ETH, 1% risk.) Candle filters that looked better in 2006-2020 got worse
in 2021-2026, the typical sign of fitting noise. Candle exits sell winners early, which lowers profit per trade.

On **gold alone** the trend entry still did better over 2000-2026, so the gold TradingView script keeps *Trend* as
its default (Breakout is an input). The breakout default applies to the multi-market portfolio and scanner.

### 20-year results (fresh $25,000 account opened 4 Nov 2006)

`python -m backtest.portfolio_run prices --risk-pct 1 --periods`

| Portfolio | Entry | Risk/position | $25k becomes | Annual | Max DD | Return/DD | Sharpe | Trades | Win | Avg per trade | Worst trade |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Gold + BTC + ETH (default)** | **breakout + MACD** | **1%** | **$134,077** | **8.8%** | **−8.1%** | **1.08** | | 264 | 51% | **+0.66R** | −1.54R |
| Gold + BTC + ETH | breakout + MACD | 2% | $591,985 | 17.2% | −15.6% | 1.10 | | 264 | 51% | +0.66R | −1.54R |
| Gold + BTC + ETH | breakout | 1% | $133,911 | 8.8% | −8.3% | 1.05 | 1.31 | 274 | 50% | +0.64R | −1.54R |
| Gold + BTC + ETH | breakout | 2% | $589,968 | 17.1% | −16.0% | 1.07 | 1.32 | 274 | 50% | +0.64R | −1.54R |
| Gold + BTC + ETH | trend | 1% | $154,062 | 9.5% | −10.5% | 0.91 | 1.27 | 419 | 44% | +0.46R | −2.05R |
| Gold + BTC + ETH | trend | 2% | $712,564 | 18.2% | −20.0% | 0.91 | 1.26 | 419 | 44% | +0.46R | −2.05R |
| Gold only | trend | 2% | $71,462 | 5.4% | −17.7% | 0.31 | 0.82 | 191 | 44% | | |
| All 21 markets (forex + 8 coins + gold) | trend | 1% | $121,393 | 8.2% | −43.4% | 0.19 | 0.62 | 1,663 | 37% | | |
| Forex only (12 pairs) | trend | 1% | $22,308 | −0.6% | −56.6% | −0.01 | 0.03 | 1,532 | 36% | | |

(R = the amount risked on a trade. Average win +2.0R, average loss −0.71R with the default entry.)

**By sub-period (default):** 2006-2014 (gold only) 2.5%/yr, −4.5% · 2015-2020 16.1%/yr, −5.9% · 2021-2026 10.1%/yr,
−8.1%. Longest time below a previous high: ~1.6 years (Mar 2014 → Oct 2015). Longest run of losing months: 5.

**Year by year (default, 1% risk, %):** 2006 −0.9 · 2007 +9.4 · 2008 +2.3 · 2009 +0.7 · 2010 −0.2 · 2011 +7.7 ·
2012 +2.5 · 2013 −1.7 · 2014 +1.4 · 2015 +7.4 · 2016 +19.6 · 2017 +18.8 · 2018 +0.1 · 2019 +9.5 · 2020 +46.4 ·
2021 +19.8 · 2022 −6.0 · 2023 +27.3 · 2024 +10.2 · 2025 +8.1 · 2026 +4.7 (to 4 Nov)

**Profitability and drawdown by period (default: breakout + MACD, 20 years):**

| | Daily | Weekly | Monthly | Yearly |
|---|---|---|---|---|
| 1% risk: profitable / losing / flat | 21.1 / 18.6 / 60.3% | 28.1 / 24.9 / 47.0% | 43.6 / 36.5 / 19.9% | 81.0 / 19.0 / 0% |
| 1% risk: profitable when in a trade | 53.1% | 53.0% | 54.4% | 81.0% |
| 1% risk: average return | +0.03% | +0.17% | +0.73% | +8.9% |
| 1% risk: best / worst period | +4.7 / −3.3% | +10.5 / −2.9% | +19.1 / −2.6% | +46.4 / −6.0% |
| 1% risk: worst drawdown within a period | −3.3% | −3.5% | −4.8% | −6.8% |
| 2% risk: profitable | 21.1% | 28.2% | 44.0% | 76.2% |
| 2% risk: average return | +0.05% | +0.33% | +1.42% | +18.6% |
| 2% risk: best / worst period | +8.3 / −6.2% | +20.7 / −5.5% | +38.3 / −5.0% | +104.7 / −11.8% |
| 2% risk: worst drawdown within a period | −6.2% | −6.7% | −8.8% | −13.0% |

The breakout entry waits for a fresh 20-day high confirmed by MACD, so it is out of the market more often
(60% of days flat).

### Running the 24/7 scanner

The scanner runs inside the bridge (`SCANNER=on`) or alone (`python -m bridge.scanner`). Every `SCAN_INTERVAL_S`
(300 s) it checks each market in `ALLOWED_SYMBOLS`:

1. **Reconcile:** a position the broker closed (its stop was hit) is forgotten.
2. **Stop watch (paper only):** the live price is checked against the stop; a real broker holds the stop itself.
3. **New daily close:** the rules decide whether to enter, trail the stop, or exit. Crypto bars close at 00:00 UTC
   (24/7), gold and forex at 17:00 New York (24/5).

It trades **daily** bars: checking every 5 minutes means stops and new closes are handled within minutes, not
that it trades more often. Orders go through the same risk checks, duplicate protection and journal as webhooks.
A replay test confirms the live scanner and the portfolio backtest trade on the same days.

```bash
python -m backtest.download --out prices          # 20 years of gold, BTC, ETH (add --all for every market)
python -m backtest.portfolio_run prices --periods # reproduce the results above
python -m bridge.scanner --once                   # one live scan cycle (paper), prints each market's decision
SCANNER=on python -m bridge.server                # bridge + scanner, 24/7
curl localhost:8080/status                        # positions, last scan, per-market state and errors
```

**Data sources:** crypto from Coinbase's public API (no key). Gold and forex from OANDA (`NONFX_FEED=oanda`, needs
`OANDA_TOKEN`) or Yahoo (`NONFX_FEED=yahoo`, unofficial, paper only).
**Brokers:** paper for everything. OANDA for gold/forex only, since OANDA doesn't offer these cryptocurrencies in most
countries. Real crypto execution needs an exchange adapter (not included). Keep crypto in paper until then.
**Don't run both** TradingView alerts and the scanner for the same market: two sources would manage one position.
The scanner leaves positions it didn't open alone.

**Portfolio risk limits** (bridge and backtest use the same values): `RISK_PCT` 1% per position, `MAX_POSITIONS` 4,
`MAX_LEVERAGE` 1× per position, `MAX_GROSS_LEVERAGE` 3× total, plus the existing daily-loss lockout, trade cap,
kill switch and news guard (gold/forex only; crypto is exempt).

**Caveats specific to this section:** 20 years only for gold (crypto from 2014/2017). Forex OHLC was repaired, and
~20% of repaired bars were widened to include the end-of-day price; validate on broker data before live use.
Crypto spot has no funding costs, but perpetual futures and CFDs do (often 5-30%/yr for longs in bull markets),
and these aren't modelled. Crypto can gap 30-40% in a day (March 2020), and stops then fill far below their level.

## Strategy rules (gold, same for every market)

Use on a **daily** chart (`OANDA:XAUUSD`, 1D).

* **Entry (long):** EMA20 > EMA200 **and** close > EMA20 → buy at the next open
* **Initial stop:** signal close − 2 × ATR(14)
* **Trailing stop:** highest high since entry − 2.5 × ATR(14), recomputed each daily close, **only ever moves up**
* **Trend exit:** EMA20 falls below EMA200 → sell at the next open
* **Size:** `equity × 2% ÷ (2 × ATR)` ounces (risk % adjustable), capped at 1× equity notional (no leverage), whole ounces
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

## Results with default settings (2% risk, $25k start)

| Period | Bot annual return | Bot max DD | Profit factor | Trades | Gold annual return | Gold max DD |
|---|---|---|---|---|---|---|
| 2000–2015 (tuning) | 6.9% | −15.1% | 1.67 | 169 | 9.2% | −44.4% |
| 2016–2026 (unseen) | 5.2% | −12.0% | 1.92 | 99 | 13.1% | −26.7% |
| 2000–2026 | 6.4% | −17.5% | 1.78 | 277 | 10.9% | −44.4% |

Year by year (bot % vs gold %): 2013 **−4.2 vs −28**, 2014 −2.9 vs −1, 2015 −3.9 vs −10, 2019 +16.5 vs +19,
2020 +9.9 vs +25, 2024 +14.1 vs +27, 2025 +27.2 vs +64. 8 losing years out of 27, the worst −6.5% (2001). The bot keeps losses small in bear years and captures part of
each bull run. It's in the market about 48% of the time, so idle cash could also earn interest.

### Last 10 years (4 Nov 2016 → 4 Nov 2026), default settings incl. news filter

A fresh $25,000 account opened on 4 Nov 2016 (what a new user would experience). Indicators warm up on daily
data from 1 Jan 2015; no trades before the start date.

| | 2% risk (default) | 1% risk | Gold buy & hold |
|---|---|---|---|
| $25,000 becomes | **$42,770** (+71.1%) | $32,795 (+31.2%) | ~$78,150 (+212.6%) |
| Annual return | **5.52%** | 2.75% | 12.07% |
| Max drawdown | **−12.1%** | −6.2% | −26.7% |
| Trades / win rate | 99 / 40.4% | 99 / 39.4% | – |
| Profit factor | 1.90 | 1.82 | – |
| Avg win / avg loss | +$938 / −$335 | +$443 / −$158 | – |
| Best / worst trade | +$4,671 / −$1,176 | +$1,846 / −$392 | – |
| Longest time below a previous high | 1,329 calendar days (~3.6 years) | 1,329 calendar days | – |

| Year | 2016* | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Bot (2% risk) | −0.9 | +0.5 | −5.2 | +16.2 | +10.1 | −6.2 | +0.3 | +7.0 | +13.5 | +25.7 | −1.5 |
| Bot (1% risk) | −0.5 | +1.0 | −2.5 | +10.4 | +5.0 | −3.0 | +0.1 | +3.2 | +7.2 | +10.6 | −2.7 |
| Gold | −11.8 | +13.6 | −2.1 | +18.9 | +24.7 | −3.5 | −0.1 | +13.4 | +27.5 | +64.4 | −6.2 |

\* partial years. The worst losing year was −6.2% at 2% risk (−3.0% at 1%). Gold had an exceptional decade, which a trend system with
small, risk-capped positions captures only partly.

### Profitability and drawdown by period (last 10 years, default 2% risk)

Equity marked at daily closes, fresh $25k account opened on 4 Nov 2016. "Flat" = no open position, so no gain or loss.

| | Daily | Weekly | Monthly | Yearly |
|---|---|---|---|---|
| Periods | 2,514 | 523 | 121 | 11 |
| **Profitable** | **30.0%** | **34.2%** | **43.8%** | **63.6%** |
| Losing | 25.2% | 30.6% | 38.0% | 36.4% |
| Flat (out of market) | 44.8% | 35.2% | 18.2% | 0% |
| Profitable when in a trade | 54.4% | 52.8% | 53.5% | 63.6% |
| Average return | +0.02% | +0.11% | +0.46% | +5.4% |
| Best period | +3.55% | +4.81% | +7.18% | +25.8% |
| Worst period | −2.53% | −2.53% | −3.35% | −6.16% |
| Avg drawdown within period | −0.12% | −0.52% | −1.48% | −6.15% |
| **Worst drawdown within period** | **−2.53%** | **−4.17%** | **−4.34%** | **−9.70%** |
| *Same at 1% risk: profitable* | *29.4%* | *33.3%* | *43.0%* | *63.6%* |
| *Same at 1% risk: worst drawdown* | *−1.28%* | *−1.70%* | *−2.06%* | *−5.92%* |
| Gold buy & hold: profitable | 53.6% | 56.4% | 57.0% | 54.5% |
| Gold buy & hold: worst drawdown | −10.8% | −10.8% | −17.6% | −26.7% |

Reproduce with `python -m backtest.run gold_daily.csv --fresh-start 2016-11-04 --periods` (CSV from 2015 onward).
`--start 2016-11-04` instead rescales the full-history account to $25k on that date, which gives slightly different
results (about 5.6%/yr) because position sizes are rounded to whole ounces at a different account size and a
position can already be open on the start date.

### The risk dial: you choose the drawdown

Return and drawdown scale together. Pick the drawdown you can live with:

| Risk per trade | Annual return | Max drawdown (2000–2026) |
|---|---|---|
| 0.5% | 1.8% | −4.2% |
| 1.0% | 3.7% | −8.8% |
| **2.0% (default)** | **6.4%** | **−17.5%** |
| 2.5% | 6.9% | −19.1% |
| 3.0% | 7.1% | −19.7% |

Above 2% the no-leverage cap (position value ≤ account equity) starts limiting size, so extra risk buys little extra
return. Expect live drawdowns to be **worse** than any backtest.

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

Fresh $25,000 account opened 2016-11-04 (`--fresh-start 2016-11-04 --news-mode ...`):

| Mode | What it does | 2% risk: annual return / max DD | 1% risk: annual return / max DD | Trades (2%) |
|---|---|---|---|---|
| Off | ignore news | 5.59% / −12.4% | 2.73% / −6.0% | 101 |
| **Block entries (default)** | no new entry if a release is on the next session | **5.52% / −12.1%** | 2.75% / −6.2% | 99 |
| Tighten stop | block + raise the stop to close − 1×ATR before a release | 5.08% / −11.6% | 2.75% / −6.5% | 127 |
| Go flat | block + close positions before every release | 3.85% / −16.3% | 2.24% / −8.5% | 231 |

None of them meaningfully improves the backtest: stepping aside costs fees and misses moves, and the 2–2.5×ATR stops
already absorb most news spikes. *Go flat* is clearly worse. **Block entries** is the default as cheap insurance
(within ±0.1%/yr of *Off*, 2 trades in 10 years, which is noise). It protects against what a backtest can't model: spreads widening 5–10× and fills slipping
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
3. Change *Properties → Initial capital* to your account size. At gold ≈ $4,000 with daily-ATR stops, 2% risk needs
   roughly **$6–8k+** to trade even 1 oz. Below that, either use a broker that allows fractional ounces (set
   *Quantity step*) or accept that it will skip trades.

## 2. Paper trade with webhooks

On Windows, follow [PAPER_TRADING.md](PAPER_TRADING.md) (start scripts, daily routine, weekly checks).

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

* shared-secret auth (constant-time compare), 16 KB body limit
* optional `IP_ALLOWLIST` (IPs or CIDR ranges). The client IP is the socket address, or, only for requests from a
  loopback proxy, the header named in `TRUSTED_IP_HEADER` (`CF-Connecting-IP` behind cloudflared).
  `X-Forwarded-For` is never trusted, since any client can set it. A missing or malformed header is rejected (403)
* symbol whitelist, required stop on every entry (no unprotected trades)
* stop updates are **tighten-only** and refused if on the wrong side of price
* stale-alert rejection, duplicate-alert suppression, one position at a time
* max trades/day, daily-loss lock-out, kill-switch file
* size capped by `MAX_UNITS`, `MAX_RISK_PCT` of balance **and** `MAX_LEVERAGE` (notional ÷ balance, default 1 = no leverage)
* one order at a time, **no blind retries**: on a network error it checks the position and marks the order `unknown`
* answers within TradingView's ~3 s webhook timeout: in OANDA mode the bridge answers `202 queued` immediately and
  executes orders in a background worker, one at a time, in arrival order (`EXECUTION_MODE=auto`; paper mode stays
  synchronous). `/status` shows `execution_mode`, `queue_depth` and `recent_results`
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

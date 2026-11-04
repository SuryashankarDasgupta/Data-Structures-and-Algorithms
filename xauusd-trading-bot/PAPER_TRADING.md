# Paper trading routine (Windows)

TradingView alerts drive the bridge in **paper mode**: no broker, no real money. Run it for at least
3 months before deciding anything. All commands are run from the `xauusd-trading-bot` folder in PowerShell.

## One-time setup

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # then set WEBHOOK_SECRET (32+ random chars), BROKER=paper, PAPER_START_BALANCE=25000
```

`.env` is gitignored; never commit it. Set `BRIDGE_HOST=127.0.0.1` in it so only the tunnel can reach the bridge.

## Start each session

The bridge must be running, and the PC awake, whenever TradingView fires an alert. Daily-bar alerts arrive
around the daily close, **~22:00 UTC (03:30 IST)**. Turn off sleep while paper trading, or use a small VPS.

1. **Bridge** (terminal 1):

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_bridge.ps1
   ```

   It loads `.env` and keeps the journal, paper account and kill switch under `runtime\` (gitignored).

2. **Tunnel** (terminal 2): TradingView only posts to ports 80/443 on a public HTTPS URL.

   ```powershell
   cloudflared tunnel --url http://localhost:8080
   ```

   It prints `https://<random>.trycloudflare.com`. **The URL changes every time cloudflared restarts**, so
   update the alert's webhook URL (`https://<random>.trycloudflare.com/webhook`) each time, or set up a named
   Cloudflare tunnel for a fixed URL. Anyone with the URL can reach the bridge, but every request needs the
   secret, and paper mode can't touch real money.

### Optional: accept only TradingView's IPs

The secret stays the main guard; this is extra protection. Behind cloudflared every request reaches the bridge
from 127.0.0.1, so the bridge must take the real client IP from Cloudflare's `CF-Connecting-IP` header. Add to
`.env`, then restart the bridge:

```
IP_ALLOWLIST=52.89.214.238,34.212.75.30,54.218.53.128,52.32.178.7
TRUSTED_IP_HEADER=CF-Connecting-IP
```

Check the IPs against TradingView's help page ("How to configure webhook alerts") first; the list can change. If
TradingView changes them without notice, alerts start failing with 403, so look at the alert log's *Webhook status*
column after enabling this. Setting `IP_ALLOWLIST` without `TRUSTED_IP_HEADER` rejects everything, and the bridge
warns about it at startup.

## Option: run the 24/7 multi-market scanner instead of TradingView alerts

The scanner trades gold + BTC + ETH by itself (see README "Multi-market portfolio and 24/7 scanner"). It needs no
TradingView alerts and no public tunnel, only the bridge running.

1. In `.env`: `SCANNER=on`, `ALLOWED_SYMBOLS=XAUUSD,BTCUSD,ETHUSD`, `RISK_PCT=1.0`, keep `BROKER=paper`.
   With no OANDA token, gold prices come from Yahoo (`NONFX_FEED=auto` → yahoo, paper only) and crypto from Coinbase.
2. **Turn off the TradingView alert for XAUUSD** (or remove XAUUSD from `ALLOWED_SYMBOLS`): two sources must
   not manage the same position.
3. Start the bridge as usual (`scripts\start_bridge.ps1`). The log shows `scanner started: XAUUSD,BTCUSD,ETHUSD`.
4. Check it: `scripts\report.ps1 -Status`. The `scanner` block shows the last cycle time and, per market, the last
   daily bar processed, the open position and its stop, and any data errors.
5. A one-off test without the server: `.venv\Scripts\python -m bridge.scanner --once`.

The PC must stay on and awake: crypto trades 24/7 and its daily bar closes at 05:30 IST (00:00 UTC). Gold closes
at 02:30/03:30 IST. If the PC sleeps, decisions happen when it wakes, at worse prices, and a paper stop can be missed.

## Check on it

```powershell
curl.exe http://localhost:8080/status
```

Shows broker (must say `paper`), balance, open position, entries today and the next news events, plus
`execution_mode`. Paper trading runs in `sync` mode: each alert is executed before TradingView gets its answer,
so `queue_depth` stays 0 and `recent_results` stays empty. With `EXECUTION_MODE=async` (the default for OANDA), the
bridge answers `202 queued` at once. `queue_depth` then shows orders waiting for the background worker, and
`recent_results` the last 20 executed ones (time, alert key, status, detail).

Daily summary (realized P&L, orders, rejected alerts), plus the status above with `-Status`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\report.ps1 -Yesterday -Status
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\report.ps1 -Date 2026-11-05
```

Days are **UTC** days, because the bridge journals by UTC. The daily-close alerts at ~03:30 IST belong to the
previous UTC day, so in the morning use `-Yesterday`. Without a date the script reports today (UTC).

## Kill switch

Create the file to block all **new entries** immediately; closes and stop updates still go through.

```powershell
New-Item runtime\KILL_SWITCH -ItemType File      # on
Remove-Item runtime\KILL_SWITCH                   # off
```

(`scripts\start_bridge.ps1` sets `KILL_SWITCH_FILE` to `runtime\KILL_SWITCH`.)

## Weekly checks

1. **Bridge vs TradingView:** compare the bridge journal (`scripts\report.ps1 -Date <day>` for each day with activity) with the
   trades in TradingView's Strategy Tester → *List of trades*. Every TradingView entry and exit should appear in
   the journal as `accepted`. Missing ones mean the bridge or tunnel was down, or the alert's URL was stale.
   Rejected ones show the reason (news guard, stale alert, risk limit). If they drift apart, close the paper
   position by hand or reset (below) and note it.
2. **TradingView alert log:** check the *Webhook status* column for failed deliveries.
3. **News calendar:** the weekly task runs `scripts\update_news.ps1` (log: `logs\news_update.log`). If it prints
   `CALENDAR CHANGED`, commit `data/high_impact_usd.csv` and the Pine file, then re-paste the Pine script into
   TradingView (Pine Editor → paste → Save; the strategy reloads).

## Reset the paper account

Stop the bridge (Ctrl+C), then:

```powershell
Remove-Item runtime\paper_state.json, runtime\journal.sqlite3
```

and start it again. The balance goes back to `PAPER_START_BALANCE`.

## When to stop and decide

* Paper trade for **at least 3 months and 10+ trades** before any decision about real money.
* Judge it on whether the bridge followed TradingView reliably, not on profit. Over a few months the strategy can
  easily be flat or down; the backtest's edge only shows over years.
* Live trading stays off until you deliberately set `BROKER=oanda`, `OANDA_ENV=live` **and**
  `ALLOW_LIVE_TRADING=yes-i-understand-the-risk` yourself. Use an OANDA *practice* account first, and check that
  leveraged gold CFDs are legal where you live.

Educational only, not financial advice.

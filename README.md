# BTC-Bot-2.0 — BloFin demo breakout bot

A forward-test bot for a 4h volume-confirmed breakout strategy on USDT perpetuals, trading **only on BloFin demo**.
It simulates prop-firm rules on a notional account so you can see how the strategy would treat a challenge or a
funded account.

> **Demo only.** The bot refuses to start unless the API base URL is exactly
> `https://demo-trading-openapi.blofin.com`, and it re-checks this before every request
> (`bot/config.py: assert_demo_url`, `bot/exchange.py: BlofinDemo._guard`). There is no setting to point it at
> live trading.

## Contents
1. [How it works](#how-it-works)
2. [Setup](#setup)
3. [Running it](#running-it)
4. [Switching modes](#switching-modes)
5. [Reading the logs and reports](#reading-the-logs-and-reports)
6. [Stopping the bot](#stopping-the-bot)
7. [Moving to a $5 VPS with systemd](#moving-to-a-5-vps-with-systemd)
8. [Implementation notes and BloFin specifics](#implementation-notes-and-blofin-specifics)
9. [Tests](#tests)

## How it works

Every 4 hours, 2 minutes after the candle closes (00, 04, 08, 12, 16, 20 UTC), one run of `python -m bot.run`:

1. Loads 4h candles for BTC, ETH, BNB, XRP, ADA, DOGE, LINK, SOL, DOT and AVAX (`-USDT` perpetuals; any symbol not
   listed on BloFin is skipped and logged).
2. **Reconciles** the saved state with the exchange: recovers entries whose order was sent but not recorded, books
   exits (stop, target, manual close) from the exchange fills, with fees and funding, and flags positions it did not
   open.
3. Computes simulated equity and checks the prop-firm limits (5% daily loss from 00:00 UTC equity, 10% static
   drawdown), including the worst case inside every 4h bar since the last run. A breach flattens everything, sets
   the **challenge failed** flag, stops trading and alerts you.
4. Closes trades that have been open 60 bars (10 days).
5. Checks that every open trade's stop-loss and take-profit are **on the exchange**, and re-places them if not.
6. Looks for signals on the just-closed bar and enters with a market order with TP/SL attached.
7. Saves `state.json`, appends to `logs/*.csv`, sends alerts.

Running it twice for the same bar is harmless: the bar is only evaluated once, and every entry has a deterministic
`clientOrderId` that the next run checks before doing anything else.

### Strategy (implemented as specified)

| | |
|---|---|
| Signal bar | volume z-score (vs 50-bar mean/stdev) > 2.0 |
| Levels | daily (UTC) swing highs/lows: higher/lower than the 5 days before and after; usable only after those 5 days have closed; swing day within 365 days |
| Long | close > L + 0.2·ATR(14) and previous close ≤ L (highest such L); stop L − 0.5·ATR |
| Short | close < L − 0.2·ATR and previous close ≥ L (lowest such L); stop L + 0.5·ATR |
| Skip | stop distance < 0.3% or > 10%; a new entry on the same symbol within 6 bars |
| Exit | stop, target, or market close after 60 bars |
| Loss streak | after 3 losses in a row, risk is halved until the next win |

| Mode | Filters | Target | Risk/trade | Max open risk | Pre-trade guard thresholds |
|---|---|---|---|---|---|
| `challenge` | none | 3R | 2.0% | 4% | daily 5%, drawdown 10% |
| `funded` | side must match BTC trend (daily close vs 200-day SMA, yesterday); volatility rank ≤ 0.90 | 5R | 0.75% | 3% | daily 4.5%, drawdown 9% |

## Setup

### 1. BloFin demo API key
1. Log in to BloFin, switch to **Demo Trading**, and create an API key there (demo keys are separate from live keys).
   Give it **Trade** permission only. Never enable withdrawals.
2. Note the key, secret and passphrase.
3. GitHub Actions runs from changing IP addresses, so don't bind the key to an IP. Check whether BloFin expires keys
   without an IP whitelist; if it does, put a reminder in your calendar to renew it.
4. Make sure the demo account's USDT balance is at least `ACCOUNT_SIZE` (default 100,000), preferably 2–3× so that
   isolated margin never limits a position. The bot sizes from the *simulated* equity and only uses the real
   balance to check that the margin fits.

### 2. GitHub secrets and variables
In the repository: **Settings → Secrets and variables → Actions**.

| Secrets | |
|---|---|
| `BLOFIN_API_KEY`, `BLOFIN_API_SECRET`, `BLOFIN_PASSPHRASE` | required |
| `DISCORD_WEBHOOK_URL` | optional: entries, exits, guard blocks, errors, daily summary |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | optional alternative to Discord |

| Variables (Variables tab) | Default | |
|---|---|---|
| `MODE` | `challenge` | `challenge` or `funded` |
| `ACCOUNT_SIZE` | `100000` | notional prop-firm account size |
| `BOT_ENABLED` | `true` | `false` = kill switch |
| `EXIT_PROTOCOL` | `R1` | how trades are taken off: `R1`, `R4`, `BE2` or `B0` (see "Exit plans" below) |
| `LONG_ONLY` | `true` | `false` re-enables short trades |
| `VOLUME_SOURCE` | `binance` | `binance` (Binance spot 4h volume, public) or `blofin` |

Credentials are only read from the environment. They are never written to files or logs.

### 3. Local install (optional)
```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
```
```bash
.venv/bin/python -m pytest -q
```

## Running it

- **Manage-only run** (`python -m bot.run --manage-only`, or tick "Manage only" in Actions): updates stops,
  break-even and trailing, checks TP/SL, books exits; evaluates no new signals.
- **Dry run** (prints signals and sizing; no orders, no state saved). It works even without API keys, using public
  candle data only:
  ```bash
  .venv/bin/python -m bot.run --dry-run
  ```
  On GitHub: **Actions → bot → Run workflow**, with "Dry run" ticked (the default).
- **One live-demo run**: the same, with "Dry run" unticked.
- **Schedule**: the `schedule:` lines in `.github/workflows/bot.yml` are commented out. Uncomment them to run every
  hour at :02. Runs right after a 4h close look for new entries; the others only manage open trades. GitHub may start scheduled runs several minutes late; that's fine because the bot always evaluates the
  last *closed* bar. If a whole bar is missed, its signals are logged as `stale` and not traded.
- **Self-test of orders and TP/SL** (Actions → bot → Run workflow → tick "Self-test"): opens the minimum
  BTC-USDT size (0.0001 BTC) on demo with stop and target attached, checks BloFin lists them, deletes them and
  checks the bot re-places them, then closes the position. The result is saved to `selftest/last.md` on the
  `bot-state` branch. It never touches the bot's state or stats, and refuses to run if BTC has a position.
- **90-day replay** of the signal logic on BloFin demo candles (public data, no keys):
  ```bash
  .venv/bin/python scripts/replay_90d.py --days 90 --mode challenge
  ```

State, logs and reports are committed by the workflow to the **`bot-state`** branch:

```
bot-state/
  state.json          open/closed trades, equity history, loss streak, day-start equity, failed flag
  logs/signals.csv    every signal, taken or skipped, with the reason
  logs/trades.csv     entries, exits, fees, funding, TP/SL repairs, failures
  reports/weekly.md   weekly report (Mondays 00:02 UTC, or on request)
```

## Exit plans, direction and volume (v2)

The research in `research/` led to three changes from the original spec. All three can be switched back with the
variables above.

| Setting | Default | What it does | Why |
|---|---|---|---|
| `EXIT_PROTOCOL=R1` | on | Stop to **break-even (entry + costs) once +2R is reached**; **50% off at the target** (3R challenge / 5R funded); the other 50% **trails 3 × ATR(4h)** below the best price since entry; max hold 60 days | best runner design in `partials_study_results.md`: better than 100%-at-3R in all five test sets (+0.11R per trade, not yet statistically proven) |
| `EXIT_PROTOCOL=R4` | | Break-even at +2R; 25% off at 2R, 25% at the target, 50% trails 3 ATR | same idea with a 41% win rate and shorter losing streaks |
| `EXIT_PROTOCOL=BE2` | | 100% at the target, break-even at +2R, 60-bar time exit | |
| `EXIT_PROTOCOL=B0` | | 100% at the target, 60-bar time exit (the original spec) | |
| `LONG_ONLY=true` | on | short signals are logged as "long-only mode" and not traded | the long side passed on 3 of 3 unseen coins; the short side made about zero after costs (`backtest_report.md`) |
| `VOLUME_SOURCE=binance` | on | the volume z-score uses Binance spot 4h volume; prices, levels and orders stay on BloFin. If Binance is unreachable the run falls back to BloFin volume and alerts | BloFin's volume flags only ~40–50% of the spikes the strategy was researched on; Binance spot ~75–80% |

**How the exit plan runs on the exchange.**
- The stop is always on BloFin for the full open size. Each partial target is its own reduce-only take-profit order for
  its share.
- Break-even and the trailing stop are moved by the bot (exchanges don't trail for you). That means they're only as fresh
  as the last run.
- With the hourly schedule (below), runs between the 4h closes only manage open trades (`--manage-only`). Stops then move
  every hour instead of every 4 hours.
- If price is already beyond a newly moved stop when the bot runs, the trade is closed at market.

**Open-risk cap.** The 4% / 3% cap counts the money still at stake: entry to the *current* stop. A trade whose stop is
at break-even no longer blocks new entries.

## Dashboard

`scripts/export_dashboard.py` runs after every bot run. It writes `docs/index.html` and `docs/data.json` to the
`bot-state` branch, which together are the whole dashboard:
- live equity, P&L and limit gauges (prices from BloFin demo every 10 s);
- equity curve and open positions with stop / break-even / trailing status;
- full, searchable trade history (click any trade for its timeline, fills, signal and raw record);
- signals log, event log, configuration and the last exchange self-test;
- CSV export of any filtered table.

The page reloads the bot's data every 60 s.

**Hosting:** in GitHub, **Settings → Pages → Build and deployment → Deploy from a branch → `bot-state` / `/docs`**.
- Pages on a **private** repository needs a paid GitHub plan (Pro or higher).
- On any plan, a Pages site can be opened by anyone with the link.
- Without Pages, download the `docs` folder and run `python -m http.server` inside it, then open http://localhost:8000.

## Switching modes

Change the `MODE` variable to `funded` (or back to `challenge`). The new mode applies to **new** trades only. Open
trades keep their original stop and target, and the switch is logged. To start a fresh forward test (new
notional account), delete or rename `state.json` on the `bot-state` branch once no trades are open.

## Reading the logs and reports

- `reports/weekly.md`: trades this week and all-time, win rate, average and total R, net P&L, fees and funding,
  trades per week, an equity curve, max drawdown (peak-to-trough and static from the start), the peak daily
  loss, and a **comparison with the backtest**:
  - challenge: ≈ +0.15R per trade long-run, but flat to negative since Aug 2026; win rate ≈ 30–35% at 3R
  - funded: win rate ≈ 25% at 5R

  It shows 95% ranges. With fewer than ~30 trades the ranges are wide, and a 1–2 month forward test mostly tells
  you whether the live behaviour (fills, slippage, signal frequency) matches the backtest, not whether the edge is
  real.
- `logs/signals.csv`: `action` is `taken`, `skipped` or `dry_run`; `reason` explains a skip (stop distance,
  cooldown, BTC trend, volatility rank, position already open, max open risk, daily-loss/drawdown guard,
  kill switch, stale bar…). `note` records `risk reduced: …` when the 5x leverage cap or the demo margin limited a
  position.
- `logs/trades.csv`: one row per event. `r_multiple` = net P&L ÷ planned risk.
- Rebuild the report any time: `STATE_DIR=path/to/bot-state python scripts/weekly_report.py`.

## Stopping the bot

Any of these stops **new** entries. Open trades are still managed (exits, TP/SL checks, limit checks), and skipped
signals are logged with reason "kill switch":

- create a file named `STOP` in the repo root (on the branch the workflow runs from) or on the `bot-state` branch;
- or set the Actions variable `BOT_ENABLED` to `false`.

To stop everything: disable the workflow (**Actions → bot → ⋯ → Disable workflow**). Your stops and targets stay on
the exchange, so open trades remain protected. To close positions, do it in the BloFin demo UI; the next run (if
any) will book the exit as "closed outside bot".

## Moving to a $5 VPS with systemd

If GitHub's scheduler proves unreliable (long delays or skipped runs), run the same code on any small Linux VPS:

```bash
sudo useradd -r -m -d /opt/btc-bot btcbot
sudo -u btcbot git clone https://github.com/<you>/BTC-Bot-2.0 /opt/btc-bot
sudo -u btcbot git clone -b bot-state https://github.com/<you>/BTC-Bot-2.0 /opt/btc-bot-state
cd /opt/btc-bot && sudo -u btcbot python3.11 -m venv .venv && sudo -u btcbot .venv/bin/pip install -r requirements.txt
sudo cp deploy/btc-bot.env.example /etc/btc-bot.env && sudo chmod 600 /etc/btc-bot.env && sudo nano /etc/btc-bot.env
sudo cp deploy/btc-bot.service deploy/btc-bot.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now btc-bot.timer
```

- Before enabling the timer, disable the Actions schedule so the two never run at the same time.
- `systemctl list-timers btc-bot.timer` shows the next run. `journalctl -u btc-bot -n 200` shows the output.
- To keep pushing state to GitHub, give the `btcbot` user a deploy key or token with write access to the repo.
  Otherwise set `PUSH_STATE=false`.
- Keep the clock synced (`timedatectl set-ntp true`); BloFin rejects requests with a skewed timestamp.

## Implementation notes and BloFin specifics

- **Library: ccxt** (pinned 4.5.93) with `set_sandbox_mode(True)`. ccxt has BloFin's demo URL built in and
  handles request signing and rate limiting. Every call uses BloFin's raw endpoints through ccxt
  (`/api/v1/trade/order`, `/trade/order-tpsl`, `/trade/orders-tpsl-pending`, `/trade/cancel-tpsl`,
  `/account/set-leverage`, …), so the exact TP/SL fields are under our control and ccxt's broker tag is not
  added. The `blofin` package on PyPI is a third-party SDK, not BloFin's, and it hard-codes the live URL, so it
  was not used.
- **TP/SL**: attached to the entry order (`slTriggerPrice`/`tpTriggerPrice`, `-1` = market). After every entry
  and on every run the bot lists pending TP/SL orders and, if the right pair is missing, cancels any partial ones
  and places a reduce-only TP/SL order for the full size.
- **Account**: net position mode, isolated margin (both set by the bot if no positions are open).
  **One position per symbol**: a new signal while a trade is open on that symbol is skipped and logged.
- **Leverage**: the smallest whole number that fits the position's margin into the simulated equity (or the demo
  balance, if smaller), capped at 5x. If 5x is not enough (challenge mode with stops under ~0.4%), the position
  is **shrunk** to what 5x can hold and the signal row says `risk reduced: leverage cap`.
- **Sizing equity**: simulated equity = `ACCOUNT_SIZE` + net realized P&L (after fees and funding) + open P&L.
- **Guards**: "today's loss" and "current drawdown" include open P&L, so open trades count only with the risk
  left between the current price and their stops (counting full initial risk too would count the same loss
  twice). The 4%/3% max-open-risk cap uses each trade's initial risk.
- **Between runs**: the limit check also replays each 4h bar since the last run, using its high/low (clamped at
  each trade's stop) to catch a breach that recovered before the next run.
- **Losses**: a trade counts as a loss if its net P&L (after fees and funding) is below zero, including time exits.
- **Entry price and R**: stop and target come from the signal bar's close, as in the backtest. The actual fill is
  recorded, and R = net P&L ÷ planned risk, so slippage shows up in R.
- **Volume**: base-currency volume (same z-score as contract volume). **Swing levels**: strictly higher/lower than
  all 10 neighbouring days (ties don't count). Daily candles are built from the 4h candles; BloFin's own daily
  candles are also UTC-aligned.
- **Data**: about 3,400 4h bars (≈ 19 months) per symbol, cached. BloFin demo history currently starts in Aug 2024
  and has a 2-bar gap on 2026-03-09 for all symbols; the indicators treat it as continuous.
- **Rate limits** (per ccxt, since the docs site blocks automated readers): about 500 requests/minute and 1,500 per
  5 minutes per IP. A normal run makes a few dozen requests.
- **Funding**: read from `/api/v1/account/funding-fees` for the holding period. If that endpoint is unavailable it
  is logged and counted as 0.

## Tests

```bash
.venv/bin/python -m pytest -q              # unit + full-run tests against an in-memory fake exchange
.venv/bin/python -m pytest -q -m replay -s # network: replay the last 90 days of BloFin demo candles
```

Covered: the demo-URL guard; level detection, including no look-ahead (a level is invisible until its 5 confirming
days have closed, and full-history results match truncated-history results); the signal rules; sizing and
leverage; the open-risk cap, daily and drawdown guards and breach detection; the loss-streak rule; and full runs
covering entry, a duplicate run, crash recovery, missing TP/SL, stop/manual/time exits, kill switch, breach →
flatten, dry run, funded filters and stale bars.

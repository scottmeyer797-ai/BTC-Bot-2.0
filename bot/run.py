"""One bot run. Usage: python -m bot.run [--dry-run]

Order of work: data -> reconcile -> equity & limit checks -> time exits ->
TP/SL verification -> signals & entries -> state save. Designed to be run
every 4 hours shortly after the bar closes; running it twice is harmless.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import traceback
from datetime import datetime, timezone
from decimal import Decimal

from .alerts import Alerter
from .config import BAR_MS, QUOTE, TIME_EXIT_BARS, UNIVERSE, Config, load_config
from .data import load_candles
from .exchange import BlofinDemo
from .indicators import DAY_MS, add_indicators, btc_trend_at, btc_trend_by_day, daily_candles, day_floor, \
    levels_at, swing_levels
from .journal import Journal
from .reconcile import Reconciler, describe_trade, direction, entry_side, trade_qty
from .risk import Snapshot, TradeExposure, breach_reason, effective_risk_pct, guard_block_reason, \
    open_risk_cap_reason, worst_equity_path
from .signals import detect_signal, signal_filter_reason
from .sizing import size_position
from .state import load_state, ms_to_iso, save_state, utcnow_iso

log = logging.getLogger("bot")

WRITE_METHODS = {"set_leverage", "market_entry", "place_tpsl", "cancel_tpsl", "close_position",
                 "ensure_account_modes"}


class DryRunClient:
    """Forwards reads to the real client; logs and skips every write."""
    settle_seconds = 0

    def __init__(self, inner):
        self.inner = inner
        self.private = getattr(inner, "private", False)
        self.writes: list[str] = []

    def __getattr__(self, name):
        attr = getattr(self.inner, name)
        if name not in WRITE_METHODS:
            return attr

        def skipped(*args, **kwargs):
            desc = f"{name}({', '.join(repr(a) if not hasattr(a, 'inst_id') else a.inst_id for a in args)})"
            self.writes.append(desc)
            log.info("DRY RUN: would call %s", desc)
            return [] if name == "ensure_account_modes" else f"dry-{name}"
        return skipped


def date_str(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


class Bot:
    def __init__(self, cfg: Config, client, *, dry_run: bool, now_ms: int | None = None, alerter=None, journal=None):
        self.cfg = cfg
        self.dry_run = dry_run
        self.client = DryRunClient(client) if dry_run else client
        self.now_ms = now_ms or int(time.time() * 1000)
        self.journal = journal or Journal(cfg.log_dir, dry_run=dry_run)
        self.alerter = alerter or Alerter(cfg, dry_run=dry_run)
        self.state = load_state(cfg.state_path, cfg.mode.name, cfg.account_size)
        self.report: list[str] = []
        self.private = getattr(client, "private", False)

    def say(self, msg: str) -> None:
        log.info(msg)
        self.report.append(msg)

    # -- equity ----------------------------------------------------------------
    def price_at(self, symbol: str, t_ms: int) -> float | None:
        df = self.frames.get(symbol)
        if df is None:
            return None
        rows = df[df["ts"] + BAR_MS <= t_ms]
        return float(rows["close"].iloc[-1]) if len(rows) else None

    def unrealized(self, t: dict, price: float | None) -> float:
        if price is None or t["status"] != "open":
            return 0.0
        return direction(t["side"]) * (price - t["entry_price"]) * trade_qty(t) - t.get("entry_fee", 0.0)

    def equity_now(self) -> tuple[float, float]:
        unreal = sum(self.unrealized(t, self.prices.get(t["inst_id"])) for t in self.state["open_trades"])
        return self.cfg.account_size + self.state["realized_pnl"] + unreal, unreal

    def equity_at(self, t_ms: int) -> float:
        """Reconstructed simulated equity at a past time, from trade records and 4h closes."""
        eq = self.cfg.account_size
        for t in self.state["closed_trades"]:
            if t["exit_ts"] <= t_ms:
                eq += t["net_pnl"]
            elif t.get("entry_ts", 0) <= t_ms:
                eq += self.unrealized({**t, "status": "open"}, self.price_at(t["symbol"], t_ms))
        for t in self.state["open_trades"]:
            if t["status"] == "open" and t.get("entry_ts", 0) <= t_ms:
                eq += self.unrealized(t, self.price_at(t["symbol"], t_ms))
        return eq

    def day_start_equity(self, day_ms: int) -> float:
        key = date_str(day_ms)
        d = self.state["day_start_equity"]
        if key not in d:
            d[key] = round(self.equity_at(day_ms), 2)
        return d[key]

    def snapshot(self) -> Snapshot:
        equity, _ = self.equity_now()
        init = rem = 0.0
        for t in self.state["open_trades"]:
            init += t.get("risk_amount", 0.0)
            px = self.prices.get(t["inst_id"], t.get("entry_price"))
            rem += max(0.0, direction(t["side"]) * (px - t["stop"])) * trade_qty(t)
        return Snapshot(self.cfg.account_size, equity, self.day_start_equity(day_floor(self.now_ms)), init, rem)

    # -- main ----------------------------------------------------------------
    def run(self) -> int:
        cfg = self.cfg
        self.say(f"run at {ms_to_iso(self.now_ms)} mode={cfg.mode.name} account={cfg.account_size:,.0f} "
                 f"dry_run={self.dry_run} credentials={'yes' if self.private else 'no'}")
        if not self.private and not self.dry_run:
            raise RuntimeError("BLOFIN_API_KEY / BLOFIN_API_SECRET / BLOFIN_PASSPHRASE are required for a live-demo run")
        if self.state["mode"] != cfg.mode.name:
            self.say(f"MODE changed {self.state['mode']} -> {cfg.mode.name}; applies to new trades only")
            self.state["mode"] = cfg.mode.name

        # 1. instruments & data
        instruments = self.client.instruments()
        self.universe: dict[str, str] = {}
        for sym in UNIVERSE:
            inst_id = f"{sym}-{QUOTE}"
            if inst_id in instruments:
                self.universe[sym] = inst_id
            else:
                self.say(f"WARNING {inst_id} not listed on BloFin demo; skipping")
        self.instruments = instruments
        self.frames, self.ind, self.levels = {}, {}, {}
        for sym, inst_id in self.universe.items():
            df = load_candles(self.client, inst_id, cfg.cache_dir, now_ms=self.now_ms)
            self.frames[sym] = df
            self.ind[sym] = add_indicators(df)
            self.levels[sym] = swing_levels(daily_candles(df, int(df["ts"].iloc[-1]) + BAR_MS))
        latest_close = max(int(df["ts"].iloc[-1]) + BAR_MS for df in self.frames.values())
        self.latest_close = latest_close
        self.say(f"latest closed 4h bar: {ms_to_iso(latest_close)}")
        btc = self.frames.get("BTC")
        self.trend_by_day = btc_trend_by_day(daily_candles(btc, latest_close)) if btc is not None else {}
        try:
            self.prices = {k: v for k, v in self.client.last_prices().items()}
        except Exception as e:  # noqa: BLE001
            log.warning("ticker fetch failed (%s); using last 4h closes", e)
            self.prices = {}
        for sym, inst_id in self.universe.items():
            self.prices.setdefault(inst_id, float(self.frames[sym]["close"].iloc[-1]))

        # 2. reconcile with the exchange
        rec = Reconciler(self.client, self.state, instruments, self.journal, self.alerter, self.now_ms)
        self.rec = rec
        positions = {}
        balance = None
        if self.private:
            rec.resolve_pending()
            positions = self.client.positions()
            rec.sync_positions(positions, self.prices)
            balance = self.client.usdt_balance()
            self.say(f"demo account USDT equity {balance['equity']:,.2f}, available {balance['available']:,.2f}")
        else:
            self.say("no credentials: skipping exchange reconciliation (public-data dry run)")

        # 3. equity and limits
        equity, unreal = self.equity_now()
        today = day_floor(self.now_ms)
        day_start = self.day_start_equity(today)
        self.say(f"simulated equity {equity:,.2f} (unrealized {unreal:+,.2f}), 00:00 UTC equity {day_start:,.2f}, "
                 f"losing streak {self.state['consecutive_losses']}")
        if not self.state["failed"]:
            reason = breach_reason(cfg.account_size, equity, day_start) or self.between_runs_breach()
            if reason:
                self.fail(reason)

        if self.state["failed"]:
            self.flatten("challenge failed")
        else:
            # 4. time exits
            for t in [t for t in self.state["open_trades"] if t["status"] == "open"]:
                t["bars_held"] = int((latest_close - t["entry_bar_close_ts"]) // BAR_MS)
                if t["bars_held"] >= TIME_EXIT_BARS:
                    self.say(f"time exit: {t['symbol']} held {t['bars_held']} bars")
                    rec.close_trade(t, "time exit (60 bars)", self.prices.get(t["inst_id"]))
            # 5. TP/SL on exchange
            if self.private:
                for t in [t for t in self.state["open_trades"] if t["status"] == "open"]:
                    res = rec.verify_tpsl(t)
                    self.say(f"TP/SL {t['symbol']}: {res}")
                    if res != "ok" and not res.startswith("ok"):
                        self.alerter.send("🛡️ " + res)

        # 6. signals and entries
        if self.private and not self.state["failed"]:
            try:
                notes = self.client.ensure_account_modes(bool(positions))
                for n in notes:
                    self.say(f"account: {n}")
            except RuntimeError as e:
                self.say(f"ERROR account modes: {e}")
                self.alerter.send(f"⚠️ {e}")
                self.state["_entries_blocked"] = str(e)
        self.scan_signals(balance)
        self.state.pop("_entries_blocked", None)

        # 7. bookkeeping
        equity, unreal = self.equity_now()
        snap = self.snapshot()
        self.state["equity_history"].append({
            "time": ms_to_iso(self.now_ms), "bar_close": ms_to_iso(latest_close), "equity": round(equity, 2),
            "realized": round(self.state["realized_pnl"], 2), "unrealized": round(unreal, 2),
            "day_start": day_start, "open_trades": len(self.state["open_trades"]),
            "open_risk": round(snap.open_initial_risk, 2), "dry_run": self.dry_run,
        })
        if not self.dry_run:
            self.state["last_processed_bar_close_ts"] = latest_close
        self.daily_summary(equity, day_start)
        for t in self.state["open_trades"]:
            self.say("open: " + describe_trade(t))
        if self.dry_run:
            self.say("DRY RUN: state not saved; no orders sent" +
                     (f"; skipped writes: {self.client.writes}" if self.client.writes else ""))
        else:
            save_state(cfg.state_path, self.state)
        return 0

    # -- limits ------------------------------------------------------------------
    def between_runs_breach(self) -> str | None:
        start = self.state.get("last_processed_bar_close_ts")
        if not start:
            return None
        exposures = []
        base = self.cfg.account_size
        for t in self.state["closed_trades"]:
            if t["exit_ts"] <= start:
                base += t["net_pnl"]
            else:
                exposures.append(TradeExposure(t["symbol"], t["side"], t.get("entry_ts", 0), t["exit_ts"],
                                               t["entry_price"], t["stop"], trade_qty(t), t["net_pnl"]))
        for t in self.state["open_trades"]:
            if t["status"] == "open":
                base -= t.get("entry_fee", 0.0)
                exposures.append(TradeExposure(t["symbol"], t["side"], t.get("entry_ts", 0), None,
                                               t["entry_price"], t["stop"], trade_qty(t)))
        if not exposures:
            return None
        bars = {s: self.frames[s] for s in {e.symbol for e in exposures} if s in self.frames}
        for close_ts, eq in worst_equity_path(base, exposures, bars, start, self.latest_close, BAR_MS):
            day = day_floor(close_ts - 1)
            reason = breach_reason(self.cfg.account_size, eq, self.day_start_equity(day))
            if reason:
                return f"{reason} — worst case inside the 4h bar closing {ms_to_iso(close_ts)}"
        return None

    def fail(self, reason: str) -> None:
        self.state.update(failed=True, failed_reason=reason, failed_at=utcnow_iso())
        self.say("CHALLENGE FAILED: " + reason)
        self.journal.trade("challenge_failed", details=reason)
        self.alerter.send(f"🚨 CHALLENGE FAILED — {reason}. Flattening all positions; trading stopped.")

    def flatten(self, why: str) -> None:
        for t in list(self.state["open_trades"]):
            if t["status"] == "open":
                self.say(f"flatten {t['symbol']} ({why})")
                self.rec.close_trade(t, why, self.prices.get(t["inst_id"]))

    # -- signals ---------------------------------------------------------------
    def scan_signals(self, balance: dict | None) -> None:
        cfg, st = self.cfg, self.state
        last = st.get("last_processed_bar_close_ts")
        if last is not None and last >= self.latest_close:
            self.say("bar already processed by an earlier run; not evaluating signals again")
            return
        first_bar = (last + BAR_MS) if last else self.latest_close
        if self.latest_close - first_bar > 30 * BAR_MS:
            first_bar = self.latest_close - 30 * BAR_MS
        n_found = 0
        for sym, inst_id in self.universe.items():
            df = self.ind[sym]
            idx = df.index[(df["close_ts"] >= first_bar) & (df["close_ts"] <= self.latest_close)]
            for i in idx:
                close_ts = int(df.at[i, "close_ts"])
                sig = detect_signal(sym, df, int(i), levels_at(self.levels[sym], close_ts))
                if sig is None:
                    continue
                n_found += 1
                trend = btc_trend_at(self.trend_by_day, close_ts)
                if close_ts != self.latest_close:
                    self.log_signal(sig, trend, "skipped", "stale: the bot did not run after this bar closed")
                    continue
                self.consider(sig, inst_id, trend, balance)
        if n_found == 0:
            self.say(f"no signals on bar closing {ms_to_iso(self.latest_close)}")

    def log_signal(self, sig, trend, action, reason, size=None, risk_pct=None, note=None):
        target = sig.target(self.cfg.mode.target_r)
        self.journal.signal(bar_close=ms_to_iso(sig.bar_close_ts), symbol=sig.symbol, side=sig.side,
                            level=sig.level, close=sig.close, atr=sig.atr, stop=sig.stop, target=target,
                            stop_pct=sig.stop_pct, vol_z=sig.vol_z, vol_rank=sig.vol_rank, btc_trend=trend,
                            mode=self.cfg.mode.name, action=action, reason=reason, risk_pct=risk_pct,
                            risk_amount=size.risk_amount if size else None,
                            contracts=str(size.contracts) if size else None,
                            leverage=size.leverage if size else None, note=note)
        line = (f"SIGNAL {sig.symbol} {sig.side} level {sig.level:.6g} close {sig.close:.6g} stop {sig.stop:.6g} "
                f"({sig.stop_pct:.2%}) target {target:.6g} z {sig.vol_z:.2f} rank {sig.vol_rank:.2f} "
                f"trend {trend:+d} -> {action}{': ' + reason if reason else ''}")
        if size:
            line += f" | {size.contracts} contracts, {size.leverage}x, risk {size.risk_amount:,.2f} USDT"
        if note:
            line += f" | {note}"
        self.say(line)

    def consider(self, sig, inst_id: str, trend: int, balance: dict | None) -> None:
        cfg, st = self.cfg, self.state
        reason = signal_filter_reason(sig, cfg.mode, trend, st["last_entry_close_ts"].get(sig.symbol))
        if reason is None and any(t["inst_id"] == inst_id for t in st["open_trades"]):
            reason = "position already open on this symbol"
        if reason is None and any(u["inst_id"] == inst_id for u in st.get("unmanaged_positions", [])):
            reason = "an unmanaged position is open on this symbol"
        if reason is None and st["failed"]:
            reason = "challenge failed: trading stopped"
        if reason is None and cfg.kill_switch:
            reason = "kill switch (STOP file or BOT_ENABLED=false): no new trades"
        if reason is None and st.get("_entries_blocked"):
            reason = "entries blocked: " + st["_entries_blocked"]
        if reason:
            self.log_signal(sig, trend, "skipped", reason)
            return
        risk_pct = effective_risk_pct(cfg.mode, st["consecutive_losses"])
        snap = self.snapshot()
        inst = self.instruments[inst_id]
        size = size_position(inst, snap.equity, risk_pct, sig.close, sig.stop,
                             available_margin=balance["available"] if balance else None)
        if size.skip_reason:
            self.log_signal(sig, trend, "skipped", size.skip_reason, size, risk_pct, size.note)
            return
        reason = open_risk_cap_reason(cfg.mode, snap, size.risk_amount) or \
            guard_block_reason(cfg.mode, snap, size.risk_amount)
        if reason:
            self.log_signal(sig, trend, "skipped", reason, size, risk_pct, size.note)
            if "guard" in reason:
                self.alerter.send(f"🛑 GUARD BLOCK {sig.symbol} {sig.side}: {reason}")
            return
        self.enter(sig, inst, trend, size, risk_pct)

    def enter(self, sig, inst, trend, size, risk_pct) -> None:
        cfg, st = self.cfg, self.state
        target = sig.target(cfg.mode.target_r)
        client_oid = f"e{sig.symbol}{sig.bar_close_ts // 1000}"
        trade = {
            "id": client_oid, "symbol": sig.symbol, "inst_id": inst.inst_id, "side": sig.side, "status": "pending",
            "mode": cfg.mode.name, "signal_bar_ts": sig.bar_ts, "entry_bar_close_ts": sig.bar_close_ts,
            "ref_price": sig.close, "entry_price": sig.close, "level": sig.level, "atr": sig.atr,
            "stop": sig.stop, "target": target, "contracts": str(size.contracts),
            "contract_value": str(inst.contract_value), "risk_amount": size.risk_amount, "risk_pct": risk_pct,
            "leverage": size.leverage, "bars_held": 0, "entry_fee": 0.0, "vol_z": sig.vol_z,
            "vol_rank": sig.vol_rank, "btc_trend": trend,
        }
        self.log_signal(sig, trend, "dry_run" if self.dry_run else "taken", None, size, risk_pct, size.note)
        if self.dry_run:
            return
        try:
            self.client.set_leverage(inst.inst_id, size.leverage)
        except Exception as e:  # noqa: BLE001
            self.say(f"ERROR set leverage {inst.inst_id} {size.leverage}x: {e}")
            self.alerter.send(f"⚠️ entry {sig.symbol} aborted: set-leverage failed: {e}")
            return
        st["open_trades"].append(trade)
        save_state(cfg.state_path, st)  # persist intent before sending the order (crash safety)
        try:
            trade["order_id"] = self.client.market_entry(inst, entry_side(sig.side), size.contracts, sig.stop,
                                                         target, client_oid)
        except Exception as e:  # noqa: BLE001
            self.say(f"ERROR entry order {sig.symbol}: {e}")
        od = None
        for _ in range(5):
            od = self.client.order_by_client_id(inst.inst_id, client_oid)
            if od and float(od.get("filledSize") or 0) > 0 and od.get("state") in ("filled", "partially_filled"):
                break
            time.sleep(getattr(self.client, "settle_seconds", 1))
        if not od or float(od.get("filledSize") or 0) <= 0:
            st["open_trades"].remove(trade)
            save_state(cfg.state_path, st)
            self.journal.trade("entry_failed", trade_id=client_oid, symbol=sig.symbol, side=sig.side,
                               details=str(od))
            self.alerter.send(f"⚠️ ENTRY FAILED {sig.symbol} {sig.side}: order not filled ({od and od.get('state')})")
            return
        self.rec.mark_filled(trade, od)
        st["last_entry_close_ts"][sig.symbol] = sig.bar_close_ts
        save_state(cfg.state_path, st)
        self.journal.trade("entry", trade_id=client_oid, symbol=sig.symbol, side=sig.side,
                           order_id=trade["order_id"], price=trade["entry_price"], contracts=trade["contracts"],
                           notional=float(trade["contracts"]) * float(inst.contract_value) * trade["entry_price"],
                           stop=sig.stop, target=target, fee=trade["entry_fee"],
                           details=f"risk {trade['risk_amount']:.2f} ({risk_pct:.2%}), {size.leverage}x"
                                   + (f"; {size.note}" if size.note else ""))
        res = self.rec.verify_tpsl(trade)
        save_state(cfg.state_path, st)
        self.say(f"ENTERED {describe_trade(trade)} · TP/SL check: {res}")
        self.alerter.send(f"📈 ENTRY {sig.symbol} {sig.side} {trade['contracts']} contracts @ "
                          f"{trade['entry_price']:.6g} · SL {sig.stop:.6g} · TP {target:.6g} · risk "
                          f"{trade['risk_amount']:,.2f} USDT ({risk_pct:.2%}) · {size.leverage}x · TP/SL: {res}")

    # -- daily summary -----------------------------------------------------------
    def daily_summary(self, equity: float, day_start: float) -> None:
        today = date_str(self.now_ms)
        if self.state.get("last_daily_summary") == today:
            return
        yesterday = date_str(self.now_ms - DAY_MS)
        y_start = self.state["day_start_equity"].get(yesterday)
        closed_y = [t for t in self.state["closed_trades"] if date_str(t["exit_ts"]) == yesterday]
        msg = (f"📊 Daily summary {yesterday}: equity now {equity:,.2f} "
               f"({(equity / self.cfg.account_size - 1):+.2%} vs start)")
        if y_start:
            msg += f", day P&L {day_start - y_start:+,.2f}"
        msg += (f", trades closed {len(closed_y)} ({sum(t['r_multiple'] for t in closed_y):+.2f}R), "
                f"open {len(self.state['open_trades'])}, losing streak {self.state['consecutive_losses']}"
                f"{', CHALLENGE FAILED' if self.state['failed'] else ''}")
        self.alerter.send(msg)
        if not self.dry_run:
            self.state["last_daily_summary"] = today


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="BloFin demo breakout bot: one run")
    p.add_argument("--dry-run", action="store_true", help="print signals and sizing; send no orders, save no state")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%Y-%m-%dT%H:%M:%SZ")
    logging.Formatter.converter = time.gmtime
    cfg = load_config()
    alerter = Alerter(cfg, dry_run=args.dry_run)
    try:
        client = BlofinDemo(cfg)
        return Bot(cfg, client, dry_run=args.dry_run, alerter=alerter).run()
    except Exception as e:  # noqa: BLE001
        log.error("run failed: %s\n%s", e, traceback.format_exc())
        alerter.send(f"💥 ERROR: run failed: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

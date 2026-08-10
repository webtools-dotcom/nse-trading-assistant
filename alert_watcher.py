"""Pushes exit signals and market-condition changes to Telegram while you are away.

Run alongside telegram_bot.py:
    python alert_watcher.py                 # loop, checks every 20 min during market hours
    python alert_watcher.py --once          # single pass, for Windows Task Scheduler / cron
    python alert_watcher.py --once --force  # ignore the market-hours guard (for testing)

WHAT IT ALERTS ON, and why only these:
  1. Exit signals on open positions - stop, target, time-exit. This is the validated part of
     the system and the only alert that is unambiguously worth interrupting you for.
  2. The daily candidate count crossing into a historically profitable band (11+). Measured
     as the strongest predictor of absolute return - though roughly half of it is market beta,
     so the message says so.

It deliberately does NOT alert on new individual candidates. More entry prompts means more
trades, and on this cost base higher frequency is net-negative.

DEDUPLICATION: alerts fire when a position's STATE CHANGES, not on a timer. Polling every 20
minutes would otherwise send the same 'stop hit' message fifteen times, and it also means a
market holiday - where nothing changes - produces no repeat alerts without needing a holiday
calendar.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from tools import (check_exit_signals, exit_verdict, get_live_price, get_swing_levels_short,
                   get_swing_levels_long, count_candidates, candidate_band)
from notify import ALLOWED, TOKEN, send

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "alert_state.json")
IST = timezone(timedelta(hours=5, minutes=30))   # India has no DST, so a fixed offset is exact
MARKET_OPEN, MARKET_CLOSE = (9, 15), (15, 30)
INTERVAL_MIN = 20
ALERT_BAND_FROM = 11    # candidate count at which the historically profitable bands begin


def _load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def market_is_open(now=None):
    now = now or datetime.now(IST)
    if now.weekday() >= 5:
        return False
    return MARKET_OPEN <= (now.hour, now.minute) <= MARKET_CLOSE


def exit_alerts():
    """[(fingerprint, message)] for positions whose validated exit rule now says EXIT."""
    positions = check_exit_signals()
    if isinstance(positions, str):
        return []

    out = []
    for pos in positions:
        if 'error' in pos:
            continue
        try:
            levels = (get_swing_levels_short(pos['ticker']) if pos['term'] == 'short'
                      else get_swing_levels_long(pos['ticker']))
            live = get_live_price(pos['ticker'])
            current = live if live is not None else levels['current_price']
            stop, target = float(pos['stop_loss']), float(pos['target'])
            code, verdict = exit_verdict(current, stop, target, pos['days_held'], pos['horizon'])
        except Exception as e:
            print(f"[exit] {pos['ticker']}: {e}")
            continue

        if code == 'hold':
            continue
        out.append((
            f"exit:{pos['ticker']}:{code}",
            f"⚠️ {pos['ticker']} — {verdict}\n\n"
            f"Entry Rs{pos['entry_price']} | Now Rs{current} | Stop Rs{stop} | Target Rs{target}\n"
            f"Day {pos['days_held']} of {pos['horizon']}\n"
            f"{'(live quote)' if live is not None else '(CACHED price - live quote failed, verify before acting)'}"))
    return out


def condition_alert():
    n = count_candidates()
    if n is None or n < ALERT_BAND_FROM:
        return None
    hist, label = candidate_band(n)
    # Keyed by date so this can fire once a day, unlike exit alerts which are state-driven.
    return (f"cond:{datetime.now(IST):%Y-%m-%d}:{label}",
            f"📊 {n} candidates passed the filter today — {label}.\n\n"
            f"Historical mean {hist}/trade on days like this (5y, net of costs).\n"
            f"Roughly half of that is market beta, not signal quality — random entries show "
            f"the same pattern. Context, not a trade instruction.")


def run_once(force=False):
    now = datetime.now(IST)
    if not force and not market_is_open(now):
        print(f"{now:%H:%M} IST - market closed, skipping")
        return 0

    state = _load_state()
    alerts = exit_alerts()
    cond = condition_alert()
    if cond:
        alerts.append(cond)

    fired = 0
    seen = set()
    for key, message in alerts:
        seen.add(key)
        if state.get(key):
            continue        # already told you; nothing has changed since
        for chat_id in ALLOWED:
            send(chat_id, message)
        state[key] = now.isoformat()
        fired += 1
        print(f"[SENT] {key}")

    # Clear exit fingerprints that no longer apply, so a position that recovers above its stop
    # can alert again if it breaches a second time.
    for key in [k for k in state if k.startswith('exit:') and k not in seen]:
        del state[key]

    _save_state(state)
    if not fired:
        print(f"{now:%H:%M} IST - checked, nothing new")
    return fired


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="single pass then exit")
    ap.add_argument("--force", action="store_true", help="ignore the market-hours guard")
    ap.add_argument("--interval", type=int, default=INTERVAL_MIN, help="minutes between checks")
    args = ap.parse_args()

    if not TOKEN or not ALLOWED:
        sys.exit("Telegram is not configured - set TELEGRAM_BOT_TOKEN and "
                 "TELEGRAM_ALLOWED_CHAT_ID in .env (see telegram_bot.py).")

    if args.once:
        return run_once(force=args.force)

    print(f"Watcher started - every {args.interval} min during market hours (IST).")
    while True:
        try:
            run_once(force=args.force)
        except Exception as e:
            # Never let one bad pass kill the loop - a dead watcher is silent, and silence
            # looks exactly like 'nothing to report'.
            print(f"[watcher] {type(e).__name__}: {e}")
        time.sleep(args.interval * 60)


if __name__ == "__main__":
    main()

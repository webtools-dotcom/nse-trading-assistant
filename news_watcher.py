"""Continuous corporate-event collector for the whole 748-stock watchlist.

Polls NSE corporate announcements and pushes genuinely material ones to Telegram, enriched
with the tool's own view of the stock. Built to run on a spare Android phone under Termux -
see TERMUX SETUP at the bottom - but it has no platform-specific dependencies and runs the
same on a PC or VPS.

    python news_watcher.py               # loop, polls every 10 min in the active window
    python news_watcher.py --once        # single pass (cron / Termux:Job)
    python news_watcher.py --once --dry  # print what it would send, send nothing

WHY IT RUNS PAST MARKET CLOSE: NSE filings land through the evening - board-meeting outcomes,
management changes, fund raising. Those are exactly the events worth knowing about before the
next open, so the active window is 08:00-23:30 IST rather than market hours.

WHAT IT CANNOT DO, stated plainly: it does not get you information before anyone else. NSE
publishes to everyone simultaneously and algorithms react in milliseconds. The realistic value
is learning about a filing minutes after it lands instead of the next morning - which matters
for positions you already hold. News impact is also the one signal in this project that CANNOT
be backtested (no historical archive), so nothing here carries a validated edge, and the
messages say so.
"""

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

from notify import ALLOWED, TOKEN, send

# NOTE: this file deliberately imports NEITHER pandas NOR nsefin, and does NOT import config.
# Both pull pandas, which on Termux/Android compiles from source and routinely fails. The
# watchlist is read with the csv module and NSE is called over plain HTTP, so the phone needs
# only `requests` and `python-dotenv` - two pure-Python packages that install in seconds.

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "news_state.json")
IST = timezone(timedelta(hours=5, minutes=30))
ACTIVE_WINDOW = (8, 0), (23, 30)     # filings land well after the close
POLL_MIN = 10
MAX_STATE_KEYS = 5000                # keep the dedupe file from growing without bound
LOOKBACK_DAYS = 2


def _load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state):
    if len(state) > MAX_STATE_KEYS:                       # drop oldest by stored timestamp
        keep = sorted(state.items(), key=lambda kv: kv[1])[-MAX_STATE_KEYS:]
        state = dict(keep)
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)
    return state


def in_active_window(now=None):
    now = now or datetime.now(IST)
    if now.weekday() >= 5:
        return False
    start, end = ACTIVE_WINDOW
    return start <= (now.hour, now.minute) <= end


def _fingerprint(row):
    """Stable id for one filing. seq_id is NSE's own and is preferred; the hash is a fallback
    for feeds that omit it, so a re-published item is not re-alerted."""
    seq = str(row.get('seq_id') or '').strip()
    if seq:
        return f"ann:{seq}"
    raw = f"{row.get('symbol')}|{row.get('an_dt')}|{row.get('desc')}"
    return "ann:" + hashlib.sha1(raw.encode('utf-8', 'ignore')).hexdigest()[:16]


# tools.HIGH_SIGNAL_ANNOUNCEMENT_KEYWORDS is deliberately NOT reused here. It feeds a scan you
# read on demand, where breadth is free. Measured against 5 days of real filings it matches 390
# of 2,136 - about 78 push notifications a day, half of them 'Outcome of Board Meeting' and
# routine re-appointments. A notifier that cries wolf 78 times a day gets muted in a week, and
# a muted notifier is worse than none because you think you are covered. Same data, stricter
# bar, because the delivery channel is different.

MATERIAL_KEYWORDS = [
    'merger', 'demerger', 'amalgamation', 'acquisition', 'scheme of arrangement',
    'takeover regulation', 'open offer', 'delisting', 'buyback', 'qip',
    'preferential issue', 'rights issue', 'fund raising', 'credit rating',
]
# Leadership churn matters only at the top. A departing company secretary is not news.
LEADERSHIP_KEYWORDS = ['change in management', 'resignation', 'appointment']
SENIOR_ROLES = ['managing director', 'chief executive', 'ceo', 'chief financial', 'cfo',
                'chairman', 'whole-time director', 'whole time director', 'promoter']
ROUTINE_NOISE = ['re-appointment', 'reappointment', 'auditor', 'company secretary',
                 'compliance officer', 'registrar', 'debenture trustee']
RATING_CHANGE_WORDS = ['downgrade', 'upgrade', 'revised', 'revision', 'watch', 'negative',
                       'default', 'withdraw']


def is_high_signal(row):
    """Returns the matched reasons, or [] to ignore.

    Checks BOTH the category and the filing text: the category is often generic ('General
    Updates') while attchmntText carries the substance - which is why this project fetches it.
    """
    blob = f"{row.get('desc') or ''} {row.get('attchmntText') or ''}".lower()

    hits = [kw for kw in MATERIAL_KEYWORDS if kw in blob]
    # Most rating filings are routine annual reaffirmations at an unchanged grade. Only a
    # CHANGE is news, so require a change word before alerting on one.
    if hits == ['credit rating'] and not any(w in blob for w in RATING_CHANGE_WORDS):
        return []
    if hits:
        return hits

    if any(kw in blob for kw in LEADERSHIP_KEYWORDS):
        if any(noise in blob for noise in ROUTINE_NOISE):
            return []
        roles = [r for r in SENIOR_ROLES if r in blob]
        if roles:
            return [f"leadership change ({roles[0]})"]
    return []


WATCHLIST_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "nse_watchlist_expanded.csv")
NSE_HOME = "https://www.nseindia.com"
NSE_ANNOUNCEMENTS = f"{NSE_HOME}/api/corporate-announcements"
BROWSER_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120 Safari/537.36'),
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': f"{NSE_HOME}/companies-listing/corporate-filings-announcements",
}


def load_watchlist():
    """(symbols, cap_by_symbol) straight from the CSV via the csv module.

    config.py would give the same thing but imports pandas, which is the single hardest
    package to install under Termux. Reading 748 rows needs nothing more than this.
    """
    symbols, caps = set(), {}
    with open(WATCHLIST_CSV, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            sym = (row.get('Symbol') or '').strip()
            if sym:
                symbols.add(sym)
                caps[sym] = (row.get('cap_bucket') or 'Unknown').strip()
    return symbols, caps


def fetch_announcements(days_back=LOOKBACK_DAYS):
    """Recent announcements for watchlist symbols, as plain dict rows.

    Calls NSE's JSON endpoint directly. NSE rejects requests without a browser-like session,
    so this warms cookies on the homepage and the filings page first - that handshake is the
    only reason a library was needed here.
    """
    symbols, _ = load_watchlist()
    to_date = datetime.now()
    from_date = to_date - timedelta(days=days_back)

    s = requests.Session()
    s.headers.update(BROWSER_HEADERS)
    s.get(NSE_HOME, timeout=20)
    s.get(BROWSER_HEADERS['Referer'], timeout=20)
    r = s.get(NSE_ANNOUNCEMENTS, timeout=30, params={
        'index': 'equities',
        'from_date': from_date.strftime('%d-%m-%Y'),
        'to_date': to_date.strftime('%d-%m-%Y')})
    r.raise_for_status()

    data = r.json()
    rows = data if isinstance(data, list) else data.get('data', [])
    return [row for row in rows if (row.get('symbol') or '').strip() in symbols]


def _context_for(symbol):
    """The tool's own view of the stock, so the alert is not just a headline.

    Imported lazily and allowed to fail. tools.py pulls in xgboost, scikit-learn, yfinance and
    ta, and needs the 55MB price cache - none of which install cleanly on Termux/Android. On a
    phone this degrades to the cap tier alone and the collector still does its job; on the PC
    you get the full context. Every number comes from a tool call - nothing is inferred, since
    an alert that invents a price is worse than no alert.
    """
    ticker = f"{symbol}.NS"
    lines = [f"Cap tier: {load_watchlist()[1].get(symbol, 'Unknown')}"]
    try:
        from tools import get_swing_levels_short
        from trade_journal import get_open_positions
    except Exception:
        lines.append("(running lite - no local price cache on this device)")
        return "\n".join(lines)

    try:
        held = get_open_positions()
        if isinstance(held, str) and f"{ticker} " in held:
            lines.append("YOU HOLD THIS - check it against your stop before the next open.")
    except Exception:
        pass
    try:
        lv = get_swing_levels_short(ticker)
        lines.append(f"Last close Rs{lv['current_price']} | RSI {lv['rsi']} | "
                     f"1yr {lv.get('change_1yr_pct')}% [{lv.get('trend_tier')}]")
        if lv['rsi'] < 30:
            lines.append("Currently passes the RSI<30 entry filter.")
    except Exception:
        lines.append("(no cached technicals - run refresh_cache.py)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------
# LLM triage. Optional: without GEMINI_API_KEY everything still works, it just sends the
# raw filing text as before. The model NEVER decides whether to trade and never produces a
# number - it only compresses legalese into a sentence and rates how material the filing is,
# which is what turns ~18 daily messages into 2-4 pushes plus one evening digest.
# ---------------------------------------------------------------------------------

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
DIGEST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "news_digest.json")
DIGEST_HOUR = 21          # evening round-up of everything not pushed immediately

TRIAGE_PROMPT = """You triage Indian NSE corporate filings for one retail swing trader.

Filing for {symbol}:
Category: {desc}
Text: {text}

Reply with ONLY a JSON object, no markdown fence:
{{"materiality": "HIGH|MEDIUM|LOW",
  "headline": "<one plain-English sentence, max 20 words, what actually happened>",
  "why": "<one sentence: who this affects and why it might matter. No prediction.>"}}

Rules you must follow:
- HIGH = changes what the company is or who runs it: merger, demerger, acquisition of a
  material business, open offer, delisting, buyback, promoter/CEO/MD/CFO departure, credit
  rating downgrade, fraud or regulatory action.
- MEDIUM = real but smaller: subsidiary-level deals, fund raising, stake changes, a new
  senior appointment.
- LOW = procedural or routine: incorporations, small stake tweaks, administrative updates.
- NEVER predict the share price, never say buy/sell/hold, never say bullish or bearish.
- Describe ONLY what the filing text states. If the text is too vague to tell, say so in
  "headline" and use LOW.
- No hype. Plain words. A tired person reads this on a phone at 9pm."""


def analyze_group(symbol, filings, timeout=45):
    """Triage a company's filings for one day as a single unit.

    Cheaper than one call per filing, and better: the model sees that a CEO change and a
    USD 303m acquisition were announced together rather than judging each in isolation.
    """
    if not GEMINI_KEY:
        return None
    blob = "\n\n".join(
        f"[{r.get('an_dt')}] {r.get('desc')}: {(r.get('attchmntText') or '')[:1200]}"
        for r in filings[:5])
    return _triage(symbol, f"{len(filings)} filing(s) today", blob, timeout)


def analyze_filing(row, timeout=45):
    """{'materiality','headline','why'} or None if unavailable.

    Any failure returns None and the caller falls back to raw text - a filing must never be
    dropped because the model was slow, rate-limited or unreachable.
    """
    if not GEMINI_KEY:
        return None
    return _triage(row.get('symbol'), row.get('desc'),
                   (row.get('attchmntText') or row.get('desc') or '')[:3000], timeout)


def _triage(symbol, desc, text, timeout=45):
    prompt = TRIAGE_PROMPT.format(symbol=symbol, desc=desc, text=text)
    try:
        r = requests.post(GEMINI_URL, params={'key': GEMINI_KEY}, timeout=timeout,
                          json={'contents': [{'parts': [{'text': prompt}]}],
                                'generationConfig': {'temperature': 0, 'maxOutputTokens': 300}})
        r.raise_for_status()
        raw = r.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        raw = raw.removeprefix('```json').removeprefix('```').removesuffix('```').strip()
        out = json.loads(raw)
        if out.get('materiality') not in ('HIGH', 'MEDIUM', 'LOW'):
            return None
        return out
    except Exception as e:
        print(f"[triage] {symbol}: {type(e).__name__}")
        return None


def _load_digest():
    try:
        with open(DIGEST_FILE) as f:
            return json.load(f)
    except Exception:
        return {'date': '', 'sent': False, 'items': []}


def _save_digest(d):
    os.makedirs(os.path.dirname(DIGEST_FILE), exist_ok=True)
    with open(DIGEST_FILE, 'w') as f:
        json.dump(d, f)


def maybe_send_digest(now, dry=False):
    """One evening message with everything that was not urgent enough to interrupt you."""
    d = _load_digest()
    today = f"{now:%Y-%m-%d}"
    if d.get('date') != today:
        return 0
    if d.get('sent') or now.hour < DIGEST_HOUR or not d.get('items'):
        return 0

    lines = [f"🌙 Evening digest — {len(d['items'])} filing(s) worth knowing, none urgent\n"]
    for it in d['items']:
        lines.append(f"• [{it['materiality']}] {it['symbol']}: {it['headline']}")
    lines.append("\nNone of these needed interrupting you. Nothing here is backtested — "
                 "if one is a stock you hold, check it against your stop on the PC.")
    msg = "\n".join(lines)

    if dry:
        print("-" * 60); print(msg)
    else:
        for chat_id in ALLOWED:
            send(chat_id, msg)
    d['sent'] = True
    _save_digest(d)
    return 1


def _queue_for_digest(now, symbol, materiality, headline):
    d = _load_digest()
    today = f"{now:%Y-%m-%d}"
    if d.get('date') != today:
        d = {'date': today, 'sent': False, 'items': []}
    d['items'].append({'symbol': symbol, 'materiality': materiality, 'headline': headline})
    _save_digest(d)


def build_alerts(rows, state):
    """One alert per COMPANY per pass, not per filing.

    A single corporate event usually arrives as several filings within minutes - Nazara
    published a CEO resignation, a CEO appointment, a press release and a warrant conversion
    on one evening, which was four separate notifications for one news day. Grouping by symbol
    collapses those into one message and one triage call.
    """
    by_symbol = {}
    for row in rows:
        fp = _fingerprint(row)
        if fp in state or not is_high_signal(row):
            continue
        by_symbol.setdefault(row.get('symbol'), []).append((fp, row))

    out = []
    for symbol, items in by_symbol.items():
        fps = [fp for fp, _ in items]
        filings = [r for _, r in items]
        # Newest first - the most recent filing is usually the substantive one.
        filings.sort(key=lambda r: str(r.get('an_dt') or ''), reverse=True)

        intel = analyze_group(symbol, filings)
        materiality = intel['materiality'] if intel else 'HIGH'   # no triage -> assume urgent

        lines = [f"📰 {symbol}.NS — {intel['headline'] if intel else filings[0].get('desc')}"]
        if intel:
            lines.append(intel['why'])
        lines.append("")
        lines.append(f"[{materiality}] {len(filings)} filing(s) today:")
        for r in filings:
            lines.append(f"  · {r.get('an_dt')} — {r.get('desc')}")

        detail = (filings[0].get('attchmntText') or '').strip()
        if len(detail) > 600:
            detail = detail[:600] + "..."
        lines += ["", f"Latest filing text: {detail or '(none published)'}",
                  "", _context_for(symbol), "",
                  "Announcement signals are NOT backtested - there is no historical news "
                  "archive wired in yet. Direction is not predictable from a filing. This is a "
                  "prompt to look, not a signal to trade."]

        out.append((fps, "\n".join(lines), materiality,
                    intel['headline'] if intel else filings[0].get('desc'), symbol))
    return out


def run_once(dry=False, force=False, prime=False):
    now = datetime.now(IST)
    if not force and not in_active_window(now):
        print(f"{now:%H:%M} IST - outside active window, skipping")
        return 0
    try:
        rows = fetch_announcements()
    except Exception as e:
        print(f"[fetch] {type(e).__name__}: {e}")
        return 0

    state = _load_state()
    alerts = build_alerts(rows, state)
    pushed = sum(1 for a in alerts if a[2] == 'HIGH')
    print(f"{now:%H:%M} IST - {len(rows)} watchlist filings, {len(alerts)} new & high-signal "
          f"({pushed} urgent, {len(alerts) - pushed} queued for the evening digest)")

    for fps, msg, materiality, headline, symbol in alerts:
        if prime:
            pass                      # mark seen, send nothing - see --prime
        elif materiality == 'HIGH':
            if dry:
                print("-" * 60)
                print(msg)
            else:
                for chat_id in ALLOWED:
                    send(chat_id, msg)
        else:
            # Real but not worth a buzz. Held back so the phone stays quiet and readable.
            _queue_for_digest(now, symbol, materiality, headline)
        for fp in fps:
            state[fp] = now.isoformat()

    if prime:
        print(f"Primed: {len(alerts)} existing filing(s) marked as seen. Only NEW ones "
              f"from here will be sent.")
    else:
        maybe_send_digest(now, dry=dry)
    if not dry:
        _save_state(state)
    return len(alerts)


def whoami():
    """Prints the chat_id of whoever has messaged the bot. Lives here as well as in
    telegram_bot.py because the phone deployment only carries these few files."""
    import requests
    data = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", timeout=30).json()
    found = False
    for u in data.get("result", []):
        chat = (u.get("message") or u.get("edited_message") or {}).get("chat") or {}
        if chat.get("id"):
            found = True
            print(f"TELEGRAM_ALLOWED_CHAT_ID={chat['id']}   ({chat.get('username') or chat.get('first_name')})")
    if not found:
        print("No messages yet. Open Telegram, send your bot any message, then run this again.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--whoami", action="store_true", help="print your Telegram chat id")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry", action="store_true", help="print instead of sending")
    ap.add_argument("--prime", action="store_true",
                    help="mark all current filings as seen WITHOUT sending - run this once "
                         "before going live so the backlog does not arrive as a burst")
    ap.add_argument("--force", action="store_true", help="ignore the active-window guard")
    ap.add_argument("--interval", type=int, default=POLL_MIN)
    args = ap.parse_args()

    if args.whoami:
        if not TOKEN:
            sys.exit("TELEGRAM_BOT_TOKEN missing from .env - get one from @BotFather first.")
        return whoami()

    if not args.dry and (not TOKEN or not ALLOWED):
        sys.exit("Telegram not configured - set TELEGRAM_BOT_TOKEN and "
                 "TELEGRAM_ALLOWED_CHAT_ID in .env, or use --dry.")

    if args.prime:
        return run_once(dry=False, force=True, prime=True)

    if args.once:
        return run_once(dry=args.dry, force=args.force)

    print(f"News watcher started - every {args.interval} min, "
          f"{ACTIVE_WINDOW[0][0]:02d}:00-{ACTIVE_WINDOW[1][0]:02d}:{ACTIVE_WINDOW[1][1]:02d} IST")
    while True:
        try:
            run_once(dry=args.dry, force=args.force)
        except Exception as e:
            print(f"[watcher] {type(e).__name__}: {e}")   # a dead loop is silent, and silence
        time.sleep(args.interval * 60)                    # looks like 'nothing happened'


if __name__ == "__main__":
    main()


# TERMUX SETUP (spare Android phone)
# ---------------------------------------------------------------------------------
#   pkg update && pkg install python
#   pip install requests python-dotenv
#
# That is the whole dependency list. NO pandas, NO numpy, NO nsefin - they compile
# from source on Android and routinely fail, which is exactly why this file talks to
# NSE over plain HTTP and reads the watchlist with the csv module instead.
#
# Copy these 5 files into ~/ta/ :
#   news_watcher.py  notify.py  nse_watchlist_expanded.csv  .env
#   (config.py is NOT needed - the watchlist is read directly from the CSV)
#
#   termux-wake-lock                      # stop Android sleeping the process
#   cd ~/ta && python news_watcher.py --once --dry --force   # test, sends nothing
#   python news_watcher.py --prime        # mark the backlog seen, send nothing
#   python news_watcher.py                # go live
#
# Android will still kill background processes unless you also:
#   - Settings > Apps > Termux > Battery > Unrestricted
#   - disable adaptive battery for Termux
#   - keep the phone on charge (a permanently-charged battery degrades; expect that)
#
# Survive reboots: install Termux:Boot, then
#   ~/.termux/boot/start-watcher.sh:
#       #!/data/data/com.termux/files/usr/bin/sh
#       termux-wake-lock
#       cd ~/ta && python news_watcher.py
#
# Honest expectation: this is less reliable than a PC or a small VPS. Android will
# occasionally kill it regardless of settings, and a watcher that has silently died
# looks exactly like a quiet news day. Check it is alive before trusting its silence.

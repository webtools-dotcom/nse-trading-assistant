"""Telegram front-end for the trading agent - the same tool loop as the CLI, on your phone.

SETUP
  1. Message @BotFather on Telegram -> /newbot -> copy the token.
  2. Message your new bot once (anything), then run:  python telegram_bot.py --whoami
     It prints the chat_id of whoever messaged it.
  3. Put both in .env:
         TELEGRAM_BOT_TOKEN=123456:ABC...
         TELEGRAM_ALLOWED_CHAT_ID=123456789
  4. python telegram_bot.py

SECURITY: a Telegram bot is reachable by ANYONE who finds its handle. Without the chat-id
whitelist below, a stranger could ask it for your open positions, capital and P&L. The bot
refuses every message from an unlisted chat and logs the attempt. Do not remove that check to
"share it with a friend" - run a second bot instead.

Deliberately dependency-free: plain HTTP long-polling via requests, which is already a
dependency. python-telegram-bot would add an async framework for what is one GET in a loop.
"""

import sys
import time
import traceback

import requests

from agent import TradingAgent
from notify import API, ALLOWED, TG_LIMIT, TOKEN, _post, send
from tools import get_exit_check_text, get_open_positions, scan_watchlist_text_short

POLL_TIMEOUT = 30

HELP = (
    "NSE trading assistant.\n\n"
    "Just type normally - 'thoughts on IRFC at 130?', 'scan for setups', "
    "'size 1% risk on BBOX with 2 lakh'.\n\n"
    "Shortcuts (no AI call, instant):\n"
    "  /exits     - check open positions against stop/target/time\n"
    "  /positions - list open positions\n"
    "  /scan      - raw short-term scan\n"
    "  /reset     - clear conversation memory\n"
)


def handle(agent, chat_id, text):
    cmd = text.strip().lower().split()[0] if text.strip() else ""
    if cmd in ("/start", "/help"):
        return HELP
    if cmd == "/reset":
        agent.reset()
        return "Conversation memory cleared."
    # Deterministic shortcuts: the things checked most often should not cost an API call,
    # and should not pass through a model that could paraphrase a stop level.
    if cmd == "/exits":
        return get_exit_check_text()
    if cmd == "/positions":
        return get_open_positions()
    if cmd == "/scan":
        return scan_watchlist_text_short(limit=10)
    return agent.ask(text)


def whoami():
    """Prints the chat_id of anyone who has messaged the bot - for first-time setup."""
    data = requests.get(f"{API}/getUpdates", timeout=30).json()
    seen = {}
    for u in data.get("result", []):
        msg = u.get("message") or u.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            seen[chat["id"]] = chat.get("username") or chat.get("first_name") or "?"
    if not seen:
        print("No messages found. Send your bot a message first, then re-run.")
    for cid, who in seen.items():
        print(f"chat_id={cid}  ({who})")


def main():
    if not TOKEN:
        sys.exit("TELEGRAM_BOT_TOKEN missing from .env - see the setup notes at the top of this file.")
    if "--whoami" in sys.argv:
        return whoami()
    if not ALLOWED:
        sys.exit("TELEGRAM_ALLOWED_CHAT_ID missing from .env. Refusing to start an open bot - "
                 "anyone who found it could read your positions. Run --whoami to get your id.")

    agent = TradingAgent()
    me = _post("getMe").get("result", {})
    print(f"Bot @{me.get('username', '?')} listening. Allowed chats: {', '.join(ALLOWED)}")

    offset = None
    while True:
        try:
            r = requests.get(f"{API}/getUpdates",
                             params={"timeout": POLL_TIMEOUT, "offset": offset},
                             timeout=POLL_TIMEOUT + 15).json()
        except Exception as e:
            print(f"[poll] {e}")
            time.sleep(5)
            continue

        for update in r.get("result", []):
            offset = update["update_id"] + 1
            msg = update.get("message") or update.get("edited_message")
            if not msg or "text" not in msg:
                continue
            chat_id = str(msg["chat"]["id"])
            text = msg["text"]

            if chat_id not in ALLOWED:
                print(f"[BLOCKED] chat_id={chat_id} user={msg['chat'].get('username')} "
                      f"said: {text[:80]!r}")
                send(chat_id, "Not authorised.")
                continue

            print(f"> {text[:100]}")
            _post("sendChatAction", chat_id=chat_id, action="typing")
            try:
                send(chat_id, handle(agent, chat_id, text))
            except Exception as e:
                # A crash here would kill the loop and silently stop every future alert, so
                # the error goes to the user rather than to a terminal nobody is watching.
                traceback.print_exc()
                send(chat_id, f"Something broke handling that: {type(e).__name__}: {e}\n"
                              f"The bot is still running. Try /reset if it persists.")


if __name__ == "__main__":
    main()

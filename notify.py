"""Telegram delivery. Deliberately dependency-light: requests + dotenv, nothing else.

Split out of telegram_bot.py so that news_watcher.py can send messages WITHOUT importing
tools.py, which pulls in xgboost, scikit-learn, yfinance and ta. Those have no prebuilt
Termux/aarch64 wheels and compile from source on Android, which is what makes the difference
between the collector running on a spare phone and not running at all.
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED = {c.strip() for c in (os.getenv("TELEGRAM_ALLOWED_CHAT_ID") or "").split(",") if c.strip()}
API = f"https://api.telegram.org/bot{TOKEN}"
TG_LIMIT = 4096          # Telegram's hard per-message cap


def _post(method, **payload):
    try:
        r = requests.post(f"{API}/{method}", json=payload, timeout=60)
        return r.json()
    except Exception as e:
        print(f"[telegram] {method} failed: {e}")
        return {}


def send(chat_id, text):
    """Telegram rejects anything over 4096 chars, and scan output routinely exceeds it.
    Splits on line boundaries so a stop-loss figure never lands mid-number."""
    text = text or "(empty response)"
    while text:
        if len(text) <= TG_LIMIT:
            chunk, text = text, ""
        else:
            cut = text.rfind("\n", 0, TG_LIMIT)
            cut = cut if cut > TG_LIMIT // 2 else TG_LIMIT
            chunk, text = text[:cut], text[cut:].lstrip("\n")
        _post("sendMessage", chat_id=chat_id, text=chunk, disable_web_page_preview=True)


def broadcast(text):
    """Send to every whitelisted chat."""
    for chat_id in ALLOWED:
        send(chat_id, text)

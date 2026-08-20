"""Shared presentation for the Streamlit suite: the Bloomberg/TradingView terminal theme,
shared navigation, widgets, and the running market ticker strip, so all pages share the exact
same skin and components.

Pure display - no trading/backtest logic.
"""

import os
import html
from datetime import datetime, timezone, timedelta

import streamlit as st
import yfinance as yf

from config import BASE_DIR
from cache_manager import load_market_ui_cache

IST = timezone(timedelta(hours=5, minutes=30))

TICKER_STRIP = [
    ("^NSEI", "NIFTY 50"), ("^BSESN", "SENSEX"), ("RELIANCE.NS", "RELIANCE"),
    ("HDFCBANK.NS", "HDFCBANK"), ("TCS.NS", "TCS"), ("INFY.NS", "INFY"),
    ("ICICIBANK.NS", "ICICIBANK"), ("BHARTIARTL.NS", "BHARTIARTL"),
]


def inject_theme():
    """Load the terminal CSS theme into the current page."""
    try:
        with open(os.path.join(BASE_DIR, "theme.css"), encoding="utf-8") as f:
            st.markdown(f.read(), unsafe_allow_html=True)
    except OSError:
        pass


def render_nav(active=""):
    """Shared top-nav row for all pages in the suite."""
    cols = st.columns([1, 1, 1.1, 1, 1, 1.1, 3.8])
    cols[0].page_link("Home.py", label="Home", icon="📰")
    cols[1].page_link("pages/2_📊_Market_Recap.py", label="Recap", icon="📊")
    cols[2].page_link("pages/3_⭐_Watchlist.py", label="Watchlist", icon="⭐")
    cols[3].page_link("pages/4_📒_Journal.py", label="Journal", icon="📒")
    cols[4].page_link("pages/5_📚_Learn.py", label="Learn", icon="📚")
    cols[5].page_link("pages/1_📈_Assistant.py", label="Assistant", icon="📈")


def mood_score(nifty_chg, breadth_pct, above_200):
    """One market-mood number in [-1, 1] from data already on hand (no API): the day's index
    move, market breadth, and Nifty vs its 200-day SMA. -1 = risk-off, +1 = risk-on."""
    parts = []
    if nifty_chg is not None:
        parts.append(max(-1.0, min(1.0, nifty_chg / 1.2)))   # ~±1.2% pins the gauge
    if breadth_pct is not None:
        parts.append((breadth_pct - 50) / 50.0)
    if above_200 is not None:
        parts.append(0.3 if above_200 else -0.3)
    return sum(parts) / len(parts) if parts else 0.0


def mood_label(score):
    """(label, color) for a mood score."""
    if score >= 0.25:
        return "RISK-ON", "var(--tv-green)"
    if score <= -0.25:
        return "RISK-OFF", "var(--tv-red)"
    return "NEUTRAL", "var(--accent-amber)"


@st.cache_data(ttl=300, show_spinner=False)
def ltp(ticker):
    """Live or cached last traded price for a ticker."""
    try:
        from data_fetcher import get_live_price
        return get_live_price(ticker)
    except Exception:
        return None


def tile(label, value, sub="", value_color=None):
    """Shared stat-tile HTML snippet."""
    style = f' style="color:{value_color}"' if value_color else ""
    return (f'<div class="stat-tile"><div class="stat-label">{label}</div>'
            f'<div class="stat-value"{style}>{value}</div>'
            + (f'<div class="stat-sub">{sub}</div>' if sub else "") + '</div>')


def pnl_color(v):
    """Green for positive, red for negative."""
    return "var(--tv-green)" if v >= 0 else "var(--tv-red)"


def goto_assistant(ticker):
    """Hand a ticker to the Assistant page and switch to it (click-through)."""
    st.session_state["assistant_ticker"] = ticker
    st.switch_page("pages/1_📈_Assistant.py")


def ticker_buttons(tickers, key_prefix, label="Analyze in Assistant →"):
    """A row of click-through buttons; each opens the Assistant pre-loaded with that ticker."""
    tickers = list(dict.fromkeys(tickers))  # de-dupe, keep order
    if not tickers:
        return
    st.markdown(f'<div class="stat-sub" style="margin:8px 0 3px;">{label}</div>',
                unsafe_allow_html=True)
    for col, tk in zip(st.columns(min(len(tickers), 6)), tickers[:6]):
        if col.button(f"🔍 {tk.replace('.NS', '')}", key=f"{key_prefix}_{tk}",
                      use_container_width=True):
            goto_assistant(tk)


def _live_quote(symbol):
    info = yf.Ticker(symbol).fast_info
    last, prev = info["last_price"], info["previous_close"]
    return last, (last - prev) / prev * 100


def market_snapshot():
    """Index/stock % moves for the ticker strip + top headline. Prefers today's precomputed
    cache from refresh_cache.py; falls back to a live yfinance call per missing symbol."""
    cached = load_market_ui_cache()
    cq = (cached or {}).get("quotes", {})
    quotes = []
    for symbol, label in TICKER_STRIP:
        if symbol in cq:
            quotes.append({"label": label, "price": cq[symbol]["price"], "chg_pct": cq[symbol]["chg_pct"]})
            continue
        try:
            last, chg_pct = _live_quote(symbol)
            quotes.append({"label": label, "price": last, "chg_pct": chg_pct})
        except Exception:
            continue
    headline = (cached or {}).get("headline")
    return quotes, headline


def render_market_strip():
    """The continuously scrolling ticker marquee + the NIFTY/SENSEX meta bar."""
    quotes, headline = market_snapshot()
    if not quotes:
        return
    chips = "".join(
        f'<span class="tick {"up" if q["chg_pct"] >= 0 else "down"}">'
        f'<span class="tick-sym">{q["label"]}</span>'
        f'<span class="tick-price">₹{q["price"]:,.1f}</span>'
        f'<span class="tick-pct">{"▲" if q["chg_pct"] >= 0 else "▼"} {abs(q["chg_pct"]):.2f}%</span>'
        f'</span>'
        for q in quotes
    )
    st.markdown(f'<div class="tick-strip"><div class="tick-track">{chips}{chips}</div></div>',
                unsafe_allow_html=True)
    nifty = next((q for q in quotes if q["label"] == "NIFTY 50"), None)
    sensex = next((q for q in quotes if q["label"] == "SENSEX"), None)
    if nifty and sensex:
        date_str = datetime.now(IST).strftime("%d %b %Y · %I:%M %p IST")
        parts = [f"NIFTY 50: {nifty['price']:,.1f} ({nifty['chg_pct']:+.2f}%)",
                 f"SENSEX: {sensex['price']:,.1f} ({sensex['chg_pct']:+.2f}%)",
                 f"Snapshot: {date_str}"]
        headline_html = (f'<span class="news-tag">TOP</span> '
                         f'<span class="news-text">{html.escape(headline)}</span>') if headline else ''
        st.markdown(
            f'<div class="market-meta-bar"><span class="market-summary">{"  │  ".join(parts)}</span>'
            + (f'<span class="market-meta-sep">│</span> {headline_html}' if headline else '')
            + '</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    assert mood_label(mood_score(2.0, 80, True))[0] == "RISK-ON"
    assert mood_label(mood_score(-2.0, 20, False))[0] == "RISK-OFF"
    assert mood_label(mood_score(0.0, 50, None))[0] == "NEUTRAL"
    assert -1.0 <= mood_score(5.0, 100, True) <= 1.0        # clamped
    assert mood_score(None, None, None) == 0.0              # no data -> neutral
    assert pnl_color(10) == "var(--tv-green)"
    assert pnl_color(-5) == "var(--tv-red)"
    t = tile("TEST", "100", "sub")
    assert "stat-tile" in t and "TEST" in t
    print("ui_common self-check OK")

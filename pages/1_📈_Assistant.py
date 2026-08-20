import streamlit as st
import os
import json
import uuid
import html
from datetime import datetime, timezone, timedelta
import yfinance as yf
from agent import TradingAgent
from cache_manager import load_market_ui_cache
from ui_common import inject_theme, render_nav

IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_WATCHLIST = [
    "RELIANCE.NS",
    "HDFCBANK.NS",
    "TCS.NS",
    "INFY.NS",
    "ICICIBANK.NS",
    "BHARTIARTL.NS",
    "SBIN.NS",
    "ITC.NS"
]

TICKER_STRIP = [
    ("^NSEI", "NIFTY 50"),
    ("^BSESN", "SENSEX"),
    ("RELIANCE.NS", "RELIANCE"),
    ("HDFCBANK.NS", "HDFCBANK"),
    ("TCS.NS", "TCS"),
    ("INFY.NS", "INFY"),
    ("ICICIBANK.NS", "ICICIBANK"),
    ("BHARTIARTL.NS", "BHARTIARTL")
]


def _live_quote(symbol):
    info = yf.Ticker(symbol).fast_info
    last, prev = info["last_price"], info["previous_close"]
    return last, (last - prev) / prev * 100


@st.cache_data(ttl=300)
def market_snapshot():
    """Index/stock % moves for the ticker strip + banner, and top Nifty-linked headline.
    Reads today's precomputed snapshot from refresh_cache.py when available (instant); any
    symbol missing from it - or the whole thing, if refresh_cache hasn't run today - falls
    back to a live yfinance call, same as before this cache existed."""
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

    if cached:
        headline = cached.get("headline")
    else:
        headline = None
        try:
            news = yf.Ticker("^NSEI").news
            if news:
                headline = news[0].get("title") or news[0].get("content", {}).get("title")
        except Exception:
            pass

    return quotes, headline


@st.cache_data(ttl=300)
def get_watchlist_quotes(tickers_tuple):
    """Price and % change for watchlist stocks. Cache-first (see market_snapshot), live
    fallback per-symbol for anything the daily snapshot doesn't cover (e.g. a ticker the
    user just added)."""
    cached = load_market_ui_cache()
    cq = (cached or {}).get("quotes", {})

    data = []
    for symbol in tickers_tuple:
        clean = symbol.replace(".NS", "").replace(".BO", "")
        if symbol in cq:
            data.append({"symbol": symbol, "clean": clean,
                         "price": cq[symbol]["price"], "chg_pct": cq[symbol]["chg_pct"]})
            continue
        try:
            last, chg_pct = _live_quote(symbol)
            data.append({"symbol": symbol, "clean": clean, "price": last, "chg_pct": chg_pct})
        except Exception:
            data.append({"symbol": symbol, "clean": clean, "price": 0.0, "chg_pct": 0.0})
    return data


def _mood(chg_pct):
    if abs(chg_pct) < 0.3:
        return "Flat"
    if abs(chg_pct) < 1:
        return "Up" if chg_pct > 0 else "Down"
    return "Surging" if chg_pct > 0 else "Slumping"


def render_market_strip():
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
        parts = [
            f"NIFTY 50: {nifty['price']:,.1f} ({nifty['chg_pct']:+.2f}%)",
            f"SENSEX: {sensex['price']:,.1f} ({sensex['chg_pct']:+.2f}%)",
            f"EOD Snapshot: {date_str}"
        ]
        summary_text = "  │  ".join(parts)
        headline_html = f'<span class="news-tag">EOD NEWS</span> <span class="news-text">{html.escape(headline)}</span>' if headline else ''
        st.markdown(f"""
        <div class="market-meta-bar">
            <span class="market-summary">{summary_text}</span>
            {f'<span class="market-meta-sep">│</span> <span class="market-headline">{headline_html}</span>' if headline else ''}
        </div>
        """, unsafe_allow_html=True)


st.set_page_config(
    page_title="NSE After-Market Swing Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)
inject_theme()
render_nav("assistant")

# Design System: TradingView Pro & Bloomberg Terminal Standard (Pure Charcoal + Bloomberg Amber)
st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">

<style>
:root {
    /* Pure Neutral TradingView & Bloomberg Palette (Zero Purple/Indigo) */
    --bg-base: #0C0D10;
    --bg-panel: #131722;
    --bg-panel-elevated: #1E222D;
    --bg-surface-hover: #262B38;
    --border-subtle: #2A2E39;
    --border-active: #363C4E;
    
    /* Terminal Signatures */
    --accent-amber: #FFA028;
    --accent-amber-subtle: rgba(255, 160, 40, 0.12);
    --accent-amber-border: rgba(255, 160, 40, 0.3);
    
    /* TradingView Standard Gain & Loss */
    --tv-green: #089981;
    --tv-green-bg: rgba(8, 153, 129, 0.14);
    --tv-red: #F23645;
    --tv-red-bg: rgba(242, 54, 69, 0.14);
    
    /* Contrast Text Hierarchy */
    --text-primary: #F0F3FA;
    --text-secondary: #9B9EA4;
    --text-muted: #6A6D78;
}

* {
    font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

/* Hide Streamlit default top-right toolbar (Deploy button + 3 dots menu) */
[data-testid="stToolbar"], 
#MainMenu, 
footer,
div[data-testid="stDecoration"] { 
    display: none !important;
    visibility: hidden !important; 
}

/* Header container: keep transparent and non-interfering */
header[data-testid="stHeader"] {
    background: transparent !important;
    height: 3rem !important;
    z-index: 9999 !important;
}

/* Sidebar collapsed toggle button: guaranteed pinned visibility */
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"] {
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    position: fixed !important;
    top: 12px !important;
    left: 14px !important;
    z-index: 9999999 !important;
    background: #181C27 !important;
    border: 1px solid var(--accent-amber) !important;
    border-radius: 6px !important;
    color: var(--accent-amber) !important;
    padding: 6px 10px !important;
    box-shadow: 0 0 12px rgba(255, 160, 40, 0.3) !important;
    cursor: pointer !important;
    transition: all 0.15s ease !important;
}

[data-testid="collapsedControl"]:hover,
[data-testid="stSidebarCollapsedControl"]:hover {
    background: #222838 !important;
    box-shadow: 0 0 16px rgba(255, 160, 40, 0.5) !important;
    transform: scale(1.05);
}

[data-testid="collapsedControl"] svg,
[data-testid="stSidebarCollapsedControl"] svg {
    display: block !important;
    visibility: visible !important;
    fill: var(--accent-amber) !important;
    stroke: var(--accent-amber) !important;
    color: var(--accent-amber) !important;
    width: 18px !important;
    height: 18px !important;
}

.stApp {
    background-color: var(--bg-base);
    color: var(--text-primary);
}

.block-container {
    padding-top: 2rem !important;
    padding-bottom: 2.5rem !important;
    max-width: 1060px;
}

/* Terminal Header */
.terminal-header {
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
    padding: 12px 18px;
    margin-bottom: 0.5rem;
}

.terminal-title-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.terminal-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.2rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 10px;
}

.terminal-logo {
    color: var(--accent-amber);
    font-size: 1.15rem;
}

.terminal-badge {
    font-size: 0.65rem;
    font-family: 'JetBrains Mono', monospace;
    font-weight: 600;
    color: var(--accent-amber);
    background: var(--accent-amber-subtle);
    border: 1px solid var(--accent-amber-border);
    padding: 2px 6px;
    border-radius: 4px;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}

.terminal-eod-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--text-secondary);
    background: var(--bg-panel-elevated);
    border: 1px solid var(--border-subtle);
    padding: 4px 10px;
    border-radius: 4px;
    letter-spacing: 0.04em;
}

.terminal-sub {
    font-size: 0.76rem;
    color: var(--text-muted);
    margin-top: 4px;
    letter-spacing: 0.01em;
}

/* Ticker Marquee Strip */
.tick-strip {
    overflow: hidden;
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
    padding: 7px 0;
    margin-top: 0.35rem;
    mask-image: linear-gradient(to right, transparent, black 4%, black 96%, transparent);
    -webkit-mask-image: linear-gradient(to right, transparent, black 4%, black 96%, transparent);
}

.tick-track {
    display: inline-flex;
    white-space: nowrap;
    animation: scroll-left 32s linear infinite;
}

.tick {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 2px 12px;
    margin: 0 4px;
    border-radius: 4px;
    background: var(--bg-panel-elevated);
    border: 1px solid var(--border-subtle);
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.78rem;
}

.tick-sym {
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: 0.02em;
}

.tick-price {
    color: #D1D4DC;
    font-weight: 500;
}

.tick.up .tick-pct {
    color: var(--tv-green);
    background: var(--tv-green-bg);
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 0.72rem;
    font-weight: 700;
}

.tick.down .tick-pct {
    color: var(--tv-red);
    background: var(--tv-red-bg);
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 0.72rem;
    font-weight: 700;
}

@keyframes scroll-left {
    from { transform: translateX(0); }
    to { transform: translateX(-50%); }
}

.market-meta-bar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    color: var(--text-secondary);
    padding: 5px 2px;
    margin-top: 3px;
}

.market-meta-sep {
    color: var(--border-subtle);
}

.news-tag {
    background: var(--accent-amber-subtle);
    color: var(--accent-amber);
    font-size: 0.65rem;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 3px;
    border: 1px solid var(--accent-amber-border);
}

.news-text {
    color: #D1D4DC;
    font-family: 'Plus Jakarta Sans', sans-serif;
}

/* Sidebar Styling */
section[data-testid="stSidebar"] {
    background-color: #090A0D !important;
    border-right: 1px solid var(--border-subtle);
}

/* Watchlist Add Ticker Form */
section[data-testid="stSidebar"] div[data-testid="stForm"] {
    border: 1px solid var(--border-subtle) !important;
    background: var(--bg-panel) !important;
    border-radius: 4px !important;
    padding: 6px 6px !important;
    margin-bottom: 8px !important;
}

section[data-testid="stSidebar"] div[data-testid="stForm"] input {
    background: #090A0D !important;
    border: 1px solid var(--border-subtle) !important;
    color: var(--text-primary) !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.74rem !important;
    padding: 4px 6px !important;
    border-radius: 3px !important;
}

section[data-testid="stSidebar"] div[data-testid="stForm"] input:focus {
    border-color: var(--accent-amber) !important;
    box-shadow: 0 0 0 1px var(--accent-amber) !important;
}

section[data-testid="stSidebar"] div[data-testid="stForm"] button {
    background: var(--bg-panel-elevated) !important;
    border: 1px solid var(--border-subtle) !important;
    color: var(--accent-amber) !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-weight: 700 !important;
    font-size: 0.85rem !important;
    padding: 2px !important;
    border-radius: 3px !important;
}

section[data-testid="stSidebar"] div[data-testid="stForm"] button:hover {
    border-color: var(--accent-amber) !important;
    background: var(--accent-amber-subtle) !important;
}

.sidebar-brand {
    padding: 4px 0 10px 0;
    border-bottom: 1px solid var(--border-subtle);
    margin-bottom: 12px;
}

.sidebar-brand-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    font-weight: 700;
    color: var(--accent-amber);
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.sidebar-brand-sub {
    font-size: 0.7rem;
    color: var(--text-muted);
    margin-top: 2px;
}

.sidebar-section-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.68rem;
    font-weight: 700;
    color: var(--accent-amber);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin: 1.1rem 0 0.4rem 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
}

/* New Session Button */
section[data-testid="stSidebar"] button[kind="primary"] {
    background: #181C27 !important;
    border: 1px solid var(--border-subtle) !important;
    color: var(--text-primary) !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.8rem !important;
    font-weight: 600 !important;
    border-radius: 5px !important;
    padding: 0.5rem 0.75rem !important;
    transition: all 0.15s ease !important;
}

section[data-testid="stSidebar"] button[kind="primary"]:hover {
    border-color: var(--accent-amber) !important;
    color: var(--accent-amber) !important;
    background: #202635 !important;
}

/* Watchlist Row Buttons in Sidebar */
.watchlist-row-container [data-testid="stHorizontalBlock"] {
    align-items: center;
    margin-bottom: 3px;
}

.watchlist-row-container [data-testid="stHorizontalBlock"] button {
    background: var(--bg-panel) !important;
    border: 1px solid var(--border-subtle) !important;
    box-shadow: none !important;
    text-align: left !important;
    justify-content: flex-start !important;
    color: #E2E8F0 !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.74rem !important;
    padding: 5px 8px !important;
    border-radius: 4px !important;
    transition: all 0.15s ease !important;
}

.watchlist-row-container [data-testid="stHorizontalBlock"] button:hover {
    background: var(--bg-panel-elevated) !important;
    border-color: var(--accent-amber) !important;
    color: #FFFFFF !important;
}

.watchlist-row-container [data-testid="stHorizontalBlock"] [data-testid="column"]:last-child button {
    opacity: 0.3 !important;
    padding: 5px 2px !important;
    justify-content: center !important;
    text-align: center !important;
}

.watchlist-row-container [data-testid="stHorizontalBlock"] [data-testid="column"]:last-child button:hover {
    opacity: 1 !important;
    color: var(--tv-red) !important;
    background: var(--tv-red-bg) !important;
    border-color: rgba(242, 54, 69, 0.3) !important;
}

/* History / Conversation List Rows */
.history-container [data-testid="stHorizontalBlock"] {
    align-items: center;
    margin-bottom: 2px;
}

.history-container [data-testid="stHorizontalBlock"] button {
    background: transparent !important;
    border: 1px solid transparent !important;
    box-shadow: none !important;
    text-align: left !important;
    justify-content: flex-start !important;
    color: var(--text-secondary) !important;
    font-size: 0.78rem !important;
    padding: 5px 8px !important;
    border-radius: 4px !important;
    transition: all 0.15s ease !important;
}

.history-container [data-testid="stHorizontalBlock"] button:hover {
    background: var(--bg-panel) !important;
    border-color: var(--border-subtle) !important;
    color: var(--text-primary) !important;
}

.history-container [data-testid="stHorizontalBlock"] [data-testid="column"]:last-child button {
    opacity: 0.3;
    padding: 4px !important;
}

.history-container [data-testid="stHorizontalBlock"] [data-testid="column"]:last-child button:hover {
    opacity: 1;
    color: var(--tv-red) !important;
    background: var(--tv-red-bg) !important;
    border-color: rgba(242, 54, 69, 0.3) !important;
}

/* Bloomberg Command Deck (Main Area) */
.command-deck-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin: 1.4rem 0 0.6rem 0;
}

.command-deck-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    font-weight: 700;
    color: var(--accent-amber);
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.command-deck-hint {
    font-size: 0.7rem;
    color: var(--text-muted);
    font-family: 'JetBrains Mono', monospace;
}

.main [data-testid="stHorizontalBlock"] button {
    background: var(--bg-panel) !important;
    border: 1px solid var(--border-subtle) !important;
    color: var(--text-primary) !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    border-radius: 6px !important;
    padding: 0.75rem 0.9rem !important;
    text-align: left !important;
    justify-content: flex-start !important;
    transition: all 0.15s ease !important;
    min-height: 48px;
    white-space: pre-line !important;
}

.main [data-testid="stHorizontalBlock"] button:hover {
    border-color: var(--accent-amber) !important;
    background: var(--bg-panel-elevated) !important;
    box-shadow: 0 0 12px var(--accent-amber-subtle) !important;
}

/* Chat Messages */
div[data-testid="stChatMessage"] {
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
    padding: 0.9rem 1.2rem;
    margin-bottom: 0.75rem;
}

div[data-testid="stChatMessage"] strong {
    color: #FFFFFF;
    font-weight: 600;
}

div[data-testid="stChatMessage"] code {
    font-family: 'JetBrains Mono', monospace;
    background: var(--bg-panel-elevated);
    color: var(--accent-amber);
    border: 1px solid var(--border-subtle);
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 0.85em;
}

/* Chat Input Bar */
div[data-testid="stChatInput"] {
    border-radius: 6px;
    overflow: hidden;
}

div[data-testid="stChatInput"] textarea {
    background: #090A0D !important;
    border: 1px solid var(--border-subtle) !important;
    color: var(--text-primary) !important;
    font-size: 0.88rem !important;
    border-radius: 6px !important;
}

div[data-testid="stChatInput"] textarea:focus {
    border-color: var(--accent-amber) !important;
    box-shadow: 0 0 0 1px var(--accent-amber) !important;
}

div[data-testid="stChatInput"] button {
    color: var(--accent-amber) !important;
}
</style>
""", unsafe_allow_html=True)

# Ctrl+B toggles the sidebar by clicking Streamlit's own collapse/expand control. One guarded
# listener on the parent doc, in a 0-height iframe.
st.components.v1.html("""
<script>
const doc = window.parent.document;
if (!doc.__sidebarShortcut) {
  doc.__sidebarShortcut = true;
  doc.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && (e.key === 'b' || e.key === 'B')) {
      e.preventDefault();
      const openBtn = doc.querySelector('[data-testid="stSidebarCollapsedControl"] button, [data-testid="collapsedControl"] button, [data-testid="collapsedControl"]');
      const closeBtn = doc.querySelector('[data-testid="stSidebarCollapseButton"] button, [data-testid="stSidebarCollapseButton"]');
      const btn = openBtn || closeBtn;
      if (btn) btn.click();
    }
  });
}
</script>
""", height=0)

# Render Header
st.markdown("""
<div class="terminal-header">
    <div class="terminal-title-row">
        <div class="terminal-title">
            <span class="terminal-logo">⚡</span>
            <span>NSE AFTER-MARKET TERMINAL</span>
            <span class="terminal-badge">EOD RESEARCH DESK</span>
        </div>
        <div class="terminal-eod-pill">
            <span>● END-OF-DAY MODE</span>
        </div>
    </div>
    <div class="terminal-sub">Quantitative Swing Screening & Exit Intelligence · Personal Research Tool (Non-Advisory)</div>
</div>
""", unsafe_allow_html=True)

render_market_strip()

CONV_DIR = "conversations"
os.makedirs(CONV_DIR, exist_ok=True)


def _day_label(ts):
    try:
        d = datetime.fromisoformat(ts).date()
    except (ValueError, TypeError):
        return "Undated"
    today = datetime.now().date()
    if d == today:
        return "Today"
    if (today - d).days == 1:
        return "Yesterday"
    return d.strftime("%d %B %Y")


def list_conversations():
    files = [f for f in os.listdir(CONV_DIR) if f.endswith(".json")]
    convos = []
    for f in files:
        try:
            with open(os.path.join(CONV_DIR, f), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            convos.append({"id": f.replace(".json", ""), "title": data.get("title", "Untitled"), "timestamp": data.get("timestamp", "")})
        except Exception:
            continue
    convos.sort(key=lambda c: c["timestamp"], reverse=True)
    return convos


def save_conversation(session_id, messages_display, agent_history):
    if len(messages_display) == 0:
        return
    title = messages_display[0]["content"][:50]
    data = {
        "title": title,
        "timestamp": datetime.now().isoformat(),
        "messages_display": messages_display,
        "agent_history": agent_history,
    }
    with open(os.path.join(CONV_DIR, f"{session_id}.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def load_conversation(session_id):
    with open(os.path.join(CONV_DIR, f"{session_id}.json"), "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data["messages_display"], data["agent_history"]


def start_new_conversation():
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.agent = TradingAgent()
    st.session_state.messages = []


if "session_id" not in st.session_state:
    start_new_conversation()

if "custom_watchlist" not in st.session_state:
    st.session_state.custom_watchlist = list(DEFAULT_WATCHLIST)

watchlist_prompt = None

with st.sidebar:
    st.markdown("""
    <div class="sidebar-brand">
        <div class="sidebar-brand-title">TERMINAL CONTROLS</div>
        <div class="sidebar-brand-sub">NSE Swing Architecture</div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("＋ New Research Session", type="primary", use_container_width=True):
        start_new_conversation()
        st.rerun()

    # --- TOP HALF: WATCHLIST RADAR ---
    st.markdown(f'<div class="sidebar-section-title"><span>WATCHLIST RADAR</span> <span>({len(st.session_state.custom_watchlist)})</span></div>', unsafe_allow_html=True)
    
    # Add Ticker Form
    with st.form("add_ticker_form", clear_on_submit=True):
        f_col1, f_col2 = st.columns([3, 1])
        with f_col1:
            new_ticker_input = st.text_input("Add Stock", placeholder="e.g. TATAMOTORS", label_visibility="collapsed")
        with f_col2:
            add_btn = st.form_submit_button("＋")
        if add_btn and new_ticker_input:
            sym_clean = new_ticker_input.strip().upper()
            if not sym_clean.endswith(".NS") and not sym_clean.endswith(".BO"):
                sym_clean = f"{sym_clean}.NS"
            if sym_clean not in st.session_state.custom_watchlist:
                st.session_state.custom_watchlist.append(sym_clean)
                st.rerun()

    # Render Watchlist with Live Price & Change %
    wl_quotes = get_watchlist_quotes(tuple(st.session_state.custom_watchlist))
    
    st.markdown('<div class="watchlist-row-container">', unsafe_allow_html=True)
    for idx, q in enumerate(wl_quotes):
        arrow = "▲" if q["chg_pct"] >= 0 else "▼"
        sign = "+" if q["chg_pct"] >= 0 else ""
        price_txt = f"₹{q['price']:,.1f}" if q["price"] > 0 else "—"
        row_label = f"{q['clean']}  {price_txt}  {arrow}{sign}{q['chg_pct']:.2f}%"
        
        c_btn, c_del = st.columns([5, 1])
        with c_btn:
            if st.button(row_label, key=f"wl_row_{q['symbol']}_{idx}", use_container_width=True):
                watchlist_prompt = f"Give me a detailed technical and swing analysis on {q['symbol']} including current trend momentum, key support/resistance, and risk/reward setup."
        with c_del:
            if st.button("✕", key=f"wl_del_{q['symbol']}_{idx}"):
                st.session_state.custom_watchlist = [s for s in st.session_state.custom_watchlist if s != q["symbol"]]
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # --- BOTTOM HALF: PAST SESSIONS ---
    st.markdown('<div class="sidebar-section-title"><span>PAST SESSIONS</span></div>', unsafe_allow_html=True)

    past_convos = list_conversations()
    if len(past_convos) == 0:
        st.caption("No saved conversations yet.")
    else:
        st.markdown('<div class="history-container">', unsafe_allow_html=True)
        last_date = None
        for c in past_convos:
            day = _day_label(c["timestamp"])
            if day != last_date:
                st.caption(day)
                last_date = day
            label = c["title"] if len(c["title"]) < 36 else c["title"][:33] + "..."
            col1, col2 = st.columns([5, 1])
            with col1:
                if st.button(label, key=f"conv_{c['id']}", use_container_width=True):
                    messages_display, agent_history = load_conversation(c["id"])
                    st.session_state.session_id = c["id"]
                    st.session_state.messages = messages_display
                    st.session_state.agent = TradingAgent()
                    st.session_state.agent.conversation_history = agent_history
                    st.rerun()
            with col2:
                if st.button("🗑️", key=f"del_{c['id']}"):
                    try:
                        os.remove(os.path.join(CONV_DIR, f"{c['id']}.json"))
                    except FileNotFoundError:
                        pass
                    if st.session_state.session_id == c['id']:
                        start_new_conversation()
                    st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

AVATARS = {"user": "🧑‍💻", "assistant": "⚡"}

for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar=AVATARS[msg["role"]]):
        st.markdown(msg["content"])

# Bloomberg Command Deck shown when conversation is empty
action_prompt = None
if len(st.session_state.messages) == 0:
    st.markdown("""
    <div class="command-deck-header">
        <div class="command-deck-title">⚡ BLOOMBERG COMMAND DECK</div>
        <div class="command-deck-hint">1-Click Institutional Workflows</div>
    </div>
    """, unsafe_allow_html=True)
    q_col1, q_col2 = st.columns(2)
    with q_col1:
        if st.button("🔎 [F1: SCAN SHORT] Scan Best Swing Breakouts\nWatchlist multi-factor ranking (5–10 day setups)", key="quick_scan_short", use_container_width=True):
            action_prompt = "Scan for the best short-term swing setups in our watchlist and rank them by model conviction"
        if st.button("📊 [F3: POSITIONS] Audit Open Trades & Exit Rules\nReal-time stop-loss, profit target & time decay check", key="quick_check_pos", use_container_width=True):
            action_prompt = "Give me an analysis on my current open positions and exit checks"
    with q_col2:
        if st.button("⚡ [F2: MOMENTUM] Long-Term Trend Leaders\n200-day EMA momentum & volume breakout screen", key="quick_scan_long", use_container_width=True):
            action_prompt = "Run the long-term momentum scan and give top candidates with trend justification"
        if st.button("🛡️ [F4: RISK AUDIT] Discipline & Drawdown Report\nCheck risk rules, max portfolio exposure & journal", key="quick_discipline", use_container_width=True):
            action_prompt = "Check my trading discipline, risk limits, and journal metrics"

prompt = st.chat_input("Enter command, stock ticker (e.g. RELIANCE), or ask a question...")

# Click-through from the Home page: it stashes a ticker in session_state then switches here.
# Gated - only fires when Home actually set it, so it cannot affect normal use.
incoming_prompt = None
_incoming = st.session_state.pop("assistant_ticker", None)
if _incoming:
    incoming_prompt = (f"Give me a detailed technical and swing analysis on {_incoming} including "
                       "current trend momentum, key support/resistance, and risk/reward setup.")

final_prompt = prompt or action_prompt or watchlist_prompt or incoming_prompt

if final_prompt:
    st.session_state.messages.append({"role": "user", "content": final_prompt})
    with st.chat_message("user", avatar=AVATARS["user"]):
        st.markdown(final_prompt)

    with st.chat_message("assistant", avatar=AVATARS["assistant"]):
        with st.spinner("Executing quantitative analysis..."):
            response = st.session_state.agent.ask(final_prompt)
        st.markdown(response)
    st.session_state.messages.append({"role": "assistant", "content": response})

    save_conversation(st.session_state.session_id, st.session_state.messages, st.session_state.agent.conversation_history)

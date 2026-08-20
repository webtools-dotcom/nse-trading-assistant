"""Personal Watchlist Page: custom watchlist radar with live technical metrics and news badges.
Display-only: reads user_watchlist.json, price cache, and today's news feeds.
"""

import html
from datetime import datetime
import streamlit as st
import pandas as pd

from ui_common import inject_theme, render_nav, IST, ticker_buttons, goto_assistant, pnl_color
from cache_manager import load_price_cache_short
from market_recap import load_meta_map, today_pct
from watchlist_store import load_user_watchlist, add_to_watchlist, remove_from_watchlist

st.set_page_config(
    page_title="My Watchlist",
    page_icon="⭐",
    layout="wide",
    initial_sidebar_state="expanded"
)
inject_theme()
render_nav("watchlist")

# Hide sidebar CSS
st.markdown("""
<style>
section[data-testid="stSidebar"],
[data-testid="collapsedControl"], [data-testid="stSidebarCollapsedControl"] {
    display: none !important;
}
.block-container { max-width: 1200px !important; }

.wl-card {
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
    padding: 14px 18px;
    margin-bottom: 12px;
}
.wl-card.not-in-cache {
    opacity: 0.6;
    border-style: dashed;
}
.wl-header-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
    flex-wrap: wrap;
    gap: 8px;
}
.wl-tk-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 10px;
}
.wl-company {
    font-size: 0.82rem;
    color: var(--text-secondary);
    font-weight: 500;
}
.wl-news-badge {
    background: rgba(31,111,235,0.16);
    color: #4c8dff;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.65rem;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 3px;
    border: 1px solid rgba(31,111,235,0.3);
}
.wl-metrics-grid {
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
    margin: 10px 0 6px 0;
}
.wl-metric-item {
    background: var(--bg-panel-elevated);
    border: 1px solid var(--border-subtle);
    border-radius: 4px;
    padding: 6px 10px;
    min-width: 110px;
}
.wl-metric-label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.58rem;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.wl-metric-val {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.95rem;
    font-weight: 700;
    color: var(--text-primary);
    margin-top: 2px;
}
</style>
""", unsafe_allow_html=True)

# Terminal Header
now = datetime.now(IST)
st.markdown(f"""
<div class="terminal-header"><div class="terminal-title-row">
  <div class="terminal-title"><span class="terminal-logo">⭐</span> PERSONAL WATCHLIST RADAR</div>
  <div class="terminal-eod-pill">● {now.strftime('%d %b %Y · %I:%M %p IST')}</div>
</div><div class="terminal-sub">Custom monitored tickers · instant technical snapshot, 52-week status &amp; news alerts</div></div>
""", unsafe_allow_html=True)

# Load caches
meta = load_meta_map()
try:
    price_cache = load_price_cache_short() or {}
except Exception:
    price_cache = {}

# Check for today's news hits on watchlist
news_watch_set = set()
try:
    from news_feed import get_ranked_news
    ranked = get_ranked_news(force=False)
    for it in ranked.get("top", []) + ranked.get("more", []):
        if it.get("watch"):
            news_watch_set.add(str(it["watch"]).upper())
except Exception:
    pass

# User Watchlist
user_tickers = load_user_watchlist()

# Add Ticker Controls
st.markdown('<div class="news-group">➕ Add Stock to Watchlist</div>', unsafe_allow_html=True)
col_in, col_btn, _ = st.columns([3, 1, 4])
with col_in:
    new_sym = st.text_input("Ticker Symbol", placeholder="e.g. TATAMOTORS or RELIANCE.NS",
                            label_visibility="collapsed", key="wl_input")
with col_btn:
    if st.button("＋ Add Stock", use_container_width=True, type="primary"):
        if new_sym and new_sym.strip():
            add_to_watchlist(new_sym.strip())
            st.rerun()

st.markdown(f'<div class="news-group">📋 Monitored Stocks ({len(user_tickers)})</div>', unsafe_allow_html=True)

if not user_tickers:
    st.markdown('<div class="stat-sub" style="padding:10px 2px;">Your personal watchlist is empty. Add tickers above to track daily setups and news.</div>', unsafe_allow_html=True)
else:
    for idx, tk in enumerate(user_tickers):
        clean_tk = tk.replace(".NS", "").replace(".BO", "")
        m = meta.get(tk, {})
        comp = m.get("company", clean_tk)
        sector = m.get("sector", "Unknown")
        cap = m.get("cap_bucket", "Unknown")

        has_news = clean_tk in news_watch_set
        news_badge_html = '<span class="wl-news-badge">📰 in today\'s news</span>' if has_news else ''

        df = price_cache.get(tk)
        if df is not None and len(df) > 0:
            last = df.iloc[-1]
            close = float(last.get("close", 0.0))
            pct = today_pct(df)
            rsi = float(last.get("rsi", 0.0)) if pd.notna(last.get("rsi")) else None
            sma_200 = float(last.get("sma_200", 0.0)) if pd.notna(last.get("sma_200")) else None
            dist_high = float(last.get("dist_from_high_252", 0.0)) if pd.notna(last.get("dist_from_high_252")) else None

            # Trend vs 200 SMA
            if sma_200 and sma_200 > 0:
                trend_pos = "ABOVE 200-SMA" if close >= sma_200 else "BELOW 200-SMA"
                trend_color = "var(--tv-green)" if close >= sma_200 else "var(--tv-red)"
            else:
                trend_pos = "—"
                trend_color = "var(--text-muted)"

            # RSI styling
            if rsi is not None:
                rsi_s = f"{rsi:.1f}"
                rsi_col = "var(--tv-green)" if rsi < 30 else ("var(--tv-red)" if rsi > 70 else "var(--text-primary)")
                rsi_sub = " (Oversold)" if rsi < 30 else (" (Overbought)" if rsi > 70 else "")
            else:
                rsi_s, rsi_col, rsi_sub = "—", "var(--text-primary)", ""

            # 52w distance
            if dist_high is not None:
                dist_s = f"{dist_high * 100:+.1f}%"
            else:
                dist_s = "—"

            st.markdown(f"""
            <div class="wl-card">
              <div class="wl-header-row">
                <div class="wl-tk-title">
                  <span>{clean_tk}</span>
                  <span class="wl-company">({html.escape(comp)} · {html.escape(sector)} · {cap}-cap)</span>
                  {news_badge_html}
                </div>
              </div>
              <div class="wl-metrics-grid">
                <div class="wl-metric-item">
                  <div class="wl-metric-label">LTP</div>
                  <div class="wl-metric-val">₹{close:,.1f}</div>
                </div>
                <div class="wl-metric-item">
                  <div class="wl-metric-label">Today %</div>
                  <div class="wl-metric-val" style="color:{pnl_color(pct)};">{pct:+.2f}%</div>
                </div>
                <div class="wl-metric-item">
                  <div class="wl-metric-label">RSI (14d)</div>
                  <div class="wl-metric-val" style="color:{rsi_col};">{rsi_s}{rsi_sub}</div>
                </div>
                <div class="wl-metric-item">
                  <div class="wl-metric-label">Trend vs 200SMA</div>
                  <div class="wl-metric-val" style="color:{trend_color};font-size:0.82rem;">{trend_pos}</div>
                </div>
                <div class="wl-metric-item">
                  <div class="wl-metric-label">52W High Dist</div>
                  <div class="wl-metric-val">{dist_s}</div>
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

        else:
            st.markdown(f"""
            <div class="wl-card not-in-cache">
              <div class="wl-header-row">
                <div class="wl-tk-title">
                  <span>{clean_tk}</span>
                  <span class="wl-company">({html.escape(comp)})</span>
                  {news_badge_html}
                </div>
              </div>
              <div class="stat-sub" style="color:var(--accent-amber);">Not in price cache — run <code>python refresh_cache.py</code> to fetch daily features.</div>
            </div>
            """, unsafe_allow_html=True)

        # Action row
        b_col1, b_col2, _ = st.columns([2.5, 1, 6])
        with b_col1:
            if st.button(f"🔍 Analyze {clean_tk} in Assistant →", key=f"asst_{tk}_{idx}"):
                goto_assistant(tk)
        with b_col2:
            if st.button(f"✕ Remove", key=f"rem_{tk}_{idx}"):
                remove_from_watchlist(tk)
                st.rerun()
        st.markdown("<div style='margin-bottom:8px;'></div>", unsafe_allow_html=True)

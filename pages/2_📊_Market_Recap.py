"""Today's Market Recap page: comprehensive end-of-day market overview.
Display-only: reads already-computed caches and visualizes breadth, top movers,
sector performance, participant flows, and catalysts.
"""

import html
from datetime import datetime
import streamlit as st

from ui_common import (inject_theme, render_nav, render_market_strip, market_snapshot,
                       mood_score, mood_label, IST, tile, pnl_color, ticker_buttons)
from cache_manager import (load_price_cache_short, load_market_breadth_cache,
                           load_vix_cache, load_category_flows, load_upcoming_results,
                           load_corp_announcements_cache)
from market_recap import (load_meta_map, top_movers, most_active,
                          advance_decline, near_52w, sector_heatmap)

st.set_page_config(
    page_title="Market Recap",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)
inject_theme()
render_nav("recap")

# Page-specific styling
st.markdown("""
<style>
/* Hide the sidebar + its reveal control (state stays expanded; Assistant untouched) */
section[data-testid="stSidebar"],
[data-testid="collapsedControl"], [data-testid="stSidebarCollapsedControl"] {
    display: none !important;
}
.block-container { max-width: 1320px !important; }

/* Market mood gauge */
.mood-wrap { display: flex; align-items: center; gap: 14px; background: var(--bg-panel);
    border: 1px solid var(--border-subtle); border-radius: 6px; padding: 10px 14px; margin: 6px 0; }
.mood-track { position: relative; flex: 1; height: 8px; border-radius: 5px;
    background: linear-gradient(to right, var(--tv-red), var(--accent-amber), var(--tv-green)); }
.mood-marker { position: absolute; top: -4px; width: 4px; height: 16px; border-radius: 2px;
    background: var(--text-primary); box-shadow: 0 0 6px rgba(0,0,0,0.6); transform: translateX(-2px); }
.mood-label { font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 0.9rem;
    min-width: 92px; text-align: right; }
.mood-cap { font-family: 'JetBrains Mono', monospace; font-size: 0.6rem; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.05em; min-width: 74px; }

/* Sector chips */
.sector-chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 16px 0; }
.sector-chip {
    font-family: 'JetBrains Mono', monospace; font-size: 0.74rem; font-weight: 600;
    padding: 6px 12px; border-radius: 4px; border: 1px solid var(--border-subtle);
    background: var(--bg-panel); color: var(--text-primary);
}
.sector-chip.pos { border-color: rgba(8, 153, 129, 0.4); background: var(--tv-green-bg); color: var(--tv-green); }
.sector-chip.neg { border-color: rgba(242, 54, 69, 0.4); background: var(--tv-red-bg); color: var(--tv-red); }
</style>
""", unsafe_allow_html=True)

# Terminal Header
now = datetime.now(IST)
st.markdown(f"""
<div class="terminal-header"><div class="terminal-title-row">
  <div class="terminal-title"><span class="terminal-logo">📊</span> TODAY'S MARKET RECAP</div>
  <div class="terminal-eod-pill">● {now.strftime('%d %b %Y · %I:%M %p IST')}</div>
</div><div class="terminal-sub">Comprehensive daily market overview · breadths, movers, sectors &amp; flows</div></div>
""", unsafe_allow_html=True)

render_market_strip()

# Market Mood Gauge
quotes, _ = market_snapshot()
nifty = next((q for q in quotes if q["label"] == "NIFTY 50"), None)
try:
    breadth = load_market_breadth_cache() or {}
except Exception:
    breadth = {}

score = mood_score(nifty["chg_pct"] if nifty else None,
                   breadth.get("breadth_pct_above_200sma"), breadth.get("nifty_above_200sma"))
label, color = mood_label(score)
pos = (score + 1) / 2 * 100
st.markdown(
    f'<div class="mood-wrap"><span class="mood-cap">Market Mood</span>'
    f'<div class="mood-track"><div class="mood-marker" style="left:{pos:.0f}%"></div></div>'
    f'<span class="mood-label" style="color:{color}">{label}</span></div>',
    unsafe_allow_html=True)

# Check Price Cache
try:
    price_cache = load_price_cache_short()
except Exception:
    price_cache = None

if not price_cache:
    st.markdown('<div class="home-warn">Price data not built yet — run '
                '<code>python refresh_cache.py</code>.</div>', unsafe_allow_html=True)
    st.stop()

meta = load_meta_map()

# --- Index & Breadth Row ---
try:
    vix_df = load_vix_cache()
except Exception:
    vix_df = None

regime = breadth.get("regime", "Unknown")
regime_color = {"Broadly Bullish": "var(--tv-green)", "Broadly Bearish": "var(--tv-red)"}.get(
    regime, "var(--accent-amber)")

summary_tiles = []
if nifty:
    n_chg = nifty.get("chg_pct", 0.0)
    summary_tiles.append(tile("Nifty 50", f"₹{nifty.get('price', 0):,.1f}", f"{n_chg:+.2f}% today", pnl_color(n_chg)))

if vix_df is not None and len(vix_df):
    try:
        vix = float(vix_df["close"].iloc[-1])
        summary_tiles.append(tile("India VIX", f"{vix:.2f}", "fear gauge" if vix >= 18 else "calm tape",
                                  "var(--tv-red)" if vix >= 18 else "var(--tv-green)"))
    except Exception:
        pass

bp = breadth.get("breadth_pct_above_200sma")
if bp is not None:
    summary_tiles.append(tile("Breadth", f"{bp:.0f}%", "stocks > 200-day SMA",
                              "var(--tv-green)" if bp >= 50 else "var(--tv-red)"))

summary_tiles.append(tile("Regime", regime, "market structure", regime_color))

# Advance / Decline Count
ad = advance_decline(price_cache)
total_ad = ad['advancers'] + ad['decliners'] + ad['unchanged']
summary_tiles.append(tile("Advancers", str(ad['advancers']), f"{(ad['advancers']/total_ad*100):.0f}%" if total_ad else "", "var(--tv-green)"))
summary_tiles.append(tile("Decliners", str(ad['decliners']), f"{(ad['decliners']/total_ad*100):.0f}%" if total_ad else "", "var(--tv-red)"))

st.markdown('<div class="news-group">📈 Index &amp; Breadth Snapshot</div>', unsafe_allow_html=True)
st.markdown(f'<div class="panel-grid">{"".join(summary_tiles)}</div>', unsafe_allow_html=True)

# --- Sector Heatmap ---
st.markdown('<div class="news-group">🗺️ Sector Performance</div>', unsafe_allow_html=True)
sectors = sector_heatmap(price_cache, meta)
if sectors:
    chips_html = '<div class="sector-chips">'
    for s in sectors:
        cls = "pos" if s["avg_pct"] > 0 else ("neg" if s["avg_pct"] < 0 else "")
        sign = "+" if s["avg_pct"] > 0 else ""
        chips_html += (f'<span class="sector-chip {cls}">{html.escape(s["sector"])} '
                       f'{sign}{s["avg_pct"]:.2f}% <span style="font-size:0.65rem;opacity:0.7;">({s["n"]})</span></span>')
    chips_html += '</div>'
    st.markdown(chips_html, unsafe_allow_html=True)
else:
    st.markdown('<div class="stat-sub">No sector data available.</div>', unsafe_allow_html=True)


def _render_movers_table(items):
    if not items:
        return '<div class="stat-sub" style="padding:6px 2px;">No stocks in this category.</div>'
    rows = ""
    for it in items:
        tk = html.escape(it["ticker"].replace(".NS", ""))
        comp = html.escape(it["company"][:22])
        sec = html.escape(it["sector"][:18])
        pct = it["pct"]
        cls = "pnl-pos" if pct >= 0 else "pnl-neg"
        pct_s = f'<span class="{cls}">{pct:+.2f}%</span>'
        ltp_s = f"₹{it['close']:,.1f}"
        rvol_s = f"{it['rvol']:.1f}x" if it.get("rvol") else "—"
        rows += f"<tr><td><span class='pos-tk'>{tk}</span></td><td>{comp}</td><td>{sec}</td><td>{pct_s}</td><td>{ltp_s}</td><td>{rvol_s}</td></tr>"
    return f'<div class="pos-wrap"><table class="pos-table"><thead><tr><th>Ticker</th><th>Company</th><th>Sector</th><th>%</th><th>LTP</th><th>RVOL</th></tr></thead><tbody>{rows}</tbody></table></div>'


# --- Top Gainers & Losers ---
movers = top_movers(price_cache, meta, n=15)
col_g, col_l = st.columns(2)
with col_g:
    st.markdown('<div class="news-group">🚀 Top Gainers (≥ ₹1cr turnover)</div>', unsafe_allow_html=True)
    st.markdown(_render_movers_table(movers["gainers"]), unsafe_allow_html=True)
    if movers["gainers"]:
        ticker_buttons([m["ticker"] for m in movers["gainers"][:6]], "g_btn")

with col_l:
    st.markdown('<div class="news-group">🔻 Top Losers (≥ ₹1cr turnover)</div>', unsafe_allow_html=True)
    st.markdown(_render_movers_table(movers["losers"]), unsafe_allow_html=True)
    if movers["losers"]:
        ticker_buttons([m["ticker"] for m in movers["losers"][:6]], "l_btn")

# --- Most Active (Unusual Volume) ---
st.markdown('<div class="news-group">⚡ Most Active by Relative Volume (RVOL)</div>', unsafe_allow_html=True)
actives = most_active(price_cache, meta, n=10)
st.markdown(_render_movers_table(actives), unsafe_allow_html=True)
if actives:
    ticker_buttons([m["ticker"] for m in actives[:6]], "act_btn")

# --- Near 52-Week High / Low ---
st.markdown('<div class="news-group">🎯 Near 52-Week High / Low <span style="font-size:0.65rem;color:var(--text-muted);font-weight:400;">(within ~2% · info only — not a signal)</span></div>', unsafe_allow_html=True)
n52 = near_52w(price_cache, meta, n=8)
col_h, col_low = st.columns(2)
with col_h:
    st.markdown('<div class="stat-sub" style="font-weight:700;margin-bottom:4px;color:var(--tv-green);">Near 52-Week High (within 2%)</div>', unsafe_allow_html=True)
    st.markdown(_render_movers_table(n52["near_high"]), unsafe_allow_html=True)
    if n52["near_high"]:
        ticker_buttons([m["ticker"] for m in n52["near_high"][:6]], "h52_btn")
with col_low:
    st.markdown('<div class="stat-sub" style="font-weight:700;margin-bottom:4px;color:var(--tv-red);">Near 52-Week Low (within 2%)</div>', unsafe_allow_html=True)
    st.markdown(_render_movers_table(n52["near_low"]), unsafe_allow_html=True)
    if n52["near_low"]:
        ticker_buttons([m["ticker"] for m in n52["near_low"][:6]], "l52_btn")

# --- Participant Cash Flows (FPI vs Retail) ---
st.markdown('<div class="news-group">🏛️ Participant Cash Flows (NSE Official)</div>', unsafe_allow_html=True)
try:
    flows_df = load_category_flows()
except Exception:
    flows_df = None

if flows_df is not None and len(flows_df):
    try:
        latest_date = flows_df['date'].max()
        latest_flows = flows_df[flows_df['date'] == latest_date]
        fpi_row = latest_flows[latest_flows['category'] == 'FPI']
        retail_row = latest_flows[latest_flows['category'] == 'RETAIL']
        mf_row = latest_flows[latest_flows['category'] == 'MUTUAL_FUNDS']

        flow_tiles = []
        if len(fpi_row):
            fpi_net = float(fpi_row['net_cr'].iloc[0])
            flow_tiles.append(tile("FPI / FII Net", f"₹{fpi_net:+,.1f} cr", f"as of {str(latest_date)[:10]}", pnl_color(fpi_net)))
        if len(retail_row):
            ret_net = float(retail_row['net_cr'].iloc[0])
            flow_tiles.append(tile("Retail Net", f"₹{ret_net:+,.1f} cr", f"as of {str(latest_date)[:10]}", pnl_color(ret_net)))
        if len(mf_row):
            mf_net = float(mf_row['net_cr'].iloc[0])
            flow_tiles.append(tile("Mutual Funds Net", f"₹{mf_net:+,.1f} cr", f"as of {str(latest_date)[:10]}", pnl_color(mf_net)))

        if flow_tiles:
            st.markdown(f'<div class="panel-grid">{"".join(flow_tiles)}</div>', unsafe_allow_html=True)
            st.caption("ℹ️ Participant turnover data is published by NSE with ~1-session reporting lag.")
    except Exception:
        pass
else:
    st.markdown('<div class="stat-sub">Category flow data not cached yet — run <code>python refresh_cache.py</code>.</div>', unsafe_allow_html=True)

# --- Catalysts (Upcoming Results & Announcements) ---
st.markdown('<div class="news-group">📅 Catalysts &amp; Corporate Filings</div>', unsafe_allow_html=True)
col_res, col_ann = st.columns(2)
with col_res:
    st.markdown('<div class="stat-sub" style="font-weight:700;margin-bottom:4px;">Upcoming Results Calendar</div>', unsafe_allow_html=True)
    try:
        res_df = load_upcoming_results()
        if res_df is not None and len(res_df):
            rows = ""
            for _, r in res_df.head(8).iterrows():
                sym = html.escape(str(r.get('symbol', r.get('Symbol', ''))))
                dt = html.escape(str(r.get('date', r.get('Date', ''))))
                purpose = html.escape(str(r.get('purpose', r.get('Purpose', 'Earnings'))))[:30]
                rows += f"<tr><td><span class='pos-tk'>{sym}</span></td><td>{dt}</td><td>{purpose}</td></tr>"
            st.markdown(f'<div class="pos-wrap"><table class="pos-table"><thead><tr><th>Symbol</th><th>Date</th><th>Purpose</th></tr></thead><tbody>{rows}</tbody></table></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="stat-sub">No upcoming results in cache.</div>', unsafe_allow_html=True)
    except Exception:
        st.markdown('<div class="stat-sub">Results calendar cache not available.</div>', unsafe_allow_html=True)

with col_ann:
    st.markdown('<div class="stat-sub" style="font-weight:700;margin-bottom:4px;">Recent Corporate Announcements</div>', unsafe_allow_html=True)
    try:
        ann_df = load_corp_announcements_cache()
        if ann_df is not None and len(ann_df):
            rows = ""
            for _, r in ann_df.head(8).iterrows():
                sym = html.escape(str(r.get('symbol', '')))
                desc = html.escape(str(r.get('desc', r.get('attchmntText', r.get('subject', ''))))[:40])
                dt = html.escape(str(r.get('an_dt', r.get('date', ''))))
                rows += f"<tr><td><span class='pos-tk'>{sym}</span></td><td>{dt}</td><td>{desc}</td></tr>"
            st.markdown(f'<div class="pos-wrap"><table class="pos-table"><thead><tr><th>Symbol</th><th>Date</th><th>Announcement</th></tr></thead><tbody>{rows}</tbody></table></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="stat-sub">No recent announcements in cache.</div>', unsafe_allow_html=True)
    except Exception:
        st.markdown('<div class="stat-sub">Announcements cache not available.</div>', unsafe_allow_html=True)

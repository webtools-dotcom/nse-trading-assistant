"""Home / landing page of the terminal suite: a running market ticker + today's CURATED news
(grouped, biggest first, noise dropped), styled to match the Assistant. Display-only and
isolated - imports the news module and shared UI, nothing from the trading/backtest path."""

import html
import streamlit as st
from datetime import datetime

from news_feed import get_ranked_news, CATEGORIES, CACHE_TTL_MIN
from ui_common import (inject_theme, render_market_strip, market_snapshot,
                       mood_score, mood_label, IST, ltp, tile, ticker_buttons,
                       goto_assistant, pnl_color, render_nav)
from trade_journal import open_positions_records, realized_pnl_summary
from cache_manager import load_market_breadth_cache, load_vix_cache
from config import vol_regime_multiplier

# Sidebar hidden on Home via CSS (it's the Assistant's tool, empty here). State stays
# "expanded" - NEVER "collapsed" - because a page that collapses it corrupts the shared state
# and leaves the Assistant's sidebar stuck collapsed with no reveal control. Hiding visually
# with display:none keeps the state healthy; navigation lives in the top tabs.
st.set_page_config(page_title="Market Home", page_icon="📰", layout="wide",
                   initial_sidebar_state="expanded")
inject_theme()
render_nav("home")

# Home-only news styling, built on the theme's CSS variables (defined in theme.css :root).
st.markdown("""
<style>
/* Hide the sidebar + its reveal control on Home only (state stays expanded; Assistant untouched) */
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
/* Alert cards */
.alert-card { display: flex; align-items: center; gap: 10px; border-radius: 6px; padding: 9px 13px;
    margin: 6px 0; font-size: 0.86rem; border: 1px solid; }
.alert-stop   { background: var(--tv-red-bg); border-color: var(--tv-red); color: var(--text-primary); }
.alert-target { background: var(--tv-green-bg); border-color: var(--tv-green); color: var(--text-primary); }
.alert-time   { background: var(--accent-amber-subtle); border-color: var(--accent-amber-border); color: var(--text-primary); }
.alert-tag { font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 0.62rem;
    padding: 2px 7px; border-radius: 3px; text-transform: uppercase; letter-spacing: 0.05em;
    background: rgba(0,0,0,0.25); white-space: nowrap; }
.alert-ok { color: var(--tv-green); font-family: 'JetBrains Mono', monospace; font-size: 0.78rem;
    padding: 4px 2px; }
.news-card {
    background: var(--bg-panel); border: 1px solid var(--border-subtle);
    border-left: 3px solid var(--border-active); border-radius: 6px;
    padding: 11px 14px; margin: 8px 0;
}
.news-card.imp-high   { border-left-color: var(--tv-red); }
.news-card.imp-medium { border-left-color: var(--accent-amber); }
.news-card.imp-low    { border-left-color: var(--border-active); }
.news-card.imp-watch  { border-left-color: #1f6feb; background: rgba(31,111,235,0.05); }
.nc-head { display: flex; align-items: center; gap: 8px; margin-bottom: 5px; flex-wrap: wrap; }
.nc-badge {
    font-family: 'JetBrains Mono', monospace; font-size: 0.6rem; font-weight: 700;
    padding: 1px 6px; border-radius: 3px; letter-spacing: 0.05em; text-transform: uppercase;
}
.nc-badge.high   { background: var(--tv-red-bg); color: var(--tv-red); }
.nc-badge.medium { background: var(--accent-amber-subtle); color: var(--accent-amber); }
.nc-badge.low    { background: var(--bg-panel-elevated); color: var(--text-muted); }
.nc-watch { background: rgba(31,111,235,0.16); color: #4c8dff; font-family: 'JetBrains Mono',
    monospace; font-size: 0.6rem; font-weight: 700; padding: 1px 6px; border-radius: 3px; }
.nc-title {
    color: var(--text-primary) !important; font-size: 0.95rem; font-weight: 600;
    line-height: 1.35; text-decoration: none !important;
}
.nc-title:hover { color: var(--accent-amber) !important; }
.nc-why { color: var(--text-secondary); font-size: 0.82rem; margin-top: 4px; }
.nc-src { color: var(--text-muted); font-family: 'JetBrains Mono', monospace;
    font-size: 0.68rem; margin-top: 5px; letter-spacing: 0.03em; }
</style>
""", unsafe_allow_html=True)


def _card(it, force_watch=False):
    imp = it.get("importance")
    cls = "imp-watch" if (force_watch and it.get("watch")) else \
        {"high": "imp-high", "medium": "imp-medium", "low": "imp-low"}.get(imp, "imp-low")
    badge = {"high": ("high", "BIG"), "medium": ("medium", "NOTABLE"),
             "low": ("low", "MINOR")}.get(imp)
    head = ""
    if badge:
        head += f'<span class="nc-badge {badge[0]}">{badge[1]}</span>'
    if it.get("category") and it["category"] != "Other" and not force_watch:
        head += f'<span class="nc-src">{html.escape(it["category"])}</span>'
    if it.get("watch"):
        head += f'<span class="nc-watch">👁 {html.escape(it["watch"])}</span>'
    title = html.escape(it["title"])
    link = it.get("link")
    title_html = (f'<a class="nc-title" href="{html.escape(link)}" target="_blank" '
                  f'rel="noopener">{title}</a>') if link else f'<span class="nc-title">{title}</span>'
    why = f'<div class="nc-why">{html.escape(it["why"])}</div>' if it.get("why") else ""
    return (f'<div class="news-card {cls}"><div class="nc-head">{head}</div>'
            f'{title_html}{why}<div class="nc-src">{html.escape(it.get("source", ""))}</div></div>')


def _cards(items, force_watch=False):
    st.markdown("".join(_card(it, force_watch) for it in items), unsafe_allow_html=True)


def render_regime():
    st.markdown('<div class="news-group">📊 Market Regime</div>', unsafe_allow_html=True)
    breadth = load_market_breadth_cache()
    vix_df = load_vix_cache()
    if not breadth and vix_df is None:
        st.markdown('<div class="home-warn">Regime data not built yet — run '
                    '<code>python refresh_cache.py</code>.</div>', unsafe_allow_html=True)
        return
    tiles = []
    if breadth:
        regime = breadth.get("regime", "Unknown")
        color = {"Broadly Bullish": "var(--tv-green)", "Broadly Bearish": "var(--tv-red)"}.get(
            regime, "var(--accent-amber)")
        tiles.append(tile("Regime", regime, "breadth + Nifty vs 200SMA", color))
        bp = breadth.get("breadth_pct_above_200sma")
        if bp is not None:
            tiles.append(tile("Breadth", f"{bp:.0f}%", "stocks above 200-day SMA"))
        na = breadth.get("nifty_above_200sma")
        if na is not None:
            tiles.append(tile("Nifty vs 200SMA", "ABOVE" if na else "BELOW", "long-term trend",
                              "var(--tv-green)" if na else "var(--tv-red)"))
        vp = breadth.get("market_vol_percentile")
        if vp is not None:
            mult, _ = vol_regime_multiplier(vp)
            lbl, col = (("Favourable", "var(--tv-green)") if mult >= 0.9 else
                        ("Moderate", "var(--accent-amber)") if mult >= 0.7 else
                        ("Unfavourable", "var(--tv-red)"))
            tiles.append(tile("Mean-Reversion", lbl,
                              f"vol pct {vp*100:.0f} · RSI&lt;30 sizing ×{mult:.2f}", col))
    if vix_df is not None and len(vix_df):
        try:
            vix = float(vix_df["close"].iloc[-1])
            tiles.append(tile("India VIX", f"{vix:.2f}",
                              "high = fear (mean-reversion fuel)" if vix >= 18 else "calm tape"))
        except Exception:
            pass
    st.markdown(f'<div class="panel-grid">{"".join(tiles)}</div>', unsafe_allow_html=True)


def render_mood():
    """One at-a-glance market-mood gauge, derived from data already loaded (no API call):
    today's Nifty move + breadth + Nifty vs 200SMA. Complements the discrete regime tiles."""
    quotes, _ = market_snapshot()
    nifty = next((q for q in quotes if q["label"] == "NIFTY 50"), None)
    b = load_market_breadth_cache() or {}
    score = mood_score(nifty["chg_pct"] if nifty else None,
                       b.get("breadth_pct_above_200sma"), b.get("nifty_above_200sma"))
    label, color = mood_label(score)
    pos = (score + 1) / 2 * 100
    st.markdown(
        f'<div class="mood-wrap"><span class="mood-cap">Market Mood</span>'
        f'<div class="mood-track"><div class="mood-marker" style="left:{pos:.0f}%"></div></div>'
        f'<span class="mood-label" style="color:{color}">{label}</span></div>',
        unsafe_allow_html=True)


def render_alerts():
    """Exit-signal alerts for open positions. Reuses the SHARED exit rule (tools.exit_verdict)
    that the alert watcher and on-demand check use - never a second copy (CLAUDE.md rule #6)."""
    from trade_journal import check_exit_signals
    sigs = check_exit_signals()
    if isinstance(sigs, str):
        return  # "No open positions to check."
    try:
        from tools import exit_verdict
    except Exception:
        return  # tools unavailable - skip alerts rather than crash the home page
    alerts = []
    for s in sigs:
        if s.get("error"):
            continue
        cur = ltp(s["ticker"])
        try:
            stop, target = float(s["stop_loss"]), float(s["target"])
        except (TypeError, ValueError):
            continue
        if cur is None:
            continue
        code, msg = exit_verdict(cur, stop, target, s["days_held"], s["horizon"])
        if code != "hold":
            alerts.append({"tk": s["ticker"], "code": code, "msg": msg})
    if not alerts:
        st.markdown('<div class="news-group">🔔 Alerts</div>', unsafe_allow_html=True)
        st.markdown('<div class="alert-ok">✓ No exit signals — all open positions are within '
                    'their validated stop / target / time rules.</div>', unsafe_allow_html=True)
        return
    st.markdown(f'<div class="news-group">🔔 Alerts ({len(alerts)})</div>', unsafe_allow_html=True)
    cards = "".join(
        f'<div class="alert-card alert-{a["code"]}"><span class="alert-tag">{a["code"]}</span>'
        f'<b>{html.escape(a["tk"].replace(".NS", ""))}</b> — {html.escape(a["msg"])}</div>'
        for a in alerts)
    st.markdown(cards, unsafe_allow_html=True)
    ticker_buttons([a["tk"] for a in alerts], "al", "Review an alerted position in the Assistant →")


def render_positions():
    recs = open_positions_records()
    today = datetime.now(IST).date()
    rows, open_unreal, unreal_known = "", 0.0, False
    for r in recs:
        entry, shares = r.get("entry_price"), r.get("shares")
        cur_ltp = ltp(r["ticker"])
        if entry and cur_ltp:
            pnl_pct = (cur_ltp - entry) / entry * 100
            pnl_amt = (cur_ltp - entry) * (shares or 0)
            open_unreal += pnl_amt
            unreal_known = True
            cls = "pnl-pos" if pnl_pct >= 0 else "pnl-neg"
            pnl_pct_s = f'<span class="{cls}">{pnl_pct:+.2f}%</span>'
            pnl_amt_s = f'<span class="{cls}">₹{pnl_amt:,.0f}</span>'
            ltp_s = f"₹{cur_ltp:,.1f}"
        else:
            pnl_pct_s = pnl_amt_s = ltp_s = "—"
        try:
            days = (today - datetime.strptime(str(r["entry_date"]), "%Y-%m-%d").date()).days
        except Exception:
            days = "—"
        stop = f"₹{r['stop_loss']:,.1f}" if r.get("stop_loss") else "—"
        tgt = f"₹{r['target']:,.1f}" if r.get("target") else "—"
        entry_s = f"₹{entry:,.1f}" if entry else "—"
        tk = html.escape(str(r["ticker"]).replace(".NS", ""))
        rows += (f"<tr><td><span class='pos-tk'>{tk}</span></td><td>{r.get('term','')}</td>"
                 f"<td>{entry_s}</td><td>{ltp_s}</td><td>{pnl_pct_s}</td><td>{pnl_amt_s}</td>"
                 f"<td>{stop}</td><td>{tgt}</td><td>{days}</td></tr>")

    # --- All-time P&L scorecard ---
    summ = realized_pnl_summary()
    rp = summ["realized_inr"]
    tiles = [tile("Realized P&amp;L · all-time", f"₹{rp:,.0f}",
                  f"{summ['n_closed']} closed trade(s)", pnl_color(rp))]
    if recs:
        unreal_s = f"₹{open_unreal:,.0f}" if unreal_known else "—"
        tiles.append(tile("Open P&amp;L · unrealized", unreal_s, f"{len(recs)} position(s)",
                          pnl_color(open_unreal) if unreal_known else None))
        net = rp + (open_unreal if unreal_known else 0.0)
        tiles.append(tile("Net P&amp;L", f"₹{net:,.0f}", "realized + open", pnl_color(net)))
    if summ["win_rate"] is not None:
        tiles.append(tile("Win Rate", f"{summ['win_rate']:.0f}%",
                          f"{summ['wins']}/{summ['n_closed']} winners"))
    st.markdown('<div class="news-group">💰 P&amp;L Scorecard</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="panel-grid">{"".join(tiles)}</div>', unsafe_allow_html=True)

    # --- Open positions table ---
    st.markdown(f'<div class="news-group">💼 Open Positions ({len(recs)})</div>',
                unsafe_allow_html=True)
    if not recs:
        st.markdown('<div class="stat-sub" style="padding:4px 2px;">No open positions logged. '
                    'Log trades in the Assistant and they appear here with live P&amp;L.</div>',
                    unsafe_allow_html=True)
        return
    st.markdown(
        '<div class="pos-wrap"><table class="pos-table"><thead><tr>'
        '<th>Ticker</th><th>Term</th><th>Entry</th><th>LTP</th><th>P&L %</th><th>P&L ₹</th>'
        '<th>Stop</th><th>Target</th><th>Days</th></tr></thead><tbody>'
        + rows + '</tbody></table></div>', unsafe_allow_html=True)
    ticker_buttons([r["ticker"] for r in recs], "pos", "Audit a position in the Assistant →")


# --- Terminal header + running ticker ---
now = datetime.now(IST)
st.markdown(f"""
<div class="terminal-header"><div class="terminal-title-row">
  <div class="terminal-title"><span class="terminal-logo">📰</span> MARKET INTELLIGENCE HOME</div>
  <div class="terminal-eod-pill">● {now.strftime('%d %b %Y · %I:%M %p IST')}</div>
</div><div class="terminal-sub">Curated market news &amp; snapshot · your daily first read</div></div>
""", unsafe_allow_html=True)
render_market_strip()
render_mood()

st.markdown("<div style='margin-top:0.8rem;'></div>", unsafe_allow_html=True)
render_alerts()
render_regime()
render_positions()
st.markdown("<div style='margin-top:0.8rem;'></div>", unsafe_allow_html=True)

# --- Curated news (interactive: filter chips, search, Live auto-refresh, click-through) ---
tc1, tc2, tc3 = st.columns([5, 1.1, 1.2])
tc1.markdown('<div class="news-group" style="border:none;margin-top:0.5rem;">What actually '
             'matters today</div>', unsafe_allow_html=True)
live = tc2.toggle("🔴 Live", value=False, key="news_live",
                  help="Auto-refresh the panel every 60s (news itself re-ranks every "
                       f"{CACHE_TTL_MIN} min)")
if tc3.button("🔄 Refresh", use_container_width=True, help="Re-fetch & re-rank now"):
    st.session_state["_force_news"] = True


@st.fragment(run_every=(60 if live else None))
def render_news_section():
    force = st.session_state.pop("_force_news", False)
    payload = get_ranked_news(force=force)
    top, more = payload.get("top", []), payload.get("more", [])

    f1, f2 = st.columns([2, 3])
    imp = f1.segmented_control("imp", ["All", "🔴 Big", "🟠 Notable+", "👁 Watchlist"],
                               default="All", label_visibility="collapsed", key="news_imp")
    query = (f2.text_input("q", placeholder="🔎 Search headlines…",
                           label_visibility="collapsed", key="news_q") or "").strip().lower()

    def keep(it):
        if query and query not in it["title"].lower():
            return False
        if imp == "🔴 Big":
            return it.get("importance") == "high"
        if imp == "🟠 Notable+":
            return it.get("importance") in ("high", "medium")
        if imp == "👁 Watchlist":
            return bool(it.get("watch"))
        return True

    ftop = [it for it in top if keep(it)]
    fmore = [it for it in more if keep(it)]

    if not top and not more:
        st.markdown('<div class="home-warn">No news yet today. RSS may be unreachable, or no '
                    '<code>*_NEWS_API</code> key is set.</div>', unsafe_allow_html=True)
    elif not ftop and not fmore:
        st.markdown('<div class="stat-sub" style="padding:6px 2px;">No headlines match this '
                    'filter.</div>', unsafe_allow_html=True)
    else:
        if not any(it.get("importance") for it in top):
            st.markdown('<div class="home-warn">⚠️ Showing raw feed by recency — the news LLM '
                        "didn't run (transient API issue); it retries automatically. Hit 🔄 to "
                        "retry now.</div>", unsafe_allow_html=True)
        watch_items = [it for it in ftop if it.get("watch")]
        if watch_items:
            st.markdown('<div class="news-group">👁 On your watchlist</div>', unsafe_allow_html=True)
            _cards(watch_items, force_watch=True)
            ticker_buttons([it["watch"] for it in watch_items], "wn",
                           "Analyze a watchlist name in the Assistant →")
        for cat in CATEGORIES:
            group = [it for it in ftop if it.get("category") == cat and not it.get("watch")]
            if not group:
                continue
            st.markdown(f'<div class="news-group">{cat}</div>', unsafe_allow_html=True)
            _cards(group)
        if fmore:
            with st.expander(f"Show {len(fmore)} filtered / minor headlines"):
                _cards(fmore)

    if payload.get("generated_at"):
        try:
            gen = datetime.fromisoformat(payload["generated_at"])
            mins = int((datetime.now(IST) - gen).total_seconds() // 60)
            ago = "just now" if mins <= 0 else f"{mins} min ago"
        except Exception:
            ago = payload["generated_at"][11:16]
        st.caption(f"Updated {ago} · auto-refreshes every {CACHE_TTL_MIN} min (or 🔄) · "
                   f"{len(top)} kept, {len(more)} filtered · {payload.get('provider')}"
                   + (" · 🔴 LIVE" if live else ""))


render_news_section()

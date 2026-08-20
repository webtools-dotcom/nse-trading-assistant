"""Trade Journal & Portfolio History Page.
Display-only: reads trade log via trade_journal.py, calculates cumulative equity curve,
renders closed trades history and strategy health metrics.
"""

import html
from datetime import datetime
import streamlit as st
import pandas as pd

from ui_common import inject_theme, render_nav, IST, tile, pnl_color, ticker_buttons, ltp
from trade_journal import (_load_log, realized_pnl_summary, open_positions_records,
                           get_strategy_health, _parse_date)

st.set_page_config(
    page_title="Trade Journal & History",
    page_icon="📒",
    layout="wide",
    initial_sidebar_state="expanded"
)
inject_theme()
render_nav("journal")

# Hide sidebar CSS
st.markdown("""
<style>
section[data-testid="stSidebar"],
[data-testid="collapsedControl"], [data-testid="stSidebarCollapsedControl"] {
    display: none !important;
}
.block-container { max-width: 1260px !important; }

.health-card {
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
    padding: 14px 18px;
    margin: 8px 0;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
    line-height: 1.5;
    white-space: pre-wrap;
    color: var(--text-primary);
}
</style>
""", unsafe_allow_html=True)

# Terminal Header
now = datetime.now(IST)
st.markdown(f"""
<div class="terminal-header"><div class="terminal-title-row">
  <div class="terminal-title"><span class="terminal-logo">📒</span> TRADE JOURNAL &amp; PORTFOLIO HISTORY</div>
  <div class="terminal-eod-pill">● {now.strftime('%d %b %Y · %I:%M %p IST')}</div>
</div><div class="terminal-sub">Realized performance metrics, equity progression &amp; quantitative execution health</div></div>
""", unsafe_allow_html=True)

# 1. Summary Scorecard Row
summ = realized_pnl_summary()
rp = summ["realized_inr"]

scorecard_tiles = [
    tile("Realized P&amp;L", f"₹{rp:+,.0f}", f"{summ['n_closed']} closed trade(s)", pnl_color(rp)),
    tile("Win Rate", f"{summ['win_rate']:.1f}%" if summ["win_rate"] is not None else "—",
         f"{summ['wins']}/{summ['n_closed']} winners" if summ["n_closed"] else "no trades yet",
         "var(--tv-green)" if (summ["win_rate"] or 0) >= 50 else "var(--text-primary)"),
    tile("Best Trade", f"{summ['best_pct']:+.2f}%" if summ["best_pct"] is not None else "—",
         "highest return", "var(--tv-green)"),
    tile("Worst Trade", f"{summ['worst_pct']:+.2f}%" if summ["worst_pct"] is not None else "—",
         "largest drawdown", "var(--tv-red)"),
]

st.markdown('<div class="news-group">💰 Performance Scorecard (All-Time Realized)</div>', unsafe_allow_html=True)
st.markdown(f'<div class="panel-grid">{"".join(scorecard_tiles)}</div>', unsafe_allow_html=True)

# Load trade log
df_log = _load_log()
closed_df = df_log[df_log['status'].astype(str).str.lower() != 'open'].copy() if len(df_log) else pd.DataFrame()

# 2. Cumulative Equity Curve
st.markdown('<div class="news-group">📈 Cumulative Realized Equity Curve (₹)</div>', unsafe_allow_html=True)

if len(closed_df) >= 2:
    try:
        closed_sorted = closed_df.copy()
        for c in ('entry_price', 'exit_price', 'shares', 'return_pct'):
            closed_sorted[c] = pd.to_numeric(closed_sorted[c], errors='coerce')
        closed_sorted = closed_sorted.dropna(subset=['entry_price', 'exit_price', 'shares'])
        closed_sorted['pnl_inr'] = (closed_sorted['exit_price'] - closed_sorted['entry_price']) * closed_sorted['shares']
        
        # Sort chronologically by exit_date
        closed_sorted['_parsed_exit'] = closed_sorted['exit_date'].apply(_parse_date)
        closed_sorted = closed_sorted.sort_values('_parsed_exit')
        
        closed_sorted['Cumulative P&L (₹)'] = closed_sorted['pnl_inr'].cumsum()
        closed_sorted['Exit Date'] = closed_sorted['exit_date'].astype(str)
        
        chart_df = closed_sorted.set_index('Exit Date')[['Cumulative P&L (₹)']]
        st.line_chart(chart_df, color="#089981")
    except Exception as e:
        st.markdown(f'<div class="stat-sub">Unable to render curve: {html.escape(str(e))}</div>', unsafe_allow_html=True)
else:
    st.markdown('<div class="stat-sub" style="padding:10px 2px;">Log at least 2 closed trades in the Assistant to visualize your cumulative equity curve.</div>', unsafe_allow_html=True)

# 3. Open Positions
recs = open_positions_records()
if recs:
    st.markdown(f'<div class="news-group">💼 Open Positions ({len(recs)})</div>', unsafe_allow_html=True)
    today = datetime.now(IST).date()
    rows = ""
    for r in recs:
        entry, shares = r.get("entry_price"), r.get("shares")
        cur_ltp = ltp(r["ticker"])
        if entry and cur_ltp:
            pnl_pct = (cur_ltp - entry) / entry * 100
            pnl_amt = (cur_ltp - entry) * (shares or 0)
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
    
    st.markdown(
        '<div class="pos-wrap"><table class="pos-table"><thead><tr>'
        '<th>Ticker</th><th>Term</th><th>Entry</th><th>LTP</th><th>P&L %</th><th>P&L ₹</th>'
        '<th>Stop</th><th>Target</th><th>Days</th></tr></thead><tbody>'
        + rows + '</tbody></table></div>', unsafe_allow_html=True)
    ticker_buttons([r["ticker"] for r in recs], "j_open", "Audit position in Assistant →")

# 4. Closed Trades Table
st.markdown(f'<div class="news-group">📜 Closed Trades History ({len(closed_df)})</div>', unsafe_allow_html=True)

if len(closed_df) == 0:
    st.markdown('<div class="stat-sub" style="padding:8px 2px;">No closed trades logged yet. Closed trades will appear here with audited entry/exit pricing and holding periods.</div>', unsafe_allow_html=True)
else:
    try:
        closed_display = closed_df.copy()
        for c in ('entry_price', 'exit_price', 'shares', 'return_pct', 'holding_days'):
            closed_display[c] = pd.to_numeric(closed_display[c], errors='coerce')
        closed_display['_parsed_exit'] = closed_display['exit_date'].apply(_parse_date)
        closed_display = closed_display.sort_values('_parsed_exit', ascending=False)
        
        table_rows = ""
        for _, r in closed_display.iterrows():
            tk = html.escape(str(r.get('ticker', '')).replace(".NS", ""))
            term = html.escape(str(r.get('term', '')))
            ent_d = html.escape(str(r.get('entry_date', '—')))
            ext_d = html.escape(str(r.get('exit_date', '—')))
            ent_p = f"₹{r['entry_price']:,.1f}" if pd.notna(r.get('entry_price')) else "—"
            ext_p = f"₹{r['exit_price']:,.1f}" if pd.notna(r.get('exit_price')) else "—"
            
            ret = r.get('return_pct')
            if pd.notna(ret):
                ret_val = float(ret)
                cls = "pnl-pos" if ret_val >= 0 else "pnl-neg"
                pnl_pct_s = f'<span class="{cls}">{ret_val:+.2f}%</span>'
                shares = r.get('shares', 0)
                if pd.notna(shares) and pd.notna(r.get('entry_price')) and pd.notna(r.get('exit_price')):
                    pnl_amt = (float(r['exit_price']) - float(r['entry_price'])) * float(shares)
                    pnl_amt_s = f'<span class="{cls}">₹{pnl_amt:+,.0f}</span>'
                else:
                    pnl_amt_s = "—"
            else:
                pnl_pct_s, pnl_amt_s = "—", "—"
                
            reason = html.escape(str(r.get('exit_type', '—')))
            days = f"{int(r['holding_days'])}" if pd.notna(r.get('holding_days')) else "—"
            
            table_rows += (f"<tr><td><span class='pos-tk'>{tk}</span></td><td>{term}</td>"
                          f"<td>{ent_d}</td><td>{ext_d}</td><td>{ent_p}</td><td>{ext_p}</td>"
                          f"<td>{pnl_pct_s}</td><td>{pnl_amt_s}</td><td>{reason}</td><td>{days}</td></tr>")
        
        st.markdown(
            '<div class="pos-wrap"><table class="pos-table"><thead><tr>'
            '<th>Ticker</th><th>Term</th><th>Entry Date</th><th>Exit Date</th><th>Entry Price</th>'
            '<th>Exit Price</th><th>P&L %</th><th>P&L ₹</th><th>Exit Type</th><th>Days Held</th></tr></thead><tbody>'
            + table_rows + '</tbody></table></div>', unsafe_allow_html=True)
    except Exception as e:
        st.markdown(f'<div class="stat-sub">Error formatting closed trade history: {html.escape(str(e))}</div>', unsafe_allow_html=True)

# 5. Discipline & Strategy Health
st.markdown('<div class="news-group">🔬 Quantitative Strategy Health (Execution vs Backtest)</div>', unsafe_allow_html=True)

col_h_short, col_h_long = st.columns(2)
with col_h_short:
    st.markdown('<div class="stat-sub" style="font-weight:700;margin-bottom:4px;color:var(--accent-amber);">Short-Term Swing Strategy Health</div>', unsafe_allow_html=True)
    try:
        health_short = get_strategy_health('short')
        st.markdown(f'<div class="health-card">{html.escape(health_short)}</div>', unsafe_allow_html=True)
    except Exception as e:
        st.markdown(f'<div class="health-card">Unable to load short health: {html.escape(str(e))}</div>', unsafe_allow_html=True)

with col_h_long:
    st.markdown('<div class="stat-sub" style="font-weight:700;margin-bottom:4px;color:var(--accent-amber);">Long-Term Momentum Strategy Health</div>', unsafe_allow_html=True)
    try:
        health_long = get_strategy_health('long')
        st.markdown(f'<div class="health-card">{html.escape(health_long)}</div>', unsafe_allow_html=True)
    except Exception as e:
        st.markdown(f'<div class="health-card">Unable to load long health: {html.escape(str(e))}</div>', unsafe_allow_html=True)

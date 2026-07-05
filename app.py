import streamlit as st
from agent import TradingAgent
from config import WATCHLIST

st.set_page_config(page_title="NSE Swing Trading Assistant", page_icon="📈")
st.title("📈 NSE Swing Trading Assistant")
st.caption("Personal research tool — not financial advice. Model signals are weak; always verify independently.")

if "agent" not in st.session_state:
    st.session_state.agent = TradingAgent()
    st.session_state.messages = []

with st.sidebar:
    st.header("Settings")
    if st.button("🔄 Reset Conversation"):
        st.session_state.agent.reset()
        st.session_state.messages = []
        st.rerun()
    st.markdown("---")
    st.markdown("**Watchlist:**")
    st.write(", ".join([t.replace(".NS", "") for t in WATCHLIST]))

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Ask about a stock, your watchlist, or position sizing..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Researching..."):
            response = st.session_state.agent.ask(prompt)
        st.markdown(response)
    st.session_state.messages.append({"role": "assistant", "content": response})
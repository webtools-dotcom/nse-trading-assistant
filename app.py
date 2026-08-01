import streamlit as st
import os
import json
import uuid
from datetime import datetime
from agent import TradingAgent
from config import WATCHLIST

st.set_page_config(page_title="NSE Swing Trading Assistant", page_icon="📈")
st.title("📈 NSE Swing Trading Assistant")
st.caption("Personal research tool — not financial advice. Model signals are weak; always verify independently.")

CONV_DIR = "conversations"
os.makedirs(CONV_DIR, exist_ok=True)


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

with st.sidebar:
    st.header("Settings")

    if st.button("🆕 New Chat"):
        start_new_conversation()
        st.rerun()

    st.markdown("---")
    st.markdown("**🕘 Past Conversations**")

    past_convos = list_conversations()
    if len(past_convos) == 0:
        st.caption("No saved conversations yet.")
    else:
        for c in past_convos:
            label = c["title"] if len(c["title"]) < 40 else c["title"][:37] + "..."
            col1, col2 = st.columns([5, 1])
            with col1:
                if st.button(label, key=f"conv_{c['id']}"):
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

    save_conversation(st.session_state.session_id, st.session_state.messages, st.session_state.agent.conversation_history)
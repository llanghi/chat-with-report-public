import json
import os
import time
import requests
import streamlit as st

API_URL_DEFAULT = os.getenv("RAG_API_URL", "http://127.0.0.1:7861/ask")

st.set_page_config(page_title="Chat with the Report", page_icon="📄", layout="wide")

# Sidebar
st.sidebar.header("Settings")
api_url = st.sidebar.text_input("Backend URL", API_URL_DEFAULT)
show_citations = st.sidebar.checkbox("Show citations", value=True)
clear_chat = st.sidebar.button("Clear conversation")

# Session state
if clear_chat or "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.messages.append({"role": "assistant", "content": "Ask a question about the CSIRO-GESIRA report on resources in the Northern Perth Basin."})

st.title("Ask a question about CSIRO-GISERA report")
st.caption("Local RAG: LlamaIndex + PyMuPDF + FastAPI")

# Chat display
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# Input box
q = st.chat_input("Type your question and press Enter")
if q:
    st.session_state.messages.append({"role": "user", "content": q})
    with st.chat_message("user"):
        st.markdown(q)

    # Call backend
    try:
        t0 = time.time()
        resp = requests.post(api_url, json={"question": q}, timeout=90)
        t1 = time.time()
        if resp.status_code != 200:
            raise RuntimeError(resp.text)

        data = resp.json()
        answer = data.get("answer", "").strip() or "(no answer)"
        citations = data.get("citations", [])

        # Render assistant answer
        with st.chat_message("assistant"):
            st.markdown(answer)
            st.caption(f"Response time: {t1 - t0:.2f}s")

            # Optional citations block
            if show_citations and citations:
                st.markdown("**Citations**")
                for i, c in enumerate(citations, start=1):
                    src = c.get("source", "unknown.pdf")
                    page = c.get("page", "?")
                    snip = c.get("snippet", "").strip()
                    # hide pages that are "?"
                    page_label = "" if page == "?" else f" (p.{page})"
                    with st.expander(f"{i}. {src}{page_label}", expanded=False):
                        st.write(snip if snip else "_no snippet_")

        st.session_state.messages.append({"role": "assistant", "content": answer})

    except Exception as e:
        err = f"Backend error: {e}"
        with st.chat_message("assistant"):
            st.error(err)
        st.session_state.messages.append({"role": "assistant", "content": err})





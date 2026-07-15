"""
keyword_manager.py
────────────────────────────────────────────────────────────
Streamlit app for keyword management + .pptx extraction.

Run separately from the main listener:
    streamlit run keyword_manager.py

Connects to the SAME SQLite database the listener uses.
────────────────────────────────────────────────────────────
"""

import os
import sys

import streamlit as st
import pandas as pd

# Ensure src/ is importable when run from project root
sys.path.insert(0, os.path.dirname(__file__))

from src.storage.database import DatabaseHandler, init_db
from src.processing.pptx_extractor import extract_keywords_from_bytes

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", "data/telegram_intel.db")

st.set_page_config(
    page_title="TeleWire — Keyword Manager",
    page_icon="🔑",
    layout="wide",
)

# ── DB ────────────────────────────────────────────────────────────────────────
init_db(DB_PATH)
db = DatabaseHandler(DB_PATH)


# ══════════════════════════════════════════════════════════════════
#  Styling injection
# ══════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }

.main-title {
    font-size: 2rem; font-weight: 800; letter-spacing: -1px;
    background: linear-gradient(135deg, #9f63f3, #60a5fa);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    margin-bottom: 0;
}
.subtitle { color: #64748b; font-size: 0.9rem; margin-bottom: 1.5rem; }
.kw-chip {
    display: inline-block;
    background: rgba(124,58,237,0.15);
    border: 1px solid rgba(124,58,237,0.35);
    border-radius: 20px; padding: 4px 12px;
    color: #a78bfa; font-size: 0.85rem; font-weight: 500;
    margin: 3px;
}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════
#  Header
# ══════════════════════════════════════════════════════════════════
st.markdown('<h1 class="main-title">📡 TeleWire · Keyword Manager</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Manage keywords + extract from .pptx decks. All changes are live within 60 s.</p>', unsafe_allow_html=True)

st.divider()

# ══════════════════════════════════════════════════════════════════
#  Layout: two columns
# ══════════════════════════════════════════════════════════════════
col_left, col_right = st.columns([1, 1], gap="large")

# ── Left: current keyword list ────────────────────────────────────────────────
with col_left:
    st.subheader("🔑 Active Keywords")

    keywords = db.get_keywords()
    if keywords:
        chips_html = "".join(f'<span class="kw-chip">{kw}</span>' for kw in keywords)
        st.markdown(chips_html, unsafe_allow_html=True)
        st.caption(f"{len(keywords)} keyword(s) total")
    else:
        st.info("No keywords yet. Add some on the right.")

    st.divider()

    # ── Add single keyword ────────────────────────────────────────────────────
    st.subheader("➕ Add Keyword")
    with st.form("add_kw_form", clear_on_submit=True):
        new_kw = st.text_input("Keyword / phrase", placeholder="e.g. pump signal")
        submitted = st.form_submit_button("Add Keyword", type="primary")
        if submitted and new_kw.strip():
            if db.add_keyword(new_kw.strip(), source="streamlit"):
                st.success(f"Added: **{new_kw.strip()}**")
                st.rerun()
            else:
                st.warning("Keyword already exists or is invalid.")

    st.divider()

    # ── Delete keyword ────────────────────────────────────────────────────────
    st.subheader("🗑️ Remove Keyword")
    if keywords:
        kw_to_delete = st.selectbox("Select keyword to remove", options=keywords, index=0)
        if st.button("Remove Selected", type="secondary"):
            db.delete_keyword(kw_to_delete)
            st.success(f"Removed: **{kw_to_delete}**")
            st.rerun()
    else:
        st.caption("Nothing to remove.")

# ── Right: .pptx uploader ────────────────────────────────────────────────────
with col_right:
    st.subheader("📎 Extract Keywords from .pptx")
    st.caption("Upload a presentation deck — text from every slide is parsed and cleaned.")

    uploaded = st.file_uploader("Choose a .pptx file", type=["pptx"])

    if uploaded is not None:
        pptx_bytes = uploaded.read()
        with st.spinner("Extracting keywords …"):
            candidates = extract_keywords_from_bytes(pptx_bytes)

        if not candidates:
            st.warning("No meaningful keywords found in this file.")
        else:
            st.success(f"Found **{len(candidates)}** keyword candidates.")

            # Let user select which ones to keep
            selected = st.multiselect(
                "Select keywords to add",
                options=candidates,
                default=candidates,
                help="Deselect any tokens that are not useful.",
            )

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("✅ Add Selected", type="primary"):
                    added = 0
                    for kw in selected:
                        if db.add_keyword(kw, source="pptx"):
                            added += 1
                    st.success(f"Added {added} new keyword(s). {len(selected)-added} already existed.")
                    st.rerun()
            with col_b:
                if st.button("Add ALL"):
                    added = 0
                    for kw in candidates:
                        if db.add_keyword(kw, source="pptx"):
                            added += 1
                    st.success(f"Added {added} keyword(s).")
                    st.rerun()

            with st.expander("Preview all candidates"):
                st.dataframe(
                    pd.DataFrame(candidates, columns=["candidate"]),
                    use_container_width=True, height=300
                )

st.divider()

# ══════════════════════════════════════════════════════════════════
#  Keyword table (full view)
# ══════════════════════════════════════════════════════════════════
st.subheader("📋 Full Keyword Table")
if keywords:
    from src.storage.database import get_db
    with get_db(DB_PATH) as conn:
        import sqlite3
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT keyword, source, added_at FROM keywords ORDER BY added_at DESC"
        ).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    df["added_at"] = pd.to_datetime(df["added_at"]).dt.strftime("%Y-%m-%d %H:%M")
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("No keywords in the database yet.")

# ── Footer ────────────────────────────────────────────────────────────────────
st.caption(f"Database: `{os.path.abspath(DB_PATH)}` · Fuzzy threshold: 85/100")

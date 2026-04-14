import sys
import os
import streamlit as st
from google import genai
from google.genai import types
import time
import re
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# --- HÓA GIẢI LỖI ĐƯỜNG DẪN CONTEXT ---
def get_context_helpers():
    try:
        from streamlit.runtime.scriptrunner import add_script_run_context, get_script_run_context
        return add_script_run_context, get_script_run_context
    except ImportError:
        try:
            from streamlit.runtime.scriptrunner.script_run_context import add_script_run_context, get_script_run_context
            return add_script_run_context, get_script_run_context
        except ImportError:
            return (lambda x: None), (lambda: None)

add_script_run_context, get_script_run_context = get_context_helpers()
try: from dotenv import load_dotenv; load_dotenv()
except: pass

# =========================================================
# GIAO DIỆN DARK MODE TỐI GIẢN
# =========================================================
st.set_page_config(page_title="Thiên Quân v71.2", page_icon="🔱", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    [data-testid="stSidebar"] { background-color: #161b22 !important; border-right: 1px solid #30363d; }
    .key-box { padding: 8px; border-radius: 6px; text-align: center; border: 1px solid #30363d; font-size: 0.7rem; margin-bottom: 5px; }
    .k-active { background: #238636; } .k-busy { background: #1f6feb; } .k-dead { background: #da3633; }
    h4 { color: #58a6ff !important; }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# QUẢN LÝ DỮ LIỆU (STATE)
# =========================================================
RAW_KEYS = [os.getenv(f"GEMINI_KEY_{i}") for i in range(1, 21)]
VALID_KEYS = [k.strip() for k in RAW_KEYS if k and len(k.strip()) > 10]

if 'key_manager' not in st.session_state:
    st.session_state.key_manager = {i: {"status": "ACTIVE", "in_use": False, "last_finished": datetime.now() - timedelta(seconds=60), "key": k} for i, k in enumerate(VALID_KEYS)}
if 'results' not in st.session_state: st.session_state.results = {}
if 'glossary' not in st.session_state: st.session_state.glossary = ""
if 'stop_signal' not in st.session_state: st.session_state.stop_signal = False

manager = st.session_state.key_manager
status_lock = threading.Lock()
result_lock = threading.Lock()

# =========================================================
# LÕI AI
# =========================================================
def call_gemini_api(api_key, prompt, content, model):
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=model, contents=f"{prompt}\n\n{content}")
        return response.text.strip() if response.text else "ERR_EMPTY"
    except Exception as e: return f"❌ LỖI: {str(e)}"

# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v71.2")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    model_choice = st.selectbox("🔮 Chọn Pháp Bảo (Model)", [
        "gemini-3-flash-preview", 
        "gemini-3.1-flash-lite-preview",
        "gemini-2.0-flash", 
        "gemini-1.5-flash"
    ], index=0)
    
    st.divider()
    is_safe_mode = st.checkbox("🐢 SAFE MODE (Cho TK Free)", value=True)
    if is_safe_mode: n_workers, c_time, b_size = 1, 30, 30
    else:
        n_workers = st.slider("Số luồng", 1, 10, 5)
        c_time = st.number_input("Giây nghỉ", 5, 60, 15)
        b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)
    
    if st.button("🗑️ DỌN DẸP DỮ LIỆU CŨ"):
        st.session_state.results = {}; st.session_state.stop_signal = False; st.rerun()

# =========================================================
# GIAO DIỆN TABS
# =========================================================
tab1, tab2 = st.tabs(["📝 LINH NHÃN (TỪ ĐIỂN)", "⚔️ KHAI TRẬN DỊCH THUẬT"])

with tab1:
    st.subheader("🏺 Linh Nhãn (Tìm tên nhân vật)")
    if file:
        if st.button("🔍 QUÉT TÊN NHÂN VẬT", type="primary", use_container_width=True):
            key = next((v["key"] for v in manager.values() if v["status"] == "ACTIVE"), VALID_KEYS[0])
            with st.spinner("Đang soi xét danh tính..."):
                p = "Extract Chinese-Vietnamese name glossary. Format: 'Gốc: Dịch'. No explanation."
                st.session_state.glossary = call_gemini_api(key, p, file.getvalue().decode("utf-8-sig")[:30000], model_choice)
            st.rerun()
    st.session_state.glossary = st.text_area("Bảng đối chiếu Trung-Việt:", value=st.session_state.glossary, height=350)

with tab2:
    if not file:
        st.info("💡 Hãy nạp file ở Sidebar.")
    else:
        col_k, col_w = st.columns([1, 3])
        with col_k:
            st.markdown("#### 📡 Key")
            k_places = [st.empty() for _ in range(len(VALID_KEYS))]
        with col_w:
            st.markdown("#### 🌊 Luồng")
            w_places = [st.empty() for _ in range(n_workers)]
            st.divider()
            p_bar = st.progress(0)
            start_btn = st.button("🚀 BẮT ĐẦU KHAI TRẬN", type="primary", use_container_width=True)

# =========================================================
# VẬN HÀNH
# =========================================================
if file and 'start_btn' in locals() and start_btn:
    st.session_state.stop_signal = False
    blocks = [b.strip() for b in re.split(r'\n\s*\n', file.getvalue().decode("utf-8-sig").strip()) if b.strip()]
    batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
    main_ctx = get_script_run_context()
    stats = {"done": 0}
    worker_map = {i: {"msg": "Sẵn sàng"} for i in range(n_workers)}

    def worker_logic(idx, worker_id):
        add_script_run_context(main_ctx)
        if st.session_state.stop_signal: return
        cur_k = None
        while cur_k is None and not st.session_state.stop_signal:
            with status_lock:
                for i, k in manager.items():
                    if k["status"] == "ACTIVE" and not k["in_use"] and (datetime.now() - k["last_finished"]).total_seconds() >= c_time:
                        cur_k = i; k["in_use"] = True; break
            if cur_k is None: time.sleep(1)

        if cur_k is not None:
            worker_map[worker_id]["msg"] = f"Lô {idx+1}: Dịch..."
            prompt = f"Dịch {len(batches[idx])} đoạn SRT sang tiếng Việt Kiếm Hiệp. Từ điển: {st.session_state.glossary}. Trả về SRT thô."
            res = call_gemini_api(manager[cur_k]["key"], prompt, "\n\n".join(batches[idx]), model_choice)
            
            with status_lock:
                manager[cur_k]["last_finished"] = datetime.now(); manager[cur_k]["in_use"] = False
                if "❌" in res:
                    st.session_state.stop_signal = True; st.error(res)
                else:
                    with result_lock: st.session_state.results[idx] = res
                    stats["done"] += 1; worker_map[worker_id]["msg"] = f"Lô {idx+1}: ✅ Xong"

    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        for i in range(len(batches)): executor.submit(worker_logic, i, i % n_workers)
        while stats["done"] < len(batches) and not st.session_state.stop_signal:
            for i, k in manager.items():
                cls = "k-dead" if k["status"] == "DEAD" else ("k-active" if not k["in_use"] else "k-busy")
                k_places[i].markdown(f"<div class='key-box {cls}'>Key {i+1}</div>", unsafe_allow_html=True)
            for i in range(n_workers):
                w_places[i].write(f"**Luồng {i+1}:** {worker_map[i]['msg']}")
            p_bar.progress(stats["done"] / len(batches)); time.sleep(1)

    if stats["done"] == len(batches):
        st.success("🎉 Hoàn tất!")
        st.download_button("📥 Tải về", "\n\n".join([st.session_state.results[i] for i in range(len(batches))]), file_name=f"V71_2_{file.name}", use_container_width=True)
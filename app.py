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
# GIAO DIỆN CHUẨN "HUYỀN VŨ" (GIỐNG HÌNH ẢNH)
# =========================================================
st.set_page_config(page_title="Thiên Quân v71.3 - Huyền Vũ", page_icon="🔱", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    [data-testid="stSidebar"] { background-color: #161b22 !important; border-right: 1px solid #30363d; }
    
    /* Style cho thanh Key giống trong hình */
    .key-box { 
        padding: 12px; 
        border-radius: 8px; 
        text-align: center; 
        font-size: 0.85rem; 
        margin-bottom: 8px; 
        font-weight: 500;
        width: 100%;
        color: white;
        transition: all 0.3s;
    }
    .k-active { background-color: #238636; border: 1px solid #2ea043; } /* Xanh lá */
    .k-busy { background-color: #1f6feb; border: 1px solid #388bfd; }   /* Xanh dương */
    .k-dead { background-color: #da3633; border: 1px solid #f85149; }   /* Đỏ */
    
    /* Style cho Worker */
    .w-box {
        padding: 10px;
        background: #161b22;
        border-left: 4px solid #58a6ff;
        margin-bottom: 5px;
        font-size: 0.85rem;
        border-radius: 4px;
    }

    /* Style cho nút Bắt đầu màu đỏ rộng */
    div.stButton > button {
        background-color: #ff4b4b !important;
        color: white !important;
        border: none !important;
        padding: 15px !important;
        font-size: 1.1rem !important;
        font-weight: bold !important;
        border-radius: 10px !important;
    }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# QUẢN LÝ DỮ LIỆU
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
    st.title("🔱 THIÊN QUÂN v71.3")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    model_choice = st.selectbox("🔮 Pháp bảo (Model)", ["gemini-3-flash-preview", "gemini-3.1-flash-lite-preview", "gemini-2.0-flash", "gemini-1.5-flash"])
    st.divider()
    is_safe_mode = st.checkbox("🐢 SAFE MODE", value=True)
    if is_safe_mode: n_workers, c_time, b_size = 1, 30, 30
    else:
        n_workers = st.slider("Số luồng xử lý", 1, 10, 5)
        c_time = st.number_input("Giây nghỉ/Key", 5, 60, 15)
        b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)
    
    if st.button("🗑️ RESET"):
        st.session_state.results = {}; st.session_state.stop_signal = False; st.rerun()

# =========================================================
# GIAO DIỆN CHÍNH
# =========================================================
tab1, tab2 = st.tabs(["📝 LINH NHÃN (TỪ ĐIỂN)", "⚔️ KHAI TRẬN"])

with tab1:
    st.subheader("🏺 Linh Nhãn")
    if file and st.button("🔍 QUÉT TÊN NHÂN VẬT", type="primary"):
        key = next((v["key"] for v in manager.values() if v["status"] == "ACTIVE"), VALID_KEYS[0])
        with st.spinner("Đang soi xét..."):
            p = "Extract glossary: 'Original: Vietnamese'. No explanation."
            st.session_state.glossary = call_gemini_api(key, p, file.getvalue().decode("utf-8-sig")[:30000], model_choice)
        st.rerun()
    st.session_state.glossary = st.text_area("Từ điển:", value=st.session_state.glossary, height=350)

with tab2:
    if not file:
        st.info("💡 Hãy nạp file ở Sidebar.")
    else:
        # BỐ CỤC CHUẨN HÌNH ẢNH: Key bên trái, Worker bên phải
        col_k, col_w = st.columns([1, 2])
        
        with col_k:
            st.markdown("#### 📡 Trạng Thái Key")
            k_places = [st.empty() for _ in range(len(VALID_KEYS))]
            
        with col_w:
            st.markdown("#### 🌊 Trạng Thái Luồng")
            w_places = [st.empty() for _ in range(n_workers)]
            
        st.divider() # Thanh kẻ trắng như trong hình
        p_bar = st.progress(0)
        
        # Nút bắt đầu đỏ rực, rộng toàn màn hình
        start_btn = st.button("🚀 BẮT ĐẦU (LỖI LÀ DỪNG LUÔN)", use_container_width=True)

# =========================================================
# VẬN HÀNH LUỒNG
# =========================================================
if file and 'start_btn' in locals() and start_btn:
    st.session_state.stop_signal = False
    blocks = [b.strip() for b in re.split(r'\n\s*\n', file.getvalue().decode("utf-8-sig").strip()) if b.strip()]
    batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
    main_ctx = get_script_run_context()
    stats = {"done": 0}
    worker_map = {i: {"msg": "Đang chờ..."} for i in range(n_workers)}

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
            worker_map[worker_id]["msg"] = f"⏳ Lô {idx+1}: Đang dịch..."
            p = f"Translate {len(batches[idx])} SRT blocks to Wuxia style. Glossary: {st.session_state.glossary}. Raw SRT only."
            res = call_gemini_api(manager[cur_k]["key"], p, "\n\n".join(batches[idx]), model_choice)
            
            with status_lock:
                manager[cur_k]["last_finished"] = datetime.now(); manager[cur_k]["in_use"] = False
                if "❌" in res:
                    st.session_state.stop_signal = True; st.error(res)
                else:
                    with result_lock: st.session_state.results[idx] = res
                    stats["done"] += 1; worker_map[worker_id]["msg"] = f"✅ Lô {idx+1}: Hoàn tất"

    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        for i in range(len(batches)): executor.submit(worker_logic, i, i % n_workers)
        
        while stats["done"] < len(batches) and not st.session_state.stop_signal:
            # Vẽ lại Key theo phong cách "thanh dài"
            for i, k in manager.items():
                cls = "k-dead" if k["status"] == "DEAD" else ("k-active" if not k["in_use"] else "k-busy")
                txt = f"Key {i+1}"
                k_places[i].markdown(f"<div class='key-box {cls}'>{txt}</div>", unsafe_allow_html=True)
            
            # Vẽ lại Worker
            for i in range(n_workers):
                w_places[i].markdown(f"<div class='w-box'><b>Luồng {i+1}:</b> {worker_map[i]['msg']}</div>", unsafe_allow_html=True)
            
            p_bar.progress(stats["done"] / len(batches)); time.sleep(1)

    if stats["done"] == len(batches):
        st.success("🎉 Xuất sắc! Bí tịch đã dịch xong.")
        final_srt = "\n\n".join([st.session_state.results[i] for i in range(len(batches))])
        st.download_button("📥 TẢI BẢN DỊCH", final_srt, file_name=f"V71_3_{file.name}", use_container_width=True)
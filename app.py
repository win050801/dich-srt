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

# --- HÓA GIẢI LỖI CONTEXT ---
try:
    from streamlit.runtime.scriptrunner import add_script_run_context, get_script_run_context
except ImportError:
    def add_script_run_context(*args, **kwargs): pass
    def get_script_run_context(*args, **kwargs): return None

try: from dotenv import load_dotenv; load_dotenv()
except: pass

st.set_page_config(page_title="Thiên Quân v70.6 - Chiếu Yêu Kính", page_icon="🔱", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    [data-testid="stSidebar"] { background-color: #161b22 !important; border-right: 1px solid #30363d; }
    .error-box { 
        padding: 10px; 
        background-color: #3e0b0b; 
        color: #ff9b9b; 
        border: 1px solid #da3633; 
        border-radius: 5px; 
        font-family: 'Courier New', monospace;
        font-size: 0.85rem;
        margin-bottom: 5px;
    }
    .status-msg { font-size: 0.8rem; color: #8b949e; }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# QUẢN LÝ KEY & TRẠNG THÁI
# =========================================================
RAW_KEYS = [os.getenv(f"GEMINI_KEY_{i}") for i in range(1, 21)]
VALID_KEYS = [k.strip() for k in RAW_KEYS if k and len(k.strip()) > 10]

if 'key_manager' not in st.session_state:
    st.session_state.key_manager = {
        i: {"status": "ACTIVE", "in_use": False, "last_finished": datetime.now() - timedelta(seconds=60), "key": k} 
        for i, k in enumerate(VALID_KEYS)
    }
if 'error_logs' not in st.session_state: st.session_state.error_logs = []

manager = st.session_state.key_manager
status_lock = threading.Lock()

# =========================================================
# THẦN CHÚ AI (KÈM BỘ LỌC LỖI CHI TIẾT)
# =========================================================
def call_gemini(api_key, text_data, expected, glossary, model):
    try:
        client = genai.Client(api_key=api_key)
        prompt = f"Translate {expected} SRT blocks to Vietnamese. Style: Wuxia. Glossary: {glossary}. Output ONLY RAW SRT."
        response = client.models.generate_content(model=model, contents=f"{prompt}\n\n{text_data}")
        res = response.text.strip() if response.text else ""
        if res.count("-->") < expected:
            return f"❌ LỖI ĐỊNH DẠNG: AI chỉ trả về {res.count('-->')}/{expected} đoạn. Nội dung rác: {res[:50]}..."
        return res
    except Exception as e:
        # Bắt toàn bộ thông báo lỗi từ Google API
        return f"❌ LỖI HỆ THỐNG: {str(e)}"

# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v70.6")
    file = st.file_uploader("📜 Nạp bí tịch", type=["srt"])
    is_safe_mode = st.checkbox("🐢 SAFE MODE (Cho tài khoản Free)", value=True)
    
    if is_safe_mode:
        n_workers, c_time, b_size = 1, 25, 30
    else:
        n_workers = st.slider("Số luồng xử lý", 1, 10, 5)
        c_time = st.number_input("Giây nghỉ/Key", 5, 60, 15)
        b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)
    
    model_choice = st.selectbox("🔮 Chọn Model", ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-3.1-flash-lite-preview"])
    if st.button("🗑️ XÓA NHẬT KÝ LỖI"):
        st.session_state.error_logs = []
        st.rerun()

# =========================================================
# GIAO DIỆN CHÍNH
# =========================================================
tab1, tab2 = st.tabs(["📝 TỪ ĐIỂN", "⚔️ DỊCH & TRUY VẾT"])

with tab1:
    st.session_state.glossary = st.text_area("Từ điển đối chiếu:", value=st.session_state.get('glossary', ''), height=300)

with tab2:
    if not file:
        st.info("Hãy nạp file ở Sidebar.")
    else:
        p_bar = st.progress(0)
        st.subheader("🕵️ Nhật Ký Truy Vết Lỗi")
        log_container = st.container() # Nơi hiện lỗi
        
        start_btn = st.button("🚀 BẮT ĐẦU DỊCH", type="primary", use_container_width=True)

        # Hiển thị lỗi cũ nếu có
        with log_container:
            for log in st.session_state.error_logs[-5:]: # Hiện 5 lỗi gần nhất
                st.markdown(f"<div class='error-box'>{log}</div>", unsafe_allow_html=True)

# =========================================================
# VẬN HÀNH
# =========================================================
if file and 'start_btn' in locals() and start_btn:
    raw = file.getvalue().decode("utf-8-sig", errors="replace").strip()
    blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
    batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
    results, stats = {}, {"done": 0}
    main_ctx = get_script_run_context()

    def worker_logic(idx):
        add_script_run_context(main_ctx)
        while True:
            cur_k = None
            with status_lock:
                for i, k_data in manager.items():
                    if k_data["status"] == "ACTIVE" and not k_data["in_use"] and (datetime.now() - k_data["last_finished"]).total_seconds() >= c_time:
                        cur_k = i; k_data["in_use"] = True; break
            
            if cur_k is None:
                if not any(k["status"] == "ACTIVE" for k in manager.values()):
                    st.session_state.error_logs.append("‼️ CẢNH BÁO: Tất cả Key đã cạn linh lực!")
                    return
                time.sleep(2); continue

            res = call_gemini(manager[cur_k]["key"], "\n\n".join(batches[idx]), len(batches[idx]), st.session_state.glossary, model_choice)
            
            with status_lock:
                manager[cur_k]["last_finished"] = datetime.now()
                manager[cur_k]["in_use"] = False
                
                if not res.startswith("❌"):
                    results[idx] = res; stats["done"] += 1; return
                else:
                    # Ghi nhận lỗi chi tiết vào kho dữ liệu
                    error_msg = f"[{datetime.now().strftime('%H:%M:%S')}] Lô {idx+1} (Key {cur_k+1}): {res}"
                    st.session_state.error_logs.append(error_msg)
                    if "429" in res or "quota" in res.lower() or "limit" in res.lower():
                        manager[cur_k]["status"] = "DEAD"
                    time.sleep(5)

    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        for i in range(len(batches)): executor.submit(worker_logic, i)
        while stats["done"] < len(batches):
            p_bar.progress(stats["done"] / len(batches))
            # Cập nhật UI lỗi thời gian thực
            time.sleep(1)
            if not any(k["status"] == "ACTIVE" for k in manager.values()): break

    if stats["done"] == len(batches):
        st.success("🎉 Hoàn tất!")
        st.download_button("📥 Tải về", "\n\n".join([results[i] for i in range(len(batches))]), file_name=f"V70_6_{file.name}")
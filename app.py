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

st.set_page_config(page_title="Thiên Quân v70.7 - Hiển Lộ", page_icon="🔱", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    .error-box { 
        padding: 8px; 
        background-color: #3e0b0b; 
        color: #ff9b9b; 
        border: 1px solid #da3633; 
        border-radius: 4px; 
        font-family: monospace;
        font-size: 0.8rem;
        margin-bottom: 4px;
    }
    .log-title { color: #58a6ff; font-weight: bold; margin-bottom: 5px; }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# KHỞI TẠO DỮ LIỆU
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

def call_gemini(api_key, text_data, expected, glossary, model):
    try:
        client = genai.Client(api_key=api_key)
        prompt = f"Translate {expected} SRT blocks to Vietnamese. Style: Wuxia. Glossary: {glossary}. Output ONLY RAW SRT."
        response = client.models.generate_content(model=model, contents=f"{prompt}\n\n{text_data}")
        return response.text.strip() if response.text else "❌ LỖI: AI trả về rỗng."
    except Exception as e:
        return f"❌ LỖI HỆ THỐNG: {str(e)}"

# =========================================================
# GIAO DIỆN
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v70.7")
    file = st.file_uploader("📜 Nạp bí tịch", type=["srt"])
    model_choice = st.selectbox("🔮 Chọn Model", ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-3.1-flash-lite-preview"])
    is_safe_mode = st.checkbox("🐢 SAFE MODE", value=True)
    
    if is_safe_mode: n_workers, c_time, b_size = 1, 30, 30
    else:
        n_workers = st.slider("Số luồng", 1, 10, 5)
        c_time = st.number_input("Giây nghỉ", 5, 60, 15)
        b_size = st.number_input("Đoạn/Lô", 10, 100, 50)

tab1, tab2 = st.tabs(["📝 TỪ ĐIỂN", "⚔️ DỊCH & TRUY VẾT"])

with tab1:
    st.session_state.glossary = st.text_area("Từ điển:", value=st.session_state.get('glossary', ''), height=200)

with tab2:
    if file:
        p_bar = st.progress(0)
        st.markdown("<div class='log-title'>🕵️ Nhật Ký Truy Vết Lỗi (Thời gian thực)</div>", unsafe_allow_html=True)
        log_view = st.empty() # VÙNG HIỂN THỊ LỖI QUAN TRỌNG
        start_btn = st.button("🚀 KHAI TRẬN", type="primary", use_container_width=True)

# =========================================================
# VẬN HÀNH LUỒNG
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
            
            if cur_k is None: time.sleep(1); continue

            res = call_gemini(manager[cur_k]["key"], "\n\n".join(batches[idx]), len(batches[idx]), st.session_state.glossary, model_choice)
            
            with status_lock:
                manager[cur_k]["last_finished"] = datetime.now(); manager[cur_k]["in_use"] = False
                if not res.startswith("❌"):
                    results[idx] = res; stats["done"] += 1; return
                else:
                    error_msg = f"Lô {idx+1} (Key {cur_k+1}): {res}"
                    st.session_state.error_logs.append(error_msg)
                    if "429" in res or "quota" in res.lower(): manager[cur_k]["status"] = "DEAD"
                    time.sleep(10) # Bị lỗi thì nghỉ lâu hơn

    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        for i in range(len(batches)): executor.submit(worker_logic, i)
        
        while stats["done"] < len(batches):
            p_bar.progress(stats["done"] / len(batches))
            
            # ĐƯA LỖI RA MÀN HÌNH NGAY LẬP TỨC
            if st.session_state.error_logs:
                # Lấy 10 lỗi mới nhất để đại hiệp xem
                logs_html = "".join([f"<div class='error-box'>{log}</div>" for log in st.session_state.error_logs[-10:]])
                log_view.markdown(logs_html, unsafe_allow_html=True)
            
            time.sleep(1)
            if not any(k["status"] == "ACTIVE" for k in manager.values()):
                st.error("Tất cả Key đã bị chặn (DEAD). Dừng trận pháp!")
                break

    if stats["done"] == len(batches):
        st.success("Dịch xong!")
        st.download_button("Tải về", "\n\n".join([results[i] for i in range(len(batches))]), file_name=f"v70_7_{file.name}")
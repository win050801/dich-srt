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

# =========================================================
# 🛡️ HÓA GIẢI IMPORT & CONTEXT
# =========================================================
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

st.set_page_config(page_title="Thiên Quân v70.9 - Nhất Kích", page_icon="🔱", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    [data-testid="stSidebar"] { background-color: #161b22 !important; border-right: 1px solid #30363d; }
    .key-box { padding: 8px; border-radius: 6px; text-align: center; border: 1px solid #30363d; font-size: 0.7rem; margin-bottom: 5px; }
    .k-active { background: #238636; color: #fff; }
    .k-busy { background: #1f6feb; color: #fff; }
    .k-dead { background: #da3633; color: #fff; }
    .error-box { padding: 10px; background-color: #491111; color: #ff9b9b; border: 1px solid #da3633; border-radius: 5px; font-family: monospace; font-size: 0.85rem; margin-bottom: 5px; }
    .log-title { color: #f85149; font-weight: bold; margin-bottom: 10px; border-bottom: 1px solid #da3633; padding-bottom: 5px; }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# 🏺 KHỞI TẠO ĐAN ĐIỀN (STATE)
# =========================================================
RAW_KEYS = [os.getenv(f"GEMINI_KEY_{i}") for i in range(1, 21)]
VALID_KEYS = [k.strip() for k in RAW_KEYS if k and len(k.strip()) > 10]

if 'key_manager' not in st.session_state:
    st.session_state.key_manager = {
        i: {"status": "ACTIVE", "in_use": False, "last_finished": datetime.now() - timedelta(seconds=60), "key": k} 
        for i, k in enumerate(VALID_KEYS)
    }
if 'error_logs' not in st.session_state: st.session_state.error_logs = []
if 'results' not in st.session_state: st.session_state.results = {}
if 'glossary' not in st.session_state: st.session_state.glossary = ""
if 'stop_signal' not in st.session_state: st.session_state.stop_signal = False

manager = st.session_state.key_manager
status_lock = threading.Lock()
result_lock = threading.Lock()

# =========================================================
# ⚔️ CHIÊU THỨC AI
# =========================================================
def call_gemini_scan(api_key, text_data, model):
    try:
        client = genai.Client(api_key=api_key)
        prompt = "Analyze this Chinese SRT. Extract main character names. Format: 'Gốc: Dịch'. No explanation."
        response = client.models.generate_content(model=model, contents=f"{prompt}\n\n{text_data[:40000]}")
        return response.text.strip() if response.text else ""
    except Exception as e: return f"Lỗi quét: {str(e)}"

def call_gemini_translate(api_key, text_data, expected, glossary, model):
    try:
        client = genai.Client(api_key=api_key)
        sys_prompt = f"Dịch {expected} đoạn SRT sang tiếng Việt Kiếm Hiệp. Từ điển: {glossary}. Chỉ trả về nội dung SRT thô."
        response = client.models.generate_content(model=model, contents=f"{sys_prompt}\n\n{text_data}")
        res = response.text.strip() if response.text else ""
        if res.count("-->") < expected:
            return f"❌ LỖI ĐỊNH DẠNG: AI trả về {res.count('-->')}/{expected} đoạn. Không chấp nhận."
        return res
    except Exception as e: return f"❌ LỖI HỆ THỐNG: {str(e)}"

# =========================================================
# 🏯 GIAO DIỆN
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v70.9")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    st.divider()
    model_choice = st.selectbox("🔮 Model", ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-3.1-flash-lite-preview"])
    b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)
    c_time = st.number_input("Giây nghỉ/Key", 5, 60, 15)
    n_workers = st.slider("Số luồng xử lý", 1, 10, 5)
    if st.button("🗑️ DỌN DẸP DỮ LIỆU CŨ"): 
        st.session_state.results = {}; st.session_state.error_logs = []; st.session_state.stop_signal = False
        st.rerun()

tab1, tab2 = st.tabs(["📝 LINH NHÃN (TỪ ĐIỂN)", "⚔️ KHAI TRẬN"])

with tab1:
    if file:
        if st.button("🔍 QUÉT TÊN NHÂN VẬT", type="primary"):
            active_key = next((v["key"] for v in manager.values() if v["status"] == "ACTIVE"), VALID_KEYS[0])
            with st.spinner("Đang soi xét..."):
                st.session_state.glossary = call_gemini_scan(active_key, file.getvalue().decode("utf-8-sig", errors="replace"), model_choice)
            st.rerun()
    st.session_state.glossary = st.text_area("Từ điển đối chiếu:", value=st.session_state.glossary, height=350)

with tab2:
    if not file: st.info("Hãy nạp bí tịch ở Sidebar.")
    else:
        col_k, col_w = st.columns([1, 2.5])
        k_places = [col_k.empty() for _ in range(len(VALID_KEYS))]
        w_places = [col_w.empty() for _ in range(n_workers)]
        st.divider()
        p_bar = st.progress(0)
        log_view = st.empty()
        start_btn = st.button("🚀 BẮT ĐẦU KHAI TRẬN (Chỉ 1 lần - Lỗi dừng luôn)", type="primary", use_container_width=True)

# =========================================================
# 🌊 LÕI VẬN HÀNH (NHẤT KÍCH TẤT SÁT)
# =========================================================
if file and 'start_btn' in locals() and start_btn:
    st.session_state.stop_signal = False
    raw = file.getvalue().decode("utf-8-sig", errors="replace").strip()
    blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
    batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
    total = len(batches)
    st.session_state.results = {}
    stats = {"done": 0}
    worker_map = {i: {"msg": "Sẵn sàng", "style": ""} for i in range(n_workers)}
    main_ctx = get_script_run_context()

    def worker_logic(idx, worker_id):
        add_script_run_context(main_ctx)
        # 1. Kiểm tra xem trận pháp có lệnh dừng chưa
        if st.session_state.stop_signal: return

        # 2. Tìm Key khả dụng
        cur_k = None
        while cur_k is None and not st.session_state.stop_signal:
            with status_lock:
                for i, k_data in manager.items():
                    if k_data["status"] == "ACTIVE" and not k_data["in_use"] and (datetime.now() - k_data["last_finished"]).total_seconds() >= c_time:
                        cur_k = i; k_data["in_use"] = True; break
            if cur_k is None: time.sleep(1)

        if cur_k is not None:
            worker_map[worker_id] = {"msg": f"Lô {idx+1}: Đang dịch...", "style": "color:#58a6ff;"}
            res = call_gemini_translate(manager[cur_k]["key"], "\n\n".join(batches[idx]), len(batches[idx]), st.session_state.glossary, model_choice)
            
            with status_lock:
                manager[cur_k]["last_finished"] = datetime.now(); manager[cur_k]["in_use"] = False
                
                if not res.startswith("❌"):
                    # THÀNH CÔNG
                    with result_lock: st.session_state.results[idx] = res
                    stats["done"] += 1
                    worker_map[worker_id] = {"msg": f"Lô {idx+1}: ✅ Xong", "style": "color:#3fb950;"}
                else:
                    # THẤT BẠI - DỪNG LUÔN, KHÔNG THỬ LẠI
                    st.session_state.stop_signal = True # PHÁT LỆNH DỪNG TOÀN TRẬN
                    error_msg = f"‼️ THẤT BẠI TẠI LÔ {idx+1}: {res}"
                    st.session_state.error_logs.append(error_msg)
                    worker_map[worker_id] = {"msg": f"Lô {idx+1}: ❌ LỖI", "style": "color:#f85149; font-weight:bold;"}

    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        for i in range(total): executor.submit(worker_logic, i, i % n_workers)
        
        while stats["done"] < total and not st.session_state.stop_signal:
            for i, k in manager.items():
                cls = "k-dead" if k["status"] == "DEAD" else ("k-active" if not k["in_use"] else "k-busy")
                k_places[i].markdown(f"<div class='key-box {cls}'>Key {i+1}</div>", unsafe_allow_html=True)
            for i in range(n_workers):
                info = worker_map[i]
                w_places[i].markdown(f"<div style='font-size:0.8rem; padding:5px; border:1px solid #30363d; margin-bottom:2px; {info['style']}'><b>Worker {i+1}</b>: {info['msg']}</div>", unsafe_allow_html=True)
            if st.session_state.error_logs:
                log_view.markdown("<div class='log-title'>💀 TRẬN PHÁP BỊ ĐỨT ĐOẠN - PHÁT HIỆN LỖI:</div>" + "".join([f"<div class='error-box'>{log}</div>" for log in st.session_state.error_logs]), unsafe_allow_html=True)
            p_bar.progress(stats["done"] / total)
            time.sleep(1)

    if st.session_state.stop_signal:
        st.error("🛑 Trận pháp đã dừng do gặp lỗi. Đại hiệp hãy kiểm tra Nhật ký truy vết bên dưới.")
    elif stats["done"] == total:
        st.success("🎉 Xuất sắc! Toàn bộ bí tịch đã được dịch mà không vấp một lỗi nào.")
        st.download_button("📥 TẢI BẢN DỊCH", "\n\n".join([st.session_state.results[i] for i in range(total)]), file_name=f"V70_9_{file.name}", use_container_width=True)
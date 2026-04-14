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
# GIAO DIỆN CHUẨN
# =========================================================
st.set_page_config(page_title="Thiên Quân v71.5 - Khai Thông", page_icon="🔱", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    .key-box { padding: 12px; border-radius: 8px; text-align: center; font-size: 0.85rem; margin-bottom: 8px; color: white; }
    .k-active { background-color: #238636; border: 1px solid #2ea043; } 
    .k-busy { background-color: #1f6feb; border: 1px solid #388bfd; }   
    .k-dead { background-color: #da3633; border: 1px solid #f85149; }   
    .w-box { padding: 10px; background: #161b22; border-left: 4px solid #58a6ff; margin-bottom: 5px; font-size: 0.85rem; border-radius: 4px; }
    div.stButton > button { background-color: #ff4b4b !important; color: white !important; font-weight: bold !important; border-radius: 10px !important; }
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

# Các biến điều khiển luồng
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
    st.title("🔱 THIÊN QUÂN v71.5")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    model_choice = st.selectbox("🔮 Model", ["gemini-3.1-flash-lite-preview", "gemini-3-flash-preview", "gemini-2.0-flash", "gemini-1.5-flash"])
    st.divider()
    n_workers = st.slider("Số luồng xử lý", 1, 10, 5)
    c_time = st.number_input("Giây nghỉ/Key", 5, 60, 15)
    b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)
    
    # NÚT KHẨN CẤP ĐỂ RESET KEY NẾU BỊ TREO
    if st.button("♻️ KHAI THÔNG KEY (Reset State)"):
        for i in st.session_state.key_manager:
            st.session_state.key_manager[i]["in_use"] = False
            st.session_state.key_manager[i]["status"] = "ACTIVE"
        st.session_state.stop_signal = False
        st.success("Đã hồi phục trạng thái Key!")
        st.rerun()

# =========================================================
# GIAO DIỆN CHÍNH
# =========================================================
tab1, tab2 = st.tabs(["📝 LINH NHÃN (TỪ ĐIỂN)", "⚔️ KHAI TRẬN"])

with tab1:
    if file and st.button("🔍 QUÉT TÊN NHÂN VẬT"):
        key = next((v["key"] for v in st.session_state.key_manager.values() if v["status"] == "ACTIVE"), VALID_KEYS[0])
        with st.spinner("Đang quét..."):
            st.session_state.glossary = call_gemini_api(key, "Extract glossary: 'Original: Vietnamese'. No explanation.", file.getvalue().decode("utf-8-sig")[:30000], model_choice)
        st.rerun()
    st.session_state.glossary = st.text_area("Từ điển:", value=st.session_state.glossary, height=200)

with tab2:
    if not file:
        st.info("💡 Hãy nạp file ở Sidebar.")
    else:
        col_k, col_w = st.columns([1, 2.5])
        k_places = [col_k.empty() for _ in range(len(VALID_KEYS))]
        w_places = [col_w.empty() for _ in range(n_workers)]
        st.divider()
        p_bar = st.progress(0)
        start_btn = st.button("🚀 BẮT ĐẦU (LỖI LÀ DỪNG LUÔN)", use_container_width=True)

# =========================================================
# VẬN HÀNH LUỒNG (CẢI TIẾN TRÁNH TREO)
# =========================================================
if file and 'start_btn' in locals() and start_btn:
    st.session_state.stop_signal = False
    st.session_state.results = {}
    blocks = [b.strip() for b in re.split(r'\n\s*\n', file.getvalue().decode("utf-8-sig").strip()) if b.strip()]
    batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
    total = len(batches)
    
    main_ctx = get_script_run_context()
    stats = {"done": 0}
    worker_map = {i: {"msg": "Đang chờ..."} for i in range(n_workers)}
    
    # Lấy reference manager để tránh gọi st.session_state quá nhiều trong thread
    manager_ref = st.session_state.key_manager

    def worker_logic(idx, worker_id, glossary):
        add_script_run_context(main_ctx)
        if st.session_state.stop_signal: return
        
        cur_k = None
        # Vòng lặp tìm Key với thông báo trạng thái
        while cur_k is None and not st.session_state.stop_signal:
            with status_lock:
                for i, k in manager_ref.items():
                    if k["status"] == "ACTIVE" and not k["in_use"] and (datetime.now() - k["last_finished"]).total_seconds() >= c_time:
                        cur_k = i; k["in_use"] = True; break
            if cur_k is None:
                worker_map[worker_id]["msg"] = "🧘 Đang đợi Key sẵn sàng..."
                time.sleep(2)

        if cur_k is not None:
            worker_map[worker_id]["msg"] = f"⏳ Lô {idx+1}: Đang kết nối AI..."
            p = f"Translate {len(batches[idx])} SRT blocks to Wuxia style. Glossary: {glossary}. Raw SRT only."
            res = call_gemini_api(manager_ref[cur_k]["key"], p, "\n\n".join(batches[idx]), model_choice)
            
            with status_lock:
                manager_ref[cur_k]["last_finished"] = datetime.now()
                manager_ref[cur_k]["in_use"] = False
                if "❌" in res:
                    st.session_state.stop_signal = True; st.error(f"Lô {idx+1} lỗi: {res}")
                else:
                    with result_lock: st.session_state.results[idx] = res
                    stats["done"] += 1; worker_map[worker_id]["msg"] = f"✅ Lô {idx+1}: Hoàn tất"

    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        for i in range(total):
            executor.submit(worker_logic, i, i % n_workers, st.session_state.glossary)
        
        while stats["done"] < total and not st.session_state.stop_signal:
            for i, k in manager_ref.items():
                cls = "k-dead" if k["status"] == "DEAD" else ("k-active" if not k["in_use"] else "k-busy")
                k_places[i].markdown(f"<div class='key-box {cls}'>Key {i+1}</div>", unsafe_allow_html=True)
            for i in range(n_workers):
                w_places[i].markdown(f"<div class='w-box'><b>Luồng {i+1}:</b> {worker_map[i]['msg']}</div>", unsafe_allow_html=True)
            p_bar.progress(stats["done"] / total)
            time.sleep(1)

    if stats["done"] == total:
        st.success("🎉 Đã hoàn thành!")
        final_srt = "\n\n".join([st.session_state.results[i] for i in range(total)])
        st.download_button("📥 TẢI BẢN DỊCH", final_srt, file_name=f"V71_5_{file.name}", use_container_width=True)
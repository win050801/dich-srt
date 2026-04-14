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
# 🛡️ HÓA GIẢI CONTEXT (PHÁP BẢO TRUYỀN TIN)
# =========================================================
def get_context_helpers():
    try:
        from streamlit.runtime.scriptrunner import add_script_run_context, get_script_run_context
        return add_script_run_context, get_script_run_context
    except:
        return (lambda x: None), (lambda: None)

add_script_run_context, get_script_run_context = get_context_helpers()

try: from dotenv import load_dotenv; load_dotenv()
except: pass

# =========================================================
# GIAO DIỆN PHONG THÁI HUYỀN VŨ
# =========================================================
st.set_page_config(page_title="Thiên Quân v71.6 - Đại Thông", page_icon="🔱", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    .key-box { padding: 12px; border-radius: 8px; text-align: center; font-size: 0.85rem; margin-bottom: 8px; color: white; font-weight: bold; }
    .k-active { background-color: #238636; border: 1px solid #2ea043; } 
    .k-busy { background-color: #1f6feb; border: 1px solid #388bfd; }   
    .k-dead { background-color: #da3633; border: 1px solid #f85149; }   
    .w-box { padding: 10px; background: #161b22; border-left: 4px solid #58a6ff; margin-bottom: 5px; font-size: 0.85rem; border-radius: 4px; }
    div.stButton > button { background-color: #ff4b4b !important; color: white !important; font-weight: bold !important; border-radius: 10px !important; width: 100%; height: 50px; }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# QUẢN LÝ LINH LỰC (API KEYS)
# =========================================================
if 'api_keys_pool' not in st.session_state:
    RAW_KEYS = [os.getenv(f"GEMINI_KEY_{i}") for i in range(1, 21)]
    VALID_KEYS = [k.strip() for k in RAW_KEYS if k and len(k.strip()) > 10]
    st.session_state.api_keys_pool = {
        i: {"key": k, "status": "ACTIVE", "in_use": False, "last_finished": datetime.now() - timedelta(seconds=60)}
        for i, k in enumerate(VALID_KEYS)
    }

if 'results' not in st.session_state: st.session_state.results = {}
if 'glossary' not in st.session_state: st.session_state.glossary = ""
if 'stop_signal' not in st.session_state: st.session_state.stop_signal = False

# Khóa vạn năng để đồng bộ luồng
status_lock = threading.Lock()
result_lock = threading.Lock()

def call_gemini_api(api_key, prompt, content, model):
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=model, contents=f"{prompt}\n\n{content}")
        return response.text.strip() if response.text else "ERR_EMPTY"
    except Exception as e: return f"❌ LỖI: {str(e)}"

# =========================================================
# SIDEBAR & CÀI ĐẶT
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v71.6")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    model_choice = st.selectbox("🔮 Model", ["gemini-3.1-flash-lite-preview", "gemini-3-flash-preview", "gemini-2.0-flash"])
    st.divider()
    n_workers = st.slider("Số luồng xử lý", 1, 10, 5)
    c_time = st.number_input("Giây nghỉ/Key", 5, 60, 15)
    b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)
    
    if st.button("♻️ RESET TRẠNG THÁI KEY"):
        for i in st.session_state.api_keys_pool:
            st.session_state.api_keys_pool[i]["in_use"] = False
            st.session_state.api_keys_pool[i]["status"] = "ACTIVE"
        st.session_state.stop_signal = False
        st.session_state.results = {}
        st.rerun()

# =========================================================
# GIAO DIỆN CHÍNH
# =========================================================
tab1, tab2 = st.tabs(["📝 LINH NHÃN", "⚔️ KHAI TRẬN"])

with tab1:
    if file and st.button("🔍 QUÉT TÊN NHÂN VẬT"):
        active_keys = [v["key"] for v in st.session_state.api_keys_pool.values() if v["status"] == "ACTIVE"]
        if active_keys:
            with st.spinner("Đang quét..."):
                p = "Extract glossary: 'Original: Vietnamese'. No explanation."
                st.session_state.glossary = call_gemini_api(active_keys[0], p, file.getvalue().decode("utf-8-sig")[:30000], model_choice)
            st.rerun()
    st.session_state.glossary = st.text_area("Từ điển:", value=st.session_state.glossary, height=200)

with tab2:
    if not file:
        st.info("💡 Hãy nạp bí tịch ở Sidebar.")
    else:
        col_k, col_w = st.columns([1, 2.5])
        k_places = [col_k.empty() for _ in range(len(st.session_state.api_keys_pool))]
        w_places = [col_w.empty() for _ in range(n_workers)]
        st.divider()
        p_bar = st.progress(0)
        start_btn = st.button("🚀 BẮT ĐẦU (NHẤT KÍCH TẤT SÁT)", use_container_width=True)

# =========================================================
# 🌊 LÕI VẬN HÀNH (ĐẠI THÔNG HUYỀN CƠ)
# =========================================================
if file and 'start_btn' in locals() and start_btn:
    st.session_state.stop_signal = False
    st.session_state.results = {}
    content = file.getvalue().decode("utf-8-sig", errors="replace").strip()
    blocks = [b.strip() for b in re.split(r'\n\s*\n', content) if b.strip()]
    batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
    total_batches = len(batches)
    
    # Chuẩn bị luồng
    main_ctx = get_script_run_context()
    worker_status = {i: "Sẵn sàng" for i in range(n_workers)}
    completed_count = [0] # Dùng list để pass by reference vào thread

    def worker_thread(batch_idx, worker_id, glossary):
        add_script_run_context(main_ctx)
        if st.session_state.stop_signal: return

        target_key_idx = -1
        # Vòng lặp "Săn Key" - Đảm bảo không bị treo
        while not st.session_state.stop_signal and target_key_idx == -1:
            with status_lock:
                for i, k_info in st.session_state.api_keys_pool.items():
                    cooldown_done = (datetime.now() - k_info["last_finished"]).total_seconds() >= c_time
                    if k_info["status"] == "ACTIVE" and not k_info["in_use"] and cooldown_done:
                        k_info["in_use"] = True
                        target_key_idx = i
                        break
            if target_key_idx == -1:
                worker_status[worker_id] = f"🧘 Đợi Key rảnh (Lô {batch_idx+1})..."
                time.sleep(1.5)

        if target_key_idx != -1:
            worker_status[worker_id] = f"⏳ Đang dịch Lô {batch_idx+1}..."
            prompt = f"Translate {len(batches[batch_idx])} SRT blocks. Glossary: {glossary}. Classical Vietnamese style."
            res = call_gemini_api(st.session_state.api_keys_pool[target_key_idx]["key"], prompt, "\n\n".join(batches[batch_idx]), model_choice)
            
            with status_lock:
                st.session_state.api_keys_pool[target_key_idx]["in_use"] = False
                st.session_state.api_keys_pool[target_key_idx]["last_finished"] = datetime.now()
                
                if "❌" in res:
                    st.session_state.stop_signal = True
                    worker_status[worker_id] = f"❌ Lỗi Lô {batch_idx+1}"
                else:
                    with result_lock:
                        st.session_state.results[batch_idx] = res
                    completed_count[0] += 1
                    worker_status[worker_id] = f"✅ Xong Lô {batch_idx+1}"

    # Thực thi đa luồng
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        for i in range(total_batches):
            executor.submit(worker_thread, i, i % n_workers, st.session_state.glossary)
        
        # Vòng lặp cập nhật UI chính
        while completed_count[0] < total_batches and not st.session_state.stop_signal:
            # Vẽ lại Key
            for i, k_info in st.session_state.api_keys_pool.items():
                cls = "k-dead" if k_info["status"] == "DEAD" else ("k-active" if not k_info["in_use"] else "k-busy")
                k_places[i].markdown(f"<div class='key-box {cls}'>Key {i+1}</div>", unsafe_allow_html=True)
            
            # Vẽ lại Worker
            for i in range(n_workers):
                w_places[i].markdown(f"<div class='w-box'><b>Luồng {i+1}:</b> {worker_status[i]}</div>", unsafe_allow_html=True)
            
            p_bar.progress(completed_count[0] / total_batches)
            time.sleep(1)
            if all(k["status"] == "DEAD" for k in st.session_state.api_keys_pool.values()): break

    if completed_count[0] == total_batches:
        st.success("🎉 Bí tịch v71.6 đã hoàn thành!")
        final_srt = "\n\n".join([st.session_state.results[i] for i in range(total_batches)])
        st.download_button("📥 TẢI BẢN DỊCH", final_srt, file_name=f"V71_6_{file.name}", use_container_width=True)
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
from queue import Queue

# --- KHỞI TẠO CẤU HÌNH ---
st.set_page_config(page_title="Donghua v75.6 - Fix Key Leak", page_icon="🔱", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    [data-testid="stSidebar"] { background-color: #161b22 !important; border-right: 1px solid #30363d; }
    .key-box { padding: 8px; border-radius: 6px; text-align: center; border: 1px solid #30363d; font-size: 0.75rem; margin-bottom: 5px; min-height: 55px; }
    .k-active { background: #238636; color: #aff5b4; }
    .k-busy { background: #1f6feb; color: #c2e0ff; }
    .k-cool { background: #9e6a03; color: #ffdf5d; }
    .k-dead { background: #da3633; color: #ffd1d1; }
    .w-box { padding: 10px; border-radius: 4px; border: 1px solid #30363d; font-size: 0.8rem; margin-bottom: 5px; background: #010409; }
    .w-run { border-left: 4px solid #58a6ff; color: #58a6ff; }
    .w-done { border-left: 4px solid #3fb950; color: #3fb950; }
    .w-retry { border-left: 4px solid #d29922; color: #d29922; }
    h4 { color: #58a6ff !important; margin-top: 10px; }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# QUẢN LÝ TÀI NGUYÊN
# =========================================================
RAW_KEYS = [os.getenv(f"GEMINI_KEY_{i}") for i in range(1, 21)]
VALID_KEYS = [k.strip() for k in RAW_KEYS if k and len(k.strip()) > 10]

if 'key_manager' not in st.session_state:
    st.session_state.key_manager = {
        i: {"status": "ACTIVE", "in_use": False, "last_finished": datetime.now() - timedelta(seconds=60), "key": k, "batch_info": ""} 
        for i, k in enumerate(VALID_KEYS)
    }
if 'glossary' not in st.session_state: st.session_state.glossary = ""
if 'final_results' not in st.session_state: st.session_state.final_results = None

manager = st.session_state.key_manager
status_lock = threading.Lock()
worker_status_lock = threading.Lock()

# =========================================================
# PHÁP THUẬT XỬ LÝ (MODEL 3)
# =========================================================

def call_gemini_translate(api_key, text_data, expected_count, glossary, model_name):
    try:
        client = genai.Client(api_key=api_key)
        sys_prompt = f"""Dịch {expected_count} đoạn SRT sang tiếng Việt Tiên Hiệp.
THUẬT NGỮ: {glossary}
YÊU CẦU: Trả về đúng định dạng SRT, khớp miệng, đủ {expected_count} đoạn."""
        
        response = client.models.generate_content(
            model=model_name, 
            contents=f"{sys_prompt}\n\nNỘI DUNG:\n{text_data}",
            config=types.GenerateContentConfig(temperature=0.3)
        )
        res = response.text.strip() if response.text else ""
        if "-->" not in res: return f"ERR_FORMAT: AI không trả về SRT"
        return res
    except Exception as e:
        return f"ERR_API: {str(e)}"

# =========================================================
# GIAO DIỆN
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v75.6")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    model_choice = st.selectbox("🔮 Model 3", ["gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-3.1-flash-lite-preview"], index=0)
    b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)
    c_time = st.number_input("Giây nghỉ/Key", 5, 60, 15)
    n_workers = st.slider("Số luồng xử lý", 1, 10, 4)

    if st.button("♻️ RESET & GIẢI KẸT KEY"):
        st.session_state.final_results = None
        for i in manager:
            manager[i]["status"] = "ACTIVE"
            manager[i]["in_use"] = False
        st.rerun()

tab1, tab2 = st.tabs(["📝 TỪ ĐIỂN", "⚔️ KHAI TRẬN"])

with tab1:
    st.session_state.glossary = st.text_area("Thuật ngữ:", value=st.session_state.glossary, height=400)

with tab2:
    if not file:
        st.info("💡 Hãy nạp file SRT.")
    elif st.session_state.final_results is None:
        col_k, col_w = st.columns([1, 2.5])
        with col_k:
            st.markdown("#### 📡 Key")
            k_places = [st.empty() for _ in range(len(VALID_KEYS))]
        with col_w:
            st.markdown("#### 🌊 Luồng")
            w_places = [st.empty() for _ in range(n_workers)]
            st.divider()
            p_bar = st.progress(0); p_text = st.empty()
            start_btn = st.button("⚔️ KHAI TRẬN DỊCH FULL", use_container_width=True, type="primary")

        def update_ui(worker_map):
            now = datetime.now()
            for i, k in manager.items():
                diff = (now - k["last_finished"]).total_seconds()
                if k["status"] == "DEAD": cls, txt = "k-dead", "💀 HỎNG"
                elif k["in_use"]: cls, txt = "k-busy", f"⚔️ {k['batch_info']}"
                elif diff < c_time: cls, txt = "k-cool", f"🧘 {int(c_time-diff)}s"
                else: cls, txt = "k-active", "✅ SẴN SÀNG"
                k_places[i].markdown(f"<div class='key-box {cls}'><b>#{i+1}</b><br>{txt}</div>", unsafe_allow_html=True)
            for i in range(n_workers):
                info = worker_map.get(i, {"msg": "Đang chờ...", "style": "w-idle"})
                w_places[i].markdown(f"<div class='w-box {info['style']}'><b>L {i+1}</b>: {info['msg']}</div>", unsafe_allow_html=True)

        if start_btn:
            from streamlit.runtime.scriptrunner import add_script_run_context, get_script_run_context
            main_ctx = get_script_run_context()
            
            raw = file.getvalue().decode("utf-8-sig", errors="replace").strip()
            blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
            batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
            
            results = {}; stats = {"done": 0, "total": len(batches)}
            worker_map = {i: {"msg": "Sẵn sàng", "style": "w-idle"} for i in range(n_workers)}
            task_queue = Queue()
            for i, b in enumerate(batches): task_queue.put((i, b))

            def worker_thread(worker_id):
                add_script_run_context(main_ctx)
                while not task_queue.empty():
                    batch_idx, chunk_blocks = task_queue.get()
                    expected = len(chunk_blocks)
                    chunk_text = "\n\n".join(chunk_blocks)
                    success = False
                    
                    while not success:
                        cur_k = None
                        with status_lock:
                            for idx, k in manager.items():
                                if k["status"] == "ACTIVE" and not k["in_use"] and (datetime.now() - k["last_finished"]).total_seconds() >= c_time:
                                    cur_k = idx; k["in_use"] = True; k["batch_info"] = f"Lô {batch_idx+1}"; break
                        
                        if cur_k is None:
                            if not any(k["status"] == "ACTIVE" for k in manager.values()):
                                with worker_status_lock: worker_map[worker_id] = {"msg": "CẠN KEY!", "style": "w-retry"}
                                task_queue.put((batch_idx, chunk_blocks))
                                return
                            with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Chờ Key...", "style": "w-retry"}
                            time.sleep(2); continue

                        try:
                            with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Dịch...", "style": "w-run"}
                            res = call_gemini_translate(manager[cur_k]["key"], chunk_text, expected, st.session_state.glossary, model_choice)
                            
                            if "ERR" not in res and res.count("-->") >= expected:
                                results[batch_idx] = res
                                with status_lock: stats["done"] += 1
                                with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Xong", "style": "w-done"}
                                success = True
                            else:
                                # Nếu lỗi rõ ràng là do Key
                                if any(x in res.upper() for x in ["401", "429", "INVALID", "QUOTA", "PERMISSION"]):
                                    with status_lock: manager[cur_k]["status"] = "DEAD"
                                time.sleep(1)
                                # Thất bại thì quay lại vòng lặp while not success để tìm key khác
                        finally:
                            with status_lock:
                                manager[cur_k]["in_use"] = False
                                manager[cur_k]["last_finished"] = datetime.now()
                                manager[cur_k]["batch_info"] = ""
                    
                    task_queue.task_done()

            with ThreadPoolExecutor(max_workers=n_workers) as executor:
                for i in range(n_workers): executor.submit(worker_thread, i)
                while stats["done"] < stats["total"]:
                    update_ui(worker_map)
                    p_bar.progress(stats["done"] / stats["total"])
                    p_text.info(f"Tiến độ: {stats['done']}/{stats['total']} lô")
                    if not any(k["status"] == "ACTIVE" for k in manager.values()): break
                    time.sleep(1)

            if stats["done"] == stats["total"]:
                st.session_state.final_results = "\n\n".join([results[i] for i in sorted(results.keys())])
                st.rerun()

# =========================================================
# TẢI XUỐNG
# =========================================================
if st.session_state.final_results:
    st.success("🎉 Hoàn thành!")
    st.download_button("📥 TẢI BẢN FULL", st.session_state.final_results, f"DICH_FULL_{file.name}", use_container_width=True, type="primary")

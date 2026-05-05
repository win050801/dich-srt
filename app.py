import sys
import os
import streamlit as st
from google import genai
from google.genai import types
import time
import re
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED

# --- HÓA GIẢI XUNG ĐỘT PHIÊN BẢN ---
try:
    from streamlit.runtime.scriptrunner import add_script_run_context, get_script_run_context
except ImportError:
    try:
        from streamlit.scriptrunner import add_script_run_context, get_script_run_context
    except ImportError:
        def add_script_run_context(*args, **kwargs): pass
        def get_script_run_context(*args, **kwargs): return None

# --- CẤU HÌNH GIAO DIỆN ---
st.set_page_config(page_title="Donghua v76.0 - Trảm Treo", page_icon="🔱", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    [data-testid="stSidebar"] { background-color: #161b22 !important; border-right: 1px solid #30363d; }
    .key-box { padding: 8px; border-radius: 6px; text-align: center; border: 1px solid #30363d; font-size: 0.75rem; margin-bottom: 5px; min-height: 60px; }
    .k-active { background: #1a4d2e; color: #aff5b4; border: 1px solid #2ea043; }
    .k-busy { background: #05445e; color: #c2e0ff; border: 1px solid #189ab4; }
    .k-dead { background: #4d1a1a; color: #ffd1d1; border: 1px solid #f85149; }
    .console-box { background: #000; color: #0f0; font-family: 'Courier New', monospace; padding: 10px; border-radius: 5px; border: 1px solid #333; height: 250px; overflow-y: auto; font-size: 0.85rem; line-height: 1.4; }
    .w-box { padding: 10px; border-radius: 4px; border: 1px solid #30363d; font-size: 0.8rem; margin-bottom: 5px; background: #010409; }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# QUẢN LÝ TÀI NGUYÊN
# =========================================================
RAW_KEYS = [os.getenv(f"GEMINI_KEY_{i}") for i in range(1, 21)]
VALID_KEYS = [k.strip() for k in RAW_KEYS if k and len(k.strip()) > 10]

if 'key_manager' not in st.session_state:
    st.session_state.key_manager = {
        i: {"status": "ACTIVE", "in_use": False, "last_finished": datetime.now() - timedelta(seconds=60), "key": k, "job": ""} 
        for i, k in enumerate(VALID_KEYS)
    }
if 'glossary' not in st.session_state: st.session_state.glossary = ""
if 'final_results' not in st.session_state: st.session_state.final_results = None
if 'logs' not in st.session_state: st.session_state.logs = []

manager = st.session_state.key_manager
log_lock = threading.Lock()
status_lock = threading.Lock()

def add_log(msg):
    with log_lock:
        t = datetime.now().strftime("%H:%M:%S")
        st.session_state.logs.append(f"[{t}] {msg}")
        if len(st.session_state.logs) > 50: st.session_state.logs.pop(0)

# =========================================================
# HÀM GỌI API (CỐ ĐỊNH MODEL 3)
# =========================================================
def call_api(api_key, model_name, prompt, content):
    """Hàm gọi API cơ bản, bọc try-except để bắt lỗi"""
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name, 
            contents=f"{prompt}\n\n{content}",
            config=types.GenerateContentConfig(temperature=0.3)
        )
        return response.text.strip() if response.text else "ERR_EMPTY"
    except Exception as e:
        return f"ERR_API: {str(e)}"

# =========================================================
# GIAO DIỆN
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v76.0")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    model_choice = st.selectbox("🔮 Model 3", ["gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-3.1-flash-lite-preview"], index=0)
    b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)
    c_time = st.number_input("Giây nghỉ/Key", 5, 60, 15)
    n_workers = st.slider("Số luồng", 1, 10, 4)

    if st.button("♻️ RESET HỆ THỐNG"):
        st.session_state.final_results = None
        st.session_state.logs = []
        for i in manager:
            manager[i]["status"] = "ACTIVE"
            manager[i]["in_use"] = False
            manager[i]["job"] = ""
        st.rerun()

tab1, tab2 = st.tabs(["📝 TỪ ĐIỂN", "⚔️ KHAI TRẬN"])

with tab1:
    st.session_state.glossary = st.text_area("Thuật ngữ:", value=st.session_state.glossary, height=300)

with tab2:
    col_k, col_w = st.columns([1, 2.5])
    with col_k:
        st.markdown("#### 📡 Key")
        k_places = [st.empty() for _ in range(len(VALID_KEYS))]
    with col_w:
        st.markdown("#### 🌊 Luồng")
        w_places = [st.empty() for _ in range(n_workers)]
        st.divider()
        p_bar = st.progress(0); p_text = st.empty()
        
        st.markdown("#### 📜 Thần Thức Nhật Ký")
        console_placeholder = st.empty()
        
        start_btn = st.button("⚔️ KHAI TRẬN (THANH LỌC & DỊCH)", use_container_width=True, type="primary")

    def refresh_ui(worker_map=None):
        # Cập nhật Key
        for i, k in manager.items():
            if k["status"] == "DEAD": cls, txt = "k-dead", "💀 HỎNG"
            elif k["in_use"]: cls, txt = "k-busy", f"⚔️ {k['job']}"
            else: cls, txt = "k-active", "✅ SẴN"
            k_places[i].markdown(f"<div class='key-box {cls}'><b>#{i+1}</b><br>{txt}</div>", unsafe_allow_html=True)
        # Cập nhật Luồng
        if worker_map:
            for i in range(n_workers):
                info = worker_map.get(i, {"msg": "Chờ...", "style": ""})
                w_places[i].markdown(f"<div class='w-box'><b>L {i+1}</b>: {info['msg']}</div>", unsafe_allow_html=True)
        # Cập nhật Console
        log_html = "".join([f"<div>{l}</div>" for l in st.session_state.logs[::-1]])
        console_placeholder.markdown(f"<div class='console-box'>{log_html}</div>", unsafe_allow_html=True)

    if start_btn and file:
        main_ctx = get_script_run_context()
        add_log("--- KHỞI CHẠY ĐẠI TRẬN v76.0 ---")
        refresh_ui()

        # --- BƯỚC 1: THANH LỌC (KHÔNG DÙNG MAP ĐỂ TRÁNH TREO) ---
        add_log("Bắt đầu thanh lọc Linh thạch...")
        def health_task(idx):
            add_script_run_context(main_ctx)
            res = call_api(manager[idx]["key"], model_choice, "ping", "hi")
            if "ERR_API" in res and any(x in res.upper() for x in ["401", "INVALID", "EXPIRED", "PERMISSION"]):
                with status_lock: manager[idx]["status"] = "DEAD"
                return f"Key #{idx+1} HỎNG"
            return f"Key #{idx+1} OK"

        with ThreadPoolExecutor(max_workers=5) as check_exec:
            futures = [check_exec.submit(health_task, i) for i in manager if manager[i]["status"] == "ACTIVE"]
            # Đợi tối đa 20 giây cho toàn bộ khâu check key
            wait(futures, timeout=20)
            for f in futures:
                if f.done(): add_log(f.result())
        
        refresh_ui()

        # --- BƯỚC 2: PHÂN TÁCH & DỊCH ---
        raw = file.getvalue().decode("utf-8-sig", errors="replace").strip()
        blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
        batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
        
        results = {}; stats = {"done": 0, "total": len(batches)}
        worker_map = {i: {"msg": "Sẵn sàng"} for i in range(n_workers)}
        pending = list(range(len(batches)))

        def worker_logic(wid):
            add_script_run_context(main_ctx)
            while pending:
                batch_idx = None
                with status_lock:
                    if pending: batch_idx = pending.pop(0)
                if batch_idx is None: break

                success = False
                chunk_text = "\n\n".join(batches[batch_idx])
                
                while not success:
                    cur_k = None
                    with status_lock:
                        # Kiểm tra key thực sự rảnh
                        for idx, k in manager.items():
                            if k["status"] == "ACTIVE" and not k["in_use"] and (datetime.now() - k["last_finished"]).total_seconds() >= c_time:
                                cur_k = idx; k["in_use"] = True; k["job"] = f"Lô {batch_idx+1}"; break
                    
                    if cur_k is None:
                        if not any(k["status"] == "ACTIVE" for k in manager.values()): return
                        worker_map[wid] = {"msg": f"Lô {batch_idx+1}: Chờ Key..."}
                        time.sleep(2); continue

                    worker_map[wid] = {"msg": f"Lô {batch_idx+1}: Đang dịch (Key #{cur_k+1})"}
                    add_log(f"Luồng {wid+1} -> Key #{cur_k+1} xử lý Lô {batch_idx+1}")
                    
                    # DỊCH
                    prompt = f"Dịch SRT sang tiếng Việt Tiên Hiệp. THUẬT NGỮ: {st.session_state.glossary}"
                    res = call_api(manager[cur_k]["key"], model_choice, prompt, chunk_text)
                    
                    with status_lock:
                        manager[cur_k]["in_use"] = False
                        manager[cur_k]["last_finished"] = datetime.now()
                        manager[cur_k]["job"] = ""
                        
                        if "ERR" not in res and res.count("-->") >= len(batches[batch_idx]):
                            results[batch_idx] = res
                            stats["done"] += 1
                            success = True
                            add_log(f"✅ Xong Lô {batch_idx+1}")
                        else:
                            add_log(f"❌ Lỗi Lô {batch_idx+1} tại Key #{cur_k+1}: {res[:60]}")
                            if any(x in res.upper() for x in ["401", "429", "INVALID", "QUOTA"]):
                                manager[cur_k]["status"] = "DEAD"
                            time.sleep(1)

        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            for i in range(n_workers): executor.submit(worker_logic, i)
            while stats["done"] < stats["total"]:
                refresh_ui(worker_map)
                p_bar.progress(stats["done"] / stats["total"])
                p_text.info(f"Tiến độ: {stats['done']}/{stats['total']} lô")
                if not any(k["status"] == "ACTIVE" for k in manager.values()):
                    add_log("🛑 CẠN KIỆT LINH THẠCH. DỪNG TRẬN.")
                    break
                time.sleep(1)

        if stats["done"] == stats["total"]:
            st.session_state.final_results = "\n\n".join([results[i] for i in sorted(results.keys())])
            add_log("🎉 LUYỆN HÓA VIÊN MÃN.")
            st.rerun()

if st.session_state.final_results:
    st.success("🎉 Hoàn thành!")
    st.download_button("📥 TẢI BẢN DỊCH FULL", st.session_state.final_results, f"DICH_FULL_{file.name}", use_container_width=True, type="primary")

import sys
import os
import streamlit as st
from google import genai
from google.genai import types
import time
import re
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

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
st.set_page_config(page_title="Donghua v75.8 - Càn Khôn", page_icon="🔱", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    [data-testid="stSidebar"] { background-color: #161b22 !important; border-right: 1px solid #30363d; }
    .key-box { padding: 8px; border-radius: 6px; text-align: center; border: 1px solid #30363d; font-size: 0.75rem; margin-bottom: 5px; min-height: 60px; }
    .k-active { background: #1a4d2e; color: #aff5b4; border: 1px solid #2ea043; }
    .k-busy { background: #05445e; color: #c2e0ff; border: 1px solid #189ab4; }
    .k-cool { background: #5e4d05; color: #ffdf5d; border: 1px solid #d29922; }
    .k-dead { background: #4d1a1a; color: #ffd1d1; border: 1px solid #f85149; }
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
        i: {"status": "ACTIVE", "in_use": False, "last_finished": datetime.now() - timedelta(seconds=60), "key": k, "job": ""} 
        for i, k in enumerate(VALID_KEYS)
    }
if 'glossary' not in st.session_state: st.session_state.glossary = ""
if 'final_results' not in st.session_state: st.session_state.final_results = None

manager = st.session_state.key_manager
status_lock = threading.Lock()
worker_status_lock = threading.Lock()

# =========================================================
# PHÁP THUẬT MODEL 3
# =========================================================
def call_gemini_api(api_key, model_name, prompt, content):
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
# GIAO DIỆN CHÍNH
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v75.8")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    model_choice = st.selectbox("🔮 Chọn Model 3", ["gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-3.1-flash-lite-preview"], index=0)
    b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)
    c_time = st.number_input("Giây nghỉ/Key", 5, 60, 15)
    n_workers = st.slider("Số luồng xử lý", 1, 10, 4)

    if st.button("♻️ RESET HỆ THỐNG"):
        st.session_state.final_results = None
        for i in manager:
            manager[i]["status"] = "ACTIVE"
            manager[i]["in_use"] = False
        st.rerun()

tab1, tab2 = st.tabs(["📝 TỪ ĐIỂN", "⚔️ KHAI TRẬN"])

with tab1:
    st.session_state.glossary = st.text_area("Bảng thuật ngữ:", value=st.session_state.glossary, height=400)

with tab2:
    if not file:
        st.info("💡 Hãy nạp file SRT ở Sidebar.")
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
            start_btn = st.button("⚔️ THANH LỌC & KHAI TRẬN DỊCH", use_container_width=True, type="primary")

        def refresh_ui(worker_map):
            now = datetime.now()
            for i, k in manager.items():
                diff = (now - k["last_finished"]).total_seconds()
                if k["status"] == "DEAD": cls, txt = "k-dead", "💀 HỎNG"
                elif k["in_use"]: cls, txt = "k-busy", f"⚔️ {k['job']}"
                elif diff < c_time: cls, txt = "k-cool", f"🧘 {int(c_time-diff)}s"
                else: cls, txt = "k-active", "✅ SẴN SÀNG"
                k_places[i].markdown(f"<div class='key-box {cls}'><b>#{i+1}</b><br>{txt}</div>", unsafe_allow_html=True)
            for i in range(n_workers):
                info = worker_map.get(i, {"msg": "Đang chờ...", "style": "w-idle"})
                w_places[i].markdown(f"<div class='w-box {info['style']}'><b>Luồng {i+1}</b>: {info['msg']}</div>", unsafe_allow_html=True)

        if start_btn:
            main_ctx = get_script_run_context()
            
            # --- BƯỚC 1: THANH LỌC ĐA LUỒNG (TRÁNH TREO) ---
            p_text.warning("🔍 Đang thanh lọc Linh thạch...")
            def health_check(idx):
                add_script_run_context(main_ctx)
                res = call_gemini_api(manager[idx]["key"], model_choice, "ping", "hi")
                if "ERR_API" in res and any(x in res.upper() for x in ["401", "INVALID", "EXPIRED", "NOT_FOUND"]):
                    with status_lock: manager[idx]["status"] = "DEAD"

            with ThreadPoolExecutor(max_workers=10) as check_exec:
                check_exec.map(health_check, [i for i in manager if manager[i]["status"] == "ACTIVE"])
            
            if not any(k["status"] == "ACTIVE" for k in manager.values()):
                st.error("🛑 Không còn Key nào khả dụng!")
                st.stop()

            # --- BƯỚC 2: KHAI TRẬN ---
            raw = file.getvalue().decode("utf-8-sig", errors="replace").strip()
            blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
            batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
            
            results = {}; stats = {"done": 0, "total": len(batches)}
            worker_map = {i: {"msg": "Khởi động...", "style": "w-idle"} for i in range(n_workers)}
            
            # Dùng list đơn giản thay cho Queue để kiểm soát chặt hơn
            pending_batches = list(range(len(batches)))

            def worker_logic(worker_id):
                add_script_run_context(main_ctx)
                while pending_batches:
                    batch_idx = None
                    with status_lock:
                        if pending_batches: batch_idx = pending_batches.pop(0)
                    
                    if batch_idx is None: break
                    
                    chunk_text = "\n\n".join(batches[batch_idx])
                    expected = len(batches[batch_idx])
                    success = False
                    
                    while not success:
                        cur_k = None
                        with status_lock:
                            # Tìm key sẵn sàng
                            for idx, k in manager.items():
                                if k["status"] == "ACTIVE" and not k["in_use"] and (datetime.now() - k["last_finished"]).total_seconds() >= c_time:
                                    cur_k = idx; k["in_use"] = True; k["job"] = f"Lô {batch_idx+1}"; break
                        
                        if cur_k is None:
                            if not any(k["status"] == "ACTIVE" for k in manager.values()):
                                with status_lock: pending_batches.append(batch_idx) # Trả lô về
                                return
                            with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Chờ Key...", "style": "w-retry"}
                            time.sleep(2); continue

                        # Bắt đầu dịch
                        with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Dịch (Key #{cur_k+1})", "style": "w-run"}
                        
                        prompt = f"Dịch {expected} đoạn SRT sang tiếng Việt Tiên Hiệp. THUẬT NGỮ: {st.session_state.glossary}. Định dạng SRT chuẩn."
                        res = call_gemini_api(manager[cur_k]["key"], model_choice, prompt, chunk_text)
                        
                        with status_lock:
                            manager[cur_k]["in_use"] = False
                            manager[cur_k]["last_finished"] = datetime.now()
                            manager[cur_k]["job"] = ""
                            
                            if "ERR" not in res and res.count("-->") >= expected:
                                results[batch_idx] = res
                                stats["done"] += 1
                                with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: ✅ Xong", "style": "w-done"}
                                success = True
                            else:
                                # Nếu Key chết thật thì đánh dấu DEAD
                                if any(x in res.upper() for x in ["401", "429", "INVALID", "QUOTA"]):
                                    manager[cur_k]["status"] = "DEAD"
                                time.sleep(1) # Nghỉ trước khi thử key khác cho lô này
                    
                with worker_status_lock: worker_map[worker_id] = {"msg": "Hoàn tất luồng", "style": "w-done"}

            with ThreadPoolExecutor(max_workers=n_workers) as executor:
                for i in range(n_workers): executor.submit(worker_logic, i)
                while stats["done"] < stats["total"]:
                    refresh_ui(worker_map)
                    p_bar.progress(stats["done"] / stats["total"])
                    p_text.info(f"Tiến độ: {stats['done']}/{stats['total']} lô")
                    if not any(k["status"] == "ACTIVE" for k in manager.values()) and stats["done"] < stats["total"]:
                        st.error("🛑 Cạn kiệt Linh thạch! Tiến trình bị gián đoạn.")
                        break
                    time.sleep(1)

            if stats["done"] == stats["total"]:
                st.session_state.final_results = "\n\n".join([results[i] for i in sorted(results.keys())])
                st.rerun()

# =========================================================
# KẾT QUẢ
# =========================================================
if st.session_state.final_results:
    st.success("🎉 Đại công cáo thành! Bí tịch đã luyện xong.")
    st.download_button("📥 TẢI BẢN DỊCH FULL (.SRT)", st.session_state.final_results, f"DICH_FULL_{file.name}", use_container_width=True, type="primary")

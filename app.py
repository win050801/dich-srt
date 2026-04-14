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
# 🛡️ HÓA GIẢI IMPORT & CONTEXT (TRỊ DỨT ĐIỂM LỖI ĐƯỜNG DẪN)
# =========================================================
def get_context_helpers():
    """Dò tìm hàm add_script_run_context ở mọi phiên bản Streamlit"""
    try:
        from streamlit.runtime.scriptrunner import add_script_run_context, get_script_run_context
        return add_script_run_context, get_script_run_context
    except ImportError:
        try:
            from streamlit.runtime.scriptrunner.script_run_context import add_script_run_context, get_script_run_context
            return add_script_run_context, get_script_run_context
        except ImportError:
            try:
                from streamlit.scriptrunner import add_script_run_context, get_script_run_context
                return add_script_run_context, get_script_run_context
            except ImportError:
                return (lambda x: None), (lambda: None)

add_script_run_context, get_script_run_context = get_context_helpers()

# Nạp linh khí từ file .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

# =========================================================
# GIAO DIỆN PHONG THÁI CỔ TRANG (DARK MODE)
# =========================================================
st.set_page_config(page_title="Donghua v70.7 - Hiển Lộ", page_icon="🔱", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    [data-testid="stSidebar"] { background-color: #161b22 !important; border-right: 1px solid #30363d; }
    .key-box { padding: 8px; border-radius: 6px; text-align: center; border: 1px solid #30363d; font-size: 0.7rem; margin-bottom: 5px; }
    .k-active { background: #238636; color: #fff; }
    .k-busy { background: #1f6feb; color: #fff; }
    .k-dead { background: #da3633; color: #fff; }
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
    .log-title { color: #58a6ff; font-weight: bold; margin-bottom: 10px; border-bottom: 1px solid #30363d; padding-bottom: 5px; }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# QUẢN LÝ LINH LỰC (API KEYS)
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

manager = st.session_state.key_manager
status_lock = threading.Lock()
result_lock = threading.Lock()

# =========================================================
# CHIÊU THỨC AI
# =========================================================
def call_gemini(api_key, text_data, expected, glossary, model):
    try:
        client = genai.Client(api_key=api_key)
        sys_prompt = (
            f"Bạn là dịch giả SRT chuyên nghiệp. Dịch {expected} đoạn sau sang tiếng Việt phong cách Kiếm Hiệp.\n"
            f"Từ điển: {glossary}\n"
            f"Yêu cầu: Chỉ trả về nội dung SRT thô. Giữ nguyên mốc thời gian."
        )
        response = client.models.generate_content(model=model, contents=f"{sys_prompt}\n\n{text_data}")
        res = response.text.strip() if response.text else ""
        if res.count("-->") < expected:
            return f"❌ LỖI ĐỊNH DẠNG: AI trả về thiếu đoạn ({res.count('-->')}/{expected})."
        return res
    except Exception as e:
        return f"❌ LỖI HỆ THỐNG: {str(e)}"

# =========================================================
# SIDEBAR & CẤU HÌNH
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v70.7")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    
    st.divider()
    is_safe_mode = st.checkbox("🐢 SAFE MODE (Dành cho tài khoản Free)", value=True)
    
    if is_safe_mode:
        n_workers, c_time, b_size = 1, 30, 30
        st.warning("Đang bật Chế độ An toàn: 1 luồng, nghỉ 30s.")
    else:
        n_workers = st.slider("Số luồng xử lý", 1, 10, 5)
        c_time = st.number_input("Giây nghỉ/Key", 5, 60, 15)
        b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)
    
    model_choice = st.selectbox("🔮 Pháp bảo (Model)", ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-3.1-flash-lite-preview"])
    
    if st.button("🗑️ XÓA NHẬT KÝ LỖI", use_container_width=True):
        st.session_state.error_logs = []
        st.rerun()

# =========================================================
# GIAO DIỆN CHÍNH
# =========================================================
tab1, tab2 = st.tabs(["📝 LINH NHÃN (TỪ ĐIỂN)", "⚔️ KHAI TRẬN DỊCH THUẬT"])

with tab1:
    st.session_state.glossary = st.text_area("Bảng đối chiếu Trung-Việt (Gốc: Dịch):", 
                                             value=st.session_state.glossary, height=350)

with tab2:
    if not file:
        st.info("💡 Đại hiệp hãy nạp bí tịch ở Sidebar để bắt đầu.")
    else:
        col_k, col_w = st.columns([1, 2.5])
        k_places = [col_k.empty() for _ in range(len(VALID_KEYS))]
        w_places = [col_w.empty() for _ in range(n_workers)]
        
        st.divider()
        progress_bar = st.progress(0)
        st.markdown("<div class='log-title'>🕵️ Nhật Ký Truy Vết Lỗi (Thời gian thực)</div>", unsafe_allow_html=True)
        log_view = st.empty() # Nơi lỗi sẽ "hiển lộ"
        
        start_btn = st.button("🚀 BẮT ĐẦU KHAI TRẬN", type="primary", use_container_width=True)

# =========================================================
# LÕI VẬN HÀNH (MULTI-THREADING + REAL-TIME LOGGING)
# =========================================================
if file and 'start_btn' in locals() and start_btn:
    # Xử lý dữ liệu đầu vào
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
        chunk_text = "\n\n".join(batches[idx])
        expected = len(batches[idx])
        
        while True:
            cur_k = None
            with status_lock:
                for i, k_data in manager.items():
                    if k_data["status"] == "ACTIVE" and not k_data["in_use"] and (datetime.now() - k_data["last_finished"]).total_seconds() >= c_time:
                        cur_k = i; k_data["in_use"] = True; break
            
            if cur_k is None:
                time.sleep(2); continue

            worker_map[worker_id] = {"msg": f"Lô {idx+1}: Đang dịch...", "style": "color:#58a6ff;"}
            res = call_gemini(manager[cur_k]["key"], chunk_text, expected, st.session_state.glossary, model_choice)
            
            with status_lock:
                manager[cur_k]["last_finished"] = datetime.now()
                manager[cur_k]["in_use"] = False
                
                if not res.startswith("❌"):
                    with result_lock:
                        st.session_state.results[idx] = res
                    stats["done"] += 1
                    worker_map[worker_id] = {"msg": f"Lô {idx+1}: ✅ Xong", "style": "color:#3fb950;"}
                    return
                else:
                    # Ghi lỗi vào nhật ký
                    error_msg = f"[{datetime.now().strftime('%H:%M:%S')}] Lô {idx+1} (Key {cur_k+1}): {res}"
                    st.session_state.error_logs.append(error_msg)
                    
                    if "429" in res or "quota" in res.lower() or "limit" in res.lower():
                        manager[cur_k]["status"] = "DEAD"
                    
                    worker_map[worker_id] = {"msg": f"Lô {idx+1}: 🔄 Thử lại...", "style": "color:#d29922;"}
                    time.sleep(10)

    # Khởi chạy đa luồng
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        for i in range(total):
            executor.submit(worker_logic, i, i % n_workers)
        
        # Vòng lặp cập nhật UI liên tục
        while stats["done"] < total:
            # 1. Cập nhật Sidebar Keys
            for i, k in manager.items():
                cls = "k-dead" if k["status"] == "DEAD" else ("k-active" if not k["in_use"] else "k-busy")
                txt = "💀 DIE" if k["status"] == "DEAD" else ("SẴN SÀNG" if not k["in_use"] else "ĐANG DỊCH")
                k_places[i].markdown(f"<div class='key-box {cls}'><b>Key {i+1}</b><br>{txt}</div>", unsafe_allow_html=True)
            
            # 2. Cập nhật Worker Status
            for i in range(n_workers):
                info = worker_map[i]
                w_places[i].markdown(f"<div style='font-size:0.8rem; padding:5px; border:1px solid #30363d; margin-bottom:2px; {info['style']}'><b>Worker {i+1}</b>: {info['msg']}</div>", unsafe_allow_html=True)
            
            # 3. Hiển thị Lỗi (Kính chiếu yêu)
            if st.session_state.error_logs:
                logs_html = "".join([f"<div class='error-box'>{log}</div>" for log in st.session_state.error_logs[-8:]])
                log_view.markdown(logs_html, unsafe_allow_html=True)
            
            progress_bar.progress(stats["done"] / total)
            time.sleep(1)
            
            if not any(k["status"] == "ACTIVE" for k in manager.values()):
                st.error("‼️ TOÀN BỘ KEY ĐÃ CẠN LINH LỰC. DỪNG TRẬN PHÁP!")
                break

    if stats["done"] == total:
        st.success("🎉 Bí tịch đã hoàn thành hoàn mỹ!")
        final_srt = "\n\n".join([st.session_state.results[i] for i in range(total)])
        st.download_button("📥 TẢI BẢN DỊCH CHUẨN", final_srt, file_name=f"V70_7_{file.name}", use_container_width=True)
        st.balloons()
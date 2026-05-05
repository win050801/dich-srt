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

# --- HÓA GIẢI LỖI CONTEXT LUỒNG ---
try:
    from streamlit.runtime.scriptrunner import add_script_run_context, get_script_run_context
except ImportError:
    def add_script_run_context(*args, **kwargs): pass
    def get_script_run_context(*args, **kwargs): return None

# --- KHỞI TẠO CẤU HÌNH ---
st.set_page_config(page_title="Donghua v75.4 - Model 3 Pure", page_icon="🔱", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    [data-testid="stSidebar"] { background-color: #161b22 !important; border-right: 1px solid #30363d; }
    .key-box { padding: 8px; border-radius: 6px; text-align: center; border: 1px solid #30363d; font-size: 0.75rem; margin-bottom: 5px; min-height: 50px; }
    .k-active { background: #238636; color: #aff5b4; border-color: #2ea043; }
    .k-busy { background: #1f6feb; color: #c2e0ff; border-color: #388bfd; }
    .k-cool { background: #9e6a03; color: #ffdf5d; border-color: #d29922; }
    .k-dead { background: #da3633; color: #ffd1d1; border-color: #f85149; }
    .w-box { padding: 10px; border-radius: 4px; border: 1px solid #30363d; font-size: 0.8rem; margin-bottom: 5px; background: #010409; }
    .w-run { border-left: 4px solid #58a6ff; color: #58a6ff; }
    .w-done { border-left: 4px solid #3fb950; color: #3fb950; }
    .w-retry { border-left: 4px solid #d29922; color: #d29922; }
    h4 { color: #58a6ff !important; margin-top: 10px; }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# QUẢN LÝ LINH LỰC (API KEYS)
# =========================================================
RAW_KEYS = [os.getenv(f"GEMINI_KEY_{i}") for i in range(1, 21)]
VALID_KEYS = [k.strip() for k in RAW_KEYS if k and len(k.strip()) > 10]

if not VALID_KEYS:
    st.sidebar.error("🛑 Không tìm thấy API Key nào!")
    st.stop()

if 'key_manager' not in st.session_state:
    st.session_state.key_manager = {
        i: {"status": "ACTIVE", "in_use": False, "last_finished": datetime.now() - timedelta(seconds=60), "key": k} 
        for i, k in enumerate(VALID_KEYS)
    }
if 'glossary' not in st.session_state: st.session_state.glossary = ""
if 'final_results' not in st.session_state: st.session_state.final_results = None

manager = st.session_state.key_manager
status_lock = threading.Lock()
worker_status_lock = threading.Lock()

# =========================================================
# PHÁP THUẬT KIỂM TRA & DỊCH (CHỈ DÙNG MODEL 3)
# =========================================================

def check_key_health(api_key, model_name):
    """Thanh lọc linh thạch bằng chính Model 3 đã chọn"""
    try:
        client = genai.Client(api_key=api_key)
        # Gửi một tín hiệu cực ngắn để xác thực Key
        client.models.generate_content(
            model=model_name, 
            contents="ping", 
            config=types.GenerateContentConfig(max_output_tokens=1)
        )
        return True
    except Exception as e:
        msg = str(e).lower()
        # Chỉ khai tử Key nếu gặp lỗi xác thực hoặc không tồn tại
        if any(x in msg for x in ["api_key_invalid", "401", "not found", "expired", "invalid"]):
            return False
        # Nếu lỗi 429 (quá tải) hoặc lỗi server 500, vẫn giữ Key để thử lại
        return True

def call_gemini_translate(api_key, text_data, expected_count, glossary, model_name):
    try:
        client = genai.Client(api_key=api_key)
        sys_prompt = f"""Bạn là bậc thầy biên kịch Donghua. Dịch {expected_count} đoạn SRT sang tiếng Việt Tiên Hiệp.
THUẬT NGỮ CỐ ĐỊNH: {glossary}
TIÊU CHUẨN: Hán-Việt súc tích, khớp miệng lồng tiếng, đúng định dạng SRT, không gộp đoạn."""
        
        response = client.models.generate_content(
            model=model_name, 
            contents=f"{sys_prompt}\n\nNỘI DUNG SRT:\n{text_data}",
            config=types.GenerateContentConfig(
                temperature=0.3,
                safety_settings=[{"category": c, "threshold": "BLOCK_NONE"} for c in [
                    "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", 
                    "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"
                ]]
            )
        )
        res = response.text.strip() if response.text else ""
        match = re.search(r"(\d+\n\d{2}:\d{2}:\d{2},\d{3} -->.*)", res, re.DOTALL)
        return match.group(1) if match else res
    except Exception as e: return f"ERR_SYS: {str(e)}"

# =========================================================
# GIAO DIỆN CHÍNH
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v75.4")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    
    # DANH SÁCH CHỈ GỒM MODEL 3/3.1
    model_choice = st.selectbox("🔮 Chọn Model 3", [
        "gemini-3-flash-preview", 
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash-lite-preview"
    ], index=0)
    
    b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)
    c_time = st.number_input("Giây nghỉ/Key", 5, 60, 15)
    n_workers = st.slider("Số luồng xử lý", 1, 10, 4) # Mặc định 4 luồng

    if st.button("♻️ RESET HỆ THỐNG", use_container_width=True):
        st.session_state.final_results = None
        for i in manager: manager[i]["status"] = "ACTIVE"
        st.rerun()

tab1, tab2 = st.tabs(["📝 LINH NHÃN (TỪ ĐIỂN)", "⚔️ KHAI TRẬN"])

with tab1:
    st.session_state.glossary = st.text_area("Bảng thuật ngữ (Gốc: Dịch):", value=st.session_state.glossary, height=400)

with tab2:
    if not file:
        st.info("💡 Hãy nạp file SRT để bắt đầu.")
    elif st.session_state.final_results is None:
        col_k, col_w = st.columns([1, 2.5])
        with col_k:
            st.markdown("#### 📡 Linh Thạch")
            k_places = [st.empty() for _ in range(len(VALID_KEYS))]
        with col_w:
            st.markdown("#### 🌊 Luồng Xử Lý")
            w_places = [st.empty() for _ in range(n_workers)]
            st.divider()
            p_bar = st.progress(0); p_text = st.empty()
            start_btn = st.button("⚔️ THANH LỌC & KHAI TRẬN", use_container_width=True, type="primary")

        def update_ui(worker_map):
            now = datetime.now()
            for i, k in manager.items():
                diff = (now - k["last_finished"]).total_seconds()
                if k["status"] == "DEAD": cls, txt = "k-dead", "💀 HỎNG"
                elif k["in_use"]: cls, txt = "k-busy", "⚔️ DỊCH"
                elif diff < c_time: cls, txt = "k-cool", f"🧘 {int(c_time-diff)}s"
                else: cls, txt = "k-active", "✅ SẴN"
                k_places[i].markdown(f"<div class='key-box {cls}'><b>#{i+1}</b><br>{txt}</div>", unsafe_allow_html=True)
            for i in range(n_workers):
                info = worker_map.get(i, {"msg": "Đang chờ...", "style": "w-idle"})
                w_places[i].markdown(f"<div class='w-box {info['style']}'><b>Luồng {i+1}</b>: {info['msg']}</div>", unsafe_allow_html=True)

        if start_btn:
            # BƯỚC 1: THANH LỌC BẰNG CHÍNH MODEL 3 ĐÃ CHỌN
            p_text.warning(f"🔍 Đang thanh lọc Linh thạch bằng {model_choice}...")
            for i, k in manager.items():
                if k["status"] == "ACTIVE":
                    if not check_key_health(k["key"], model_choice):
                        k["status"] = "DEAD"
                    time.sleep(0.3) # Delay nhẹ để tránh bị Google chặn vì check quá nhanh
            
            if not any(k["status"] == "ACTIVE" for k in manager.values()):
                st.error("🛑 Toàn bộ Linh thạch đã cạn kiệt linh lực! Hãy kiểm tra lại Key.")
                st.stop()

            # BƯỚC 2: KHAI TRẬN DỊCH
            raw = file.getvalue().decode("utf-8-sig", errors="replace").strip()
            blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
            batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
            total = len(batches)
            results, stats = {}, {"done": 0}
            worker_map = {i: {"msg": "Khởi động...", "style": "w-idle"} for i in range(n_workers)}
            main_ctx = get_script_run_context()

            def worker_logic(batch_idx, worker_id):
                add_script_run_context(main_ctx)
                chunk_text = "\n\n".join(batches[batch_idx])
                expected = len(batches[batch_idx])
                while True:
                    cur_k = None
                    with status_lock:
                        for idx, k in manager.items():
                            if k["status"] == "ACTIVE" and not k["in_use"] and (datetime.now() - k["last_finished"]).total_seconds() >= c_time:
                                cur_k = idx; k["in_use"] = True; break
                    
                    if cur_k is None:
                        if not any(k["status"] == "ACTIVE" for k in manager.values()): return
                        with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Chờ Key...", "style": "w-retry"}
                        time.sleep(2); continue
                    
                    with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Đang dịch...", "style": "w-run"}
                    res = call_gemini_translate(manager[cur_k]["key"], chunk_text, expected, st.session_state.glossary, model_choice)
                    
                    with status_lock:
                        manager[cur_k]["last_finished"] = datetime.now(); manager[cur_k]["in_use"] = False
                        if res.count("-->") >= expected:
                            results[batch_idx] = res; stats["done"] += 1
                            with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: ✅ Xong", "style": "w-done"}
                            return
                        else:
                            # Nếu trong lúc dịch mà phát hiện Key chết hẳn
                            if any(x in res.upper() for x in ["401", "INVALID", "EXPIRED"]):
                                manager[cur_k]["status"] = "DEAD"
                            time.sleep(2)

            with ThreadPoolExecutor(max_workers=n_workers) as executor:
                for i in range(total): executor.submit(worker_logic, i, i % n_workers)
                while stats["done"] < total:
                    update_ui(worker_map)
                    p_bar.progress(stats["done"] / total)
                    p_text.info(f"Tiến độ: {stats['done']}/{total} lô")
                    time.sleep(0.5)

            st.session_state.final_results = "\n\n".join([results[i] for i in sorted(results.keys())])
            st.rerun()

# =========================================================
# KẾT QUẢ CUỐI CÙNG
# =========================================================
if st.session_state.final_results:
    st.success("🎉 Bí tịch đã luyện xong viên mãn bằng Model 3!")
    st.download_button(
        label="🚀 TẢI TOÀN BỘ BẢN DỊCH (.SRT)", 
        data=st.session_state.final_results, 
        file_name=f"FULL_{file.name if file else 'Dich.srt'}", 
        use_container_width=True, type="primary"
    )
    with st.expander("👁️ Xem trước nội dung"):
        st.text_area("Preview:", st.session_state.final_results, height=300)

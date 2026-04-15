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
def get_context_helpers():
    try:
        from streamlit.runtime.scriptrunner import add_script_run_context, get_script_run_context
        return add_script_run_context, get_script_run_context
    except: return (lambda x: None), (lambda: None)

add_script_run_context, get_script_run_context = get_context_helpers()
try: from dotenv import load_dotenv; load_dotenv()
except: pass

# =========================================================
# 🏺 ĐỊNH NGHĨA LINH LỰC TOÀN CỤC (FIX NAME ERROR)
# =========================================================
RAW_KEYS = [os.getenv(f"GEMINI_KEY_{i}") for i in range(1, 21)]
# Biến này phải được định nghĩa ở cấp cao nhất của script
VALID_KEYS = [k.strip() for k in RAW_KEYS if k and len(k.strip()) > 10]

# GIAO DIỆN
st.set_page_config(page_title="Thiên Quân v72.0 - Thiên Long", page_icon="🔱", layout="wide")

st.markdown("""<style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    [data-testid="stSidebar"] { background-color: #161b22 !important; border-right: 1px solid #30363d; }
    .key-box { padding: 12px; border-radius: 8px; text-align: center; font-size: 0.85rem; margin-bottom: 8px; color: white; font-weight: bold; }
    .k-active { background-color: #238636; border: 1px solid #2ea043; } 
    .k-busy { background-color: #1f6feb; border: 1px solid #388bfd; }   
    .k-dead { background-color: #da3633; border: 1px solid #f85149; }   
    .w-box { padding: 10px; background: #161b22; border-left: 4px solid #58a6ff; margin-bottom: 5px; font-size: 0.85rem; border-radius: 4px; }
    div.stButton > button { background-color: #ff4b4b !important; color: white !important; font-weight: bold !important; border-radius: 10px !important; width: 100%; height: 50px; }
</style>""", unsafe_allow_html=True)

# =========================================================
# QUẢN LÝ TRẠNG THÁI (SESSION STATE)
# =========================================================
if not VALID_KEYS:
    st.error("🛑 Không tìm thấy API Key nào trong .env hoặc Secrets!")
    st.stop()

if 'key_manager' not in st.session_state:
    st.session_state.key_manager = {
        i: {"status": "ACTIVE", "in_use": False, "last_finished": datetime.now() - timedelta(seconds=60), "key": k} 
        for i, k in enumerate(VALID_KEYS)
    }

if 'results' not in st.session_state: st.session_state.results = {}
if 'glossary' not in st.session_state: st.session_state.glossary = ""

manager = st.session_state.key_manager
status_lock = threading.Lock()
result_lock = threading.Lock()

# =========================================================
# ⚔️ PHÁP BẢO PROMPT: LỒNG TIẾNG + HÀI HƯỚC
# =========================================================
def call_gemini_translate(api_key, text_data, expected_count, glossary, model_name):
    try:
        client = genai.Client(api_key=api_key)
        sys_prompt = f"""Bạn là bậc thầy dịch thuật Donghua và biên kịch lồng tiếng.
Nhiệm vụ: Dịch SRT Trung -> Việt để LỒNG TIẾNG (DUBBING).

TỪ ĐIỂN ĐỒNG NHẤT:
{glossary}

YÊU CẦU:
1. ĐỘ DÀI: Câu dịch phải ngắn gọn, số âm tiết tương đương tiếng Trung để khớp miệng nhân vật. Ưu tiên dùng từ Hán Việt súc tích.
2. PHONG CÁCH: Tiên hiệp/Kiếm hiệp pha chút HÀI HƯỚC, 'CÀ KHỊA' duyên dáng. Xưng hô: Ta, Ngươi, Bổn tọa, Lão phu, Huynh đài...
3. CẤU TRÚC: Trả về đúng {expected_count} đoạn. KHÔNG ĐỔI mốc thời gian và số thứ tự.
4. KHÔNG giải thích, KHÔNG để lại tiếng Trung."""

        response = client.models.generate_content(
            model=model_name, 
            contents=f"{sys_prompt}\n\nNỘI DUNG GỐC:\n{text_data}",
            config=types.GenerateContentConfig(temperature=0.4) # Độ ảo vừa đủ để tấu hài
        )
        res = response.text.strip() if response.text else ""
        match = re.search(r"(\d+\n\d{2}:\d{2}:\d{2},\d{3} -->.*)", res, re.DOTALL)
        return match.group(1) if match else res
    except Exception as e: return f"❌ LỖI: {str(e)}"

# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v72.0")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    model_choice = st.selectbox("🔮 Chọn Model", ["gemini-3.1-flash-lite-preview", "gemini-3-flash-preview", "gemini-2.0-flash"])
    st.divider()
    n_workers = st.slider("Số luồng xử lý", 1, 10, 5)
    c_time = st.number_input("Giây nghỉ/Key", 5, 60, 15)
    b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)

# =========================================================
# GIAO DIỆN CHÍNH
# =========================================================
tab1, tab2 = st.tabs(["📝 LINH NHÃN", "⚔️ KHAI TRẬN"])

with tab1:
    st.session_state.glossary = st.text_area("Từ điển đối chiếu:", value=st.session_state.glossary, height=350)

with tab2:
    if not file:
        st.info("💡 Hãy nạp file ở Sidebar.")
    else:
        col_k, col_w = st.columns([1, 2.5])
        with col_k:
            st.markdown("#### 📡 Trạng Thái Key")
            k_places = [st.empty() for _ in range(len(VALID_KEYS))]
        with col_w:
            st.markdown("#### 🌊 Trạng Thái Luồng")
            w_places = [st.empty() for _ in range(n_workers)]
            st.divider()
            p_bar = st.progress(0)
            start_btn = st.button("🚀 BẮT ĐẦU (DỊCH HÀI & NGẮN)", use_container_width=True)

# =========================================================
# VẬN HÀNH LUỒNG
# =========================================================
if file and 'start_btn' in locals() and start_btn:
    st.session_state.results = {}
    content = file.getvalue().decode("utf-8-sig", errors="replace").strip()
    blocks = [b.strip() for b in re.split(r'\n\s*\n', content) if b.strip()]
    batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
    
    main_ctx = get_script_run_context()
    worker_status = {i: "Sẵn sàng" for i in range(n_workers)}
    completed = [0]; stop_signal = [False]

    def worker(idx, worker_id):
        add_script_run_context(main_ctx)
        if stop_signal[0]: return
        
        cur_k = None
        while cur_k is None and not stop_signal[0]:
            with status_lock:
                for i, k in manager.items():
                    if k["status"] == "ACTIVE" and not k["in_use"] and (datetime.now() - k["last_finished"]).total_seconds() >= c_time:
                        cur_k = i; k["in_use"] = True; break
            if cur_k is None: time.sleep(1)

        if cur_k is not None:
            worker_status[worker_id] = f"⏳ Lô {idx+1}: Đang tấu hài..."
            res = call_gemini_translate(manager[cur_k]["key"], "\n\n".join(batches[idx]), len(batches[idx]), st.session_state.glossary, model_choice)
            
            with status_lock:
                manager[cur_k]["in_use"] = False
                manager[cur_k]["last_finished"] = datetime.now()
                if "❌ LỖI" in res or res.count("-->") < len(batches[idx]):
                    stop_signal[0] = True; st.error(f"Lô {idx+1} thất bại: {res}")
                else:
                    with result_lock: st.session_state.results[idx] = res
                    completed[0] += 1
                    worker_status[worker_id] = f"✅ Lô {idx+1}: Xong"

    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        for i in range(len(batches)): executor.submit(worker, i, i % n_workers)
        while completed[0] < len(batches) and not stop_signal[0]:
            for i, k in manager.items():
                cls = "k-dead" if k["status"] == "DEAD" else ("k-active" if not k["in_use"] else "k-busy")
                k_places[i].markdown(f"<div class='key-box {cls}'>Key {i+1}</div>", unsafe_allow_html=True)
            for i in range(n_workers):
                w_places[i].markdown(f"<div class='w-box'><b>Luồng {i+1}:</b> {worker_status[i]}</div>", unsafe_allow_html=True)
            p_bar.progress(completed[0] / len(batches)); time.sleep(1)

    if completed[0] == len(batches):
        st.success("🎉 Hoàn tất bí tịch!")
        final_srt = "\n\n".join([st.session_state.results[i] for i in range(len(batches))])
        st.download_button("📥 TẢI BẢN DỊCH", final_srt, file_name=f"V72_DUB_{file.name}")
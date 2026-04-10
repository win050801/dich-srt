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

# --- PHÁP BẢO KHAI MÔN ---
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

# =========================================================
# GIAO DIỆN PHONG THÁI CỔ TRANG (DARK MODE)
# =========================================================
st.set_page_config(page_title="Donghua v70 - Thiên Quân Nhất Trụ", page_icon="🔱", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    [data-testid="stSidebar"] { background-color: #161b22 !important; border-right: 1px solid #30363d; }
    .key-box { padding: 8px; border-radius: 6px; text-align: center; border: 1px solid #30363d; font-size: 0.75rem; margin-bottom: 5px; min-height: 60px; }
    .k-active { background: #238636; color: #aff5b4; border-color: #2ea043; }
    .k-busy { background: #1f6feb; color: #c2e0ff; border-color: #388bfd; }
    .k-cool { background: #9e6a03; color: #ffdf5d; border-color: #d29922; }
    .k-dead { background: #da3633; color: #ffd1d1; border-color: #f85149; }
    .w-box { padding: 8px; border-radius: 4px; border: 1px solid #30363d; font-size: 0.75rem; text-align: center; background: #010409; margin-bottom: 5px; }
    .w-run { color: #58a6ff; border: 1px solid #58a6ff; }
    .w-retry { color: #d29922; border: 1px dashed #d29922; animation: blink 1.5s infinite; }
    .w-done { color: #3fb950; border: 1px solid #3fb950; }
    .w-idle { color: #8b949e; border: 1px dotted #8b949e; }
    @keyframes blink { 50% { opacity: 0.4; } }
    h4 { margin-bottom: 5px !important; color: #58a6ff !important; }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# QUẢN LÝ LINH LỰC (API KEYS)
# =========================================================
RAW_KEYS = [os.getenv(f"GEMINI_KEY_{i}") for i in range(1, 21)]
VALID_KEYS = [k.strip() for k in RAW_KEYS if k and len(k.strip()) > 10]

if not VALID_KEYS:
    st.sidebar.error("🛑 Không tìm thấy Key! Hãy nạp vào .env hoặc Secrets.")
    st.stop()

if 'key_manager' not in st.session_state:
    st.session_state.key_manager = {
        i: {"status": "ACTIVE", "in_use": False, "last_finished": datetime.now() - timedelta(seconds=60), "key": k} 
        for i, k in enumerate(VALID_KEYS)
    }

manager = st.session_state.key_manager
status_lock = threading.Lock()
worker_status_lock = threading.Lock()

def check_valid_output(text, expected_count):
    """Kính chiếu yêu: Chặn đứng rỗng, chữ Trung, và lệch mốc thời gian"""
    if not text or len(text.strip()) < 50: return False
    # Regex quét toàn bộ dải chữ Hán
    if re.search(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', text): return False
    # Đếm chính xác số mốc thời gian
    if text.count("-->") < expected_count: return False
    return True

def call_gemini(api_key, text_data, expected_count):
    try:
        client = genai.Client(api_key=api_key)
        # Hóa giải bộ lọc an toàn (Tránh lỗi 400)
        safety = [{"category": c, "threshold": "BLOCK_NONE"} for c in [
            "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", 
            "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"
        ]]
        
        # Thần chú thiết luật (Prompt tối ưu)
        sys_prompt = (
            f"You are a professional SRT translator. Translate from Chinese to Vietnamese.\n"
            f"STRICT RULES:\n"
            f"1. You MUST return exactly {expected_count} subtitle blocks.\n"
            f"2. Keep original timestamps (00:00:00,000 --> 00:00:00,000) UNCHANGED.\n"
            f"3. Style: Classical Vietnamese martial arts (võ hiệp). Use pronouns: Ta, Ngươi, Lão phu, Bổn tọa, v.v.\n"
            f"4. 100% Vietnamese output. No Chinese characters allowed.\n"
            f"5. Do not merge or skip any blocks."
        )
        
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-preview", 
            contents=f"{sys_prompt}\n\nCONTENT:\n{text_data}",
            config=types.GenerateContentConfig(temperature=0.1, safety_settings=safety)
        )
        return response.text.strip() if response.text else ""
    except Exception as e:
        return f"ERR_SYS: {str(e)}"

# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v70")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    b_size = st.number_input("Số đoạn/Lô (Nên để 50)", 10, 100, 50)
    c_time = st.number_input("Giây nghỉ/Key", 5, 60, 15)
    st.divider()
    n_workers = st.slider("Số luồng xử lý", 1, 10, 5)
    start_btn = st.button("⚔️ KHAI TRẬN", use_container_width=True, type="primary")

col_keys, col_workers = st.columns([1, 2.5])

with col_keys:
    st.markdown("#### 📡 Linh Thạch")
    k_places = [st.empty() for _ in range(len(VALID_KEYS))]

with col_workers:
    st.markdown("#### 🌊 Luồng Xử Lý")
    w_places = [st.empty() for _ in range(n_workers)]
    st.divider()
    p_bar = st.progress(0)
    p_text = st.empty()

def refresh_ui(worker_map):
    now = datetime.now()
    for i in range(len(VALID_KEYS)):
        k = manager[i]
        diff = (now - k["last_finished"]).total_seconds()
        if k["status"] == "DEAD": cls, txt = "k-dead", "💀 HỎNG"
        elif k["in_use"]: cls, txt = "k-busy", "⚔️ DỊCH"
        elif diff < c_time: cls, txt = "k-cool", f"🧘 {int(c_time-diff)}s"
        else: cls, txt = "k-active", "✅ SẴN SÀNG"
        k_places[i].markdown(f"<div class='key-box {cls}'><b>#{i+1}</b><br>{txt}</div>", unsafe_allow_html=True)
    
    for i in range(n_workers):
        info = worker_map.get(i, {"msg": "Đang chờ...", "style": "w-idle"})
        w_places[i].markdown(f"<div class='w-box {info['style']}'><b>Worker {i+1}</b>: {info['msg']}</div>", unsafe_allow_html=True)

# =========================================================
# LÕI VẬN HÀNH (QUEUE SYSTEM)
# =========================================================
if start_btn and file:
    try:
        raw = file.getvalue().decode("utf-8-sig", errors="replace").strip()
        blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
        batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
        total = len(batches)
        
        results = {}
        worker_map = {i: {"msg": "Sẵn sàng", "style": "w-idle"} for i in range(n_workers)}
        stats = {"done": 0}

        def worker_logic(batch_idx, worker_id):
            chunk_blocks = batches[batch_idx]
            expected = len(chunk_blocks)
            chunk_text = "\n\n".join(chunk_blocks)
            attempt = 0
            
            while True:
                attempt += 1
                cur_k = None
                with status_lock:
                    for i in range(len(VALID_KEYS)):
                        k = manager[i]
                        if k["status"] == "ACTIVE" and not k["in_use"] and (datetime.now() - k["last_finished"]).total_seconds() >= c_time:
                            cur_k = i; k["in_use"] = True; break
                
                if cur_k is None:
                    if not any(k["status"] == "ACTIVE" for k in manager.values()): return "FATAL"
                    with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Chờ Key...", "style": "w-retry"}
                    time.sleep(2); continue

                with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Key {cur_k+1} dịch...", "style": "w-run"}
                res = call_gemini(manager[cur_k]["key"], chunk_text, expected)
                
                with status_lock:
                    manager[cur_k]["last_finished"] = datetime.now()
                    manager[cur_k]["in_use"] = False
                    
                    if check_valid_output(res, expected):
                        results[batch_idx] = res
                        stats["done"] += 1
                        with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: ✅ Xong", "style": "w-done"}
                        return "OK"
                    else:
                        if "429" in res or "401" in res: manager[cur_k]["status"] = "DEAD"
                        with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: 🔄 Thử lại {attempt}", "style": "w-retry"}
                        time.sleep(1.5); cur_k = None

        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = {executor.submit(worker_logic, i, i % n_workers): i for i in range(total)}
            
            while stats["done"] < total:
                refresh_ui(worker_map)
                p_bar.progress(stats["done"] / total)
                p_text.info(f"Tiến độ: {stats['done']}/{total} lô.")
                if any(f.done() and f.result() == "FATAL" for f in futures.keys()):
                    st.error("🛑 Trận pháp sụp đổ! Hãy nạp thêm Key mới."); st.stop()
                time.sleep(0.5)

        final_srt = "\n\n".join([results[i] for i in range(total)])
        st.success("🎉 Bí tịch v70 đã hoàn thành hoàn mỹ!")
        st.download_button("📥 TẢI BẢN DỊCH CHUẨN", final_srt, file_name=f"V70_Final_{file.name}", use_container_width=True)
        st.balloons()

    except Exception as e:
        st.error(f"Sụp đổ: {e}")
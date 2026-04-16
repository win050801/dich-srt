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

# --- ĐỒNG BỘ CONTEXT ---
try:
    from streamlit.runtime.scriptrunner import add_script_run_context, get_script_run_context
except ImportError:
    def add_script_run_context(*args, **kwargs): pass
    def get_script_run_context(*args, **kwargs): return None

try: from dotenv import load_dotenv; load_dotenv()
except: pass

# =========================================================
# GIAO DIỆN DARK MODE
# =========================================================
st.set_page_config(page_title="Thiên Quân v72.4 - Thanh Phong", page_icon="🔱", layout="wide")

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
    .w-retry { color: #d29922; border: 1px dashed #d29922; }
    .w-done { color: #3fb950; border: 1px solid #3fb950; }
    .w-idle { color: #8b949e; border: 1px dotted #8b949e; }
    h4 { margin-bottom: 5px !important; color: #58a6ff !important; }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# QUẢN LÝ LINH LỰC
# =========================================================
RAW_KEYS = [os.getenv(f"GEMINI_KEY_{i}") for i in range(1, 21)]
VALID_KEYS = [k.strip() for k in RAW_KEYS if k and len(k.strip()) > 10]

if not VALID_KEYS:
    st.sidebar.error("🛑 Không tìm thấy Key!")
    st.stop()

if 'key_manager' not in st.session_state:
    st.session_state.key_manager = {
        i: {"status": "ACTIVE", "in_use": False, "last_finished": datetime.now() - timedelta(seconds=60), "key": k} 
        for i, k in enumerate(VALID_KEYS)
    }
if 'glossary' not in st.session_state: st.session_state.glossary = ""

manager = st.session_state.key_manager
status_lock = threading.Lock()
worker_status_lock = threading.Lock()

# =========================================================
# ⚔️ BÍ KÍP PROMPT "THANH PHONG" (ĐÃ TỐI ƯU LẠI TỪ GỐC)
# =========================================================
def call_gemini_translate(api_key, text_data, expected_count, glossary, model_name):
    try:
        client = genai.Client(api_key=api_key)
        
        # PROMPT MỚI: TẬP TRUNG VÀO SỰ TỰ NHIÊN, KHÔNG GƯỢNG ÉP
        sys_prompt = f"""Bạn là dịch giả Donghua (phim hoạt hình Trung Quốc) lão luyện.
Nhiệm vụ: Dịch SRT từ tiếng Trung sang tiếng Việt chuyên dùng cho LỒNG TIẾNG.

YÊU CẦU CỐT LÕI:
1. VĂN PHONG: Sử dụng ngôn ngữ Tiên Hiệp/Kiếm Hiệp tự nhiên, thoát ý. X xưng hô (Ta, Ngươi, Huynh, Đệ...) phải chuẩn mực theo ngữ cảnh. Tránh dịch cứng nhắc theo từng chữ.
2. ĐỘ NÉN DUBBING: Câu dịch phải súc tích, ưu tiên từ Hán-Việt để độ dài âm tiết tương đương tiếng Trung, giúp lồng tiếng không bị nhanh hay hụt hơi.
3. TỰ NHIÊN: Có thể pha chút hóm hỉnh nhẹ nhàng nếu ngữ cảnh cho phép, nhưng phải nhã nhặn, không dùng từ lóng hiện đại quá đà gây cảm giác gượng ép.
4. CẤU TRÚC: Trả về chính xác {expected_count} đoạn SRT. KHÔNG GỘP đoạn, giữ nguyên mốc thời gian.

DANH SÁCH THUẬT NGỮ:
{glossary}

HÃY DỊCH NỘI DUNG SAU ĐÂY:"""

        response = client.models.generate_content(
            model=model_name, 
            contents=f"{sys_prompt}\n\nCONTENT:\n{text_data}",
            config=types.GenerateContentConfig(
                temperature=0.25, # Giảm nhiệt độ để tránh AI "chém gió" quá đà gây gượng
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
# GIAO DIỆN (GIỮ NGUYÊN BỐ CỤC)
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v72.4")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    model_choice = st.selectbox("🔮 Model", ["gemini-3.1-flash-lite-preview", "gemini-3-flash-preview", "gemini-2.5-flash"], index=0)
    st.divider()
    n_workers = st.slider("Số luồng xử lý", 1, 10, 5)
    c_time = st.number_input("Giây nghỉ/Key", 5, 60, 15)
    b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)

tab1, tab2 = st.tabs(["📝 LINH NHÃN (TỪ ĐIỂN)", "⚔️ KHAI TRẬN"])

with tab1:
    st.session_state.glossary = st.text_area("Từ điển đối chiếu:", value=st.session_state.glossary, height=350)

with tab2:
    col_keys, col_workers = st.columns([1, 2.5])
    with col_keys:
        st.markdown("#### 📡 Key")
        k_places = [st.empty() for _ in range(len(VALID_KEYS))]
    with col_workers:
        st.markdown("#### 🌊 Luồng")
        w_places = [st.empty() for _ in range(n_workers)]
        st.divider()
        p_bar = st.progress(0); p_text = st.empty()
        start_btn = st.button("🚀 BẮT ĐẦU DỊCH (TỰ NHIÊN & KHỚP MIỆNG)", use_container_width=True, type="primary")

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
# LÕI VẬN HÀNH
# =========================================================
if 'start_btn' in locals() and start_btn and file:
    try:
        raw = file.getvalue().decode("utf-8-sig", errors="replace").strip()
        blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
        batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
        total = len(batches)
        
        results, stats = {}, {"done": 0}
        worker_map = {i: {"msg": "Sẵn sàng", "style": "w-idle"} for i in range(n_workers)}
        main_ctx = get_script_run_context()

        def worker_logic(batch_idx, worker_id, glossary_text, selected_model):
            add_script_run_context(main_ctx)
            chunk_blocks = batches[batch_idx]; expected = len(chunk_blocks)
            chunk_text = "\n\n".join(chunk_blocks)
            
            while True:
                cur_k = None
                with status_lock:
                    for i in range(len(VALID_KEYS)):
                        k = manager[i]
                        if k["status"] == "ACTIVE" and not k["in_use"] and (datetime.now() - k["last_finished"]).total_seconds() >= c_time:
                            cur_k = i; k["in_use"] = True; break
                
                if cur_k is None:
                    if not any(k["status"] == "ACTIVE" for k in manager.values()): return "FATAL"
                    with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Đợi Key...", "style": "w-retry"}
                    time.sleep(2); continue

                with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Đang dịch...", "style": "w-run"}
                res = call_gemini_translate(manager[cur_k]["key"], chunk_text, expected, glossary_text, selected_model)
                
                with status_lock:
                    manager[cur_k]["last_finished"] = datetime.now(); manager[cur_k]["in_use"] = False
                    if res.count("-->") >= expected:
                        results[batch_idx] = res; stats["done"] += 1
                        with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: ✅ Xong", "style": "w-done"}
                        return "OK"
                    else:
                        time.sleep(2)

        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            for i in range(total): 
                executor.submit(worker_logic, i, i % n_workers, st.session_state.glossary, model_choice)
            
            while stats["done"] < total:
                refresh_ui(worker_map)
                p_bar.progress(stats["done"] / total)
                p_text.info(f"Tiến độ: {stats['done']}/{total} lô. Sử dụng: {model_choice}")
                time.sleep(0.5)

        final_srt = "\n\n".join([results[i] for i in sorted(results.keys())])
        st.success(f"🎉 Đã hoàn thành bí tịch v72.4!")
        st.download_button(f"📥 TẢI BẢN DỊCH TỰ NHIÊN", final_srt, file_name=f"V72_4_{file.name}", use_container_width=True)

    except Exception as e: st.error(f"Sụp đổ: {e}")
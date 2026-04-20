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

# --- PHÁP BẢO KHAI MÔN ---
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

# =========================================================
# GIAO DIỆN v73.3
# =========================================================
st.set_page_config(page_title="Donghua v73.3 - Định Luồng", page_icon="🔱", layout="wide")

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
# QUẢN LÝ TRẠNG THÁI
# =========================================================
if 'glossary' not in st.session_state: st.session_state.glossary = ""
if 'final_results' not in st.session_state: st.session_state.final_results = None

RAW_KEYS = [os.getenv(f"GEMINI_KEY_{i}") for i in range(1, 21)]
VALID_KEYS = [k.strip() for k in RAW_KEYS if k and len(k.strip()) > 10]

if not VALID_KEYS:
    st.sidebar.error("🛑 Không tìm thấy Key!")
    st.stop()

# Khởi tạo hoặc lấy lại Key Manager
if 'key_manager' not in st.session_state:
    st.session_state.key_manager = {
        i: {"status": "ACTIVE", "in_use": False, "last_finished": datetime.now() - timedelta(seconds=60), "key": k} 
        for i, k in enumerate(VALID_KEYS)
    }

# =========================================================
# CÁC HÀM XỬ LÝ (GIỮ NGUYÊN LOGIC CỦA ĐẠO HỮU)
# =========================================================
def call_gemini_scan(api_key, text_data, model_name):
    try:
        client = genai.Client(api_key=api_key)
        prompt = "Analyze this Chinese SRT. ONLY extract: Character Names, Cultivation Ranks, and Locations. Translate them to Vietnamese Hán-Việt. Format: 'Original: Vietnamese'."
        response = client.models.generate_content(model=model_name, contents=f"{prompt}\n\nCONTENT:\n{text_data[:30000]}")
        return response.text.strip() if response.text else ""
    except Exception: return ""

def call_gemini_translate(api_key, text_data, expected_count, glossary, model_name):
    try:
        client = genai.Client(api_key=api_key)
        sys_prompt = f"Dịch {expected_count} đoạn SRT sang tiếng Việt phong cách Tiên Hiệp. Thuật ngữ: {glossary}. Trả về đúng {expected_count} đoạn SRT."
        response = client.models.generate_content(
            model=model_name, 
            contents=f"{sys_prompt}\n\n{text_data}",
            config=types.GenerateContentConfig(temperature=0.3)
        )
        res = response.text.strip() if response.text else ""
        if "-->" not in res: return "ERR_FORMAT"
        return res
    except Exception as e: return f"ERR_SYS: {str(e)}"

def split_srt_by_length(srt_content, limit=4):
    blocks = [b.strip() for b in re.split(r'\n\s*\n', srt_content) if b.strip()]
    short, long = [], []
    for b in blocks:
        lines = b.split('\n')
        if len(lines) >= 3:
            txt = " ".join(lines[2:])
            if len(txt.split()) <= limit: short.append(b)
            else: long.append(b)
    return "\n\n".join(short), "\n\n".join(long)

# =========================================================
# GIAO DIỆN Sidebar
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v73.3")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    model_choice = st.selectbox("🔮 Model", ["gemini-3.1-flash-lite-preview", "gemini-3.1-pro-preview", "gemini-3-flash-preview", "gemini-2.5-flash", "gemini-2.5-pro"])
    b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)
    c_time = st.number_input("Giây nghỉ/Key", 2, 60, 10)
    n_workers = st.slider("Số luồng xử lý", 1, 10, 5)
    if st.button("♻️ RESET"): 
        st.session_state.final_results = None
        st.rerun()

tab1, tab2 = st.tabs(["📝 LINH NHÃN", "⚔️ KHAI TRẬN"])

with tab1:
    if file and st.button("🔍 QUÉT TOÀN BỘ FILE", type="primary", use_container_width=True):
        raw_scan = file.getvalue().decode("utf-8-sig", errors="replace")
        st.session_state.glossary = call_gemini_scan(VALID_KEYS[0], raw_scan, model_choice)
        st.rerun()
    st.session_state.glossary = st.text_area("Bảng đối chiếu:", value=st.session_state.glossary, height=350)

with tab2:
    if not file:
        st.info("💡 Nạp file ở Sidebar.")
    elif st.session_state.final_results is None:
        col_keys, col_workers = st.columns([1, 2.5])
        k_places = [col_keys.empty() for _ in range(len(VALID_KEYS))]
        w_places = [col_workers.empty() for _ in range(n_workers)]
        p_bar = st.progress(0)
        start_btn = st.button("⚔️ BẮT ĐẦU KHAI TRẬN", use_container_width=True, type="primary")

        if start_btn:
            raw = file.getvalue().decode("utf-8-sig", errors="replace").strip()
            blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
            batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
            
            # BIẾN DÙNG CHUNG CHO LUỒNG (KHÔNG DÙNG SESSION_STATE Ở ĐÂY)
            shared_results = {}
            shared_stats = {"done": 0}
            shared_worker_map = {i: {"msg": "Chờ...", "style": "w-idle"} for i in range(n_workers)}
            shared_keys = st.session_state.key_manager # Lấy ra dict thô
            
            lock = threading.Lock()
            main_ctx = get_script_run_context()

            def worker_logic(batch_idx, worker_id):
                add_script_run_context(main_ctx)
                batch_text = "\n\n".join(batches[batch_idx])
                expected = len(batches[batch_idx])
                
                while True:
                    cur_k_idx = -1
                    with lock:
                        for idx, info in shared_keys.items():
                            diff = (datetime.now() - info["last_finished"]).total_seconds()
                            if info["status"] == "ACTIVE" and not info["in_use"] and diff >= c_time:
                                cur_k_idx = idx
                                info["in_use"] = True
                                break
                    
                    if cur_k_idx == -1:
                        shared_worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Đợi Key...", "style": "w-retry"}
                        time.sleep(2); continue

                    shared_worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Dịch...", "style": "w-run"}
                    res = call_gemini_translate(shared_keys[cur_k_idx]["key"], batch_text, expected, st.session_state.glossary, model_choice)
                    
                    with lock:
                        shared_keys[cur_k_idx]["in_use"] = False
                        shared_keys[cur_k_idx]["last_finished"] = datetime.now()
                        if "ERR" not in res and res.count("-->") >= expected:
                            shared_results[batch_idx] = res
                            shared_stats["done"] += 1
                            shared_worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: ✅ Xong", "style": "w-done"}
                            return
                        else:
                            if "429" in res: shared_keys[cur_k_idx]["status"] = "DEAD"
                            time.sleep(2)

            with ThreadPoolExecutor(max_workers=n_workers) as executor:
                for i in range(len(batches)):
                    executor.submit(worker_logic, i, i % n_workers)
                
                # VÒNG LẶP CẬP NHẬT UI TRÊN LUỒNG CHÍNH
                while shared_stats["done"] < len(batches):
                    # Cập nhật Key UI
                    for i, k in shared_keys.items():
                        diff = (datetime.now() - k["last_finished"]).total_seconds()
                        if k["status"] == "DEAD": cls, txt = "k-dead", "💀 HỎNG"
                        elif k["in_use"]: cls, txt = "k-busy", "⚔️ DỊCH"
                        elif diff < c_time: cls, txt = "k-cool", f"🧘 {int(c_time-diff)}s"
                        else: cls, txt = "k-active", "✅ SẴN SÀNG"
                        k_places[i].markdown(f"<div class='key-box {cls}'><b>#{i+1}</b><br>{txt}</div>", unsafe_allow_html=True)
                    
                    # Cập nhật Worker UI
                    for i in range(n_workers):
                        info = shared_worker_map[i]
                        w_places[i].markdown(f"<div class='w-box {info['style']}'><b>W{i+1}</b>: {info['msg']}</div>", unsafe_allow_html=True)
                    
                    p_bar.progress(shared_stats["done"] / len(batches))
                    
                    if all(k["status"] == "DEAD" for k in shared_keys.values()):
                        st.error("🛑 Tất cả Key đã hỏng!")
                        break
                    time.sleep(0.5)

            if shared_stats["done"] == len(batches):
                st.session_state.final_results = "\n\n".join([shared_results[i] for i in sorted(shared_results.keys())])
                st.rerun()

# =========================================================
# HIỂN THỊ SAU KHI DỊCH XONG
# =========================================================
if st.session_state.final_results:
    short_srt, long_srt = split_srt_by_length(st.session_state.final_results)
    st.success("🎉 Hoàn thành!")
    c1, c2, c3 = st.columns(3)
    c1.download_button("📥 TẢI ĐOẢN CÂU", short_srt, file_name=f"SHORT_{file.name if file else 'V73.srt'}", use_container_width=True)
    c2.download_button("📥 TẢI TRƯỜNG CÂU", long_srt, file_name=f"LONG_{file.name if file else 'V73.srt'}", use_container_width=True)
    c3.download_button("📥 TẢI FULL", st.session_state.final_results, file_name=f"FULL_{file.name if file else 'V73.srt'}", use_container_width=True)

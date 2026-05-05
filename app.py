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
# GIAO DIỆN (PHONG CÁCH THIÊN QUÂN)
# =========================================================
st.set_page_config(page_title="Donghua v74.0 - Tứ Chữ", page_icon="🔱", layout="wide")

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
    .console-box { 
        background-color: #000000; 
        color: #39ff14; 
        font-family: 'Courier New', Courier, monospace; 
        padding: 10px; 
        border-radius: 5px; 
        border: 1px solid #30363d;
        height: 250px;
        overflow-y: auto;
        font-size: 0.85rem;
    }
    h4 { margin-bottom: 5px !important; color: #58a6ff !important; }
    .split-box { padding: 10px; border: 1px solid #30363d; border-radius: 8px; background: #161b22; }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# QUẢN LÝ LINH LỰC & LOGS
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
if 'final_results' not in st.session_state: st.session_state.final_results = None
if 'console_logs' not in st.session_state: st.session_state.console_logs = []

manager = st.session_state.key_manager
status_lock = threading.Lock()
worker_status_lock = threading.Lock()
log_lock = threading.Lock()

def add_log(msg):
    with log_lock:
        timestamp = datetime.now().strftime("%H:%M:%S")
        st.session_state.console_logs.append(f"[{timestamp}] {msg}")
        # Giữ lại tối đa 100 dòng log gần nhất
        if len(st.session_state.console_logs) > 100:
            st.session_state.console_logs.pop(0)

# =========================================================
# ⚔️ CÁC HÀM XỬ LÝ
# =========================================================
def call_gemini_scan(api_key, text_data, model_name):
    try:
        client = genai.Client(api_key=api_key)
        prompt = "Analyze this Chinese SRT. ONLY extract: Character Names, Cultivation Ranks, and Locations. Translate them to Vietnamese Hán-Việt. Format: 'Original: Vietnamese'."
        response = client.models.generate_content(model=model_name, contents=f"{prompt}\n\nCONTENT:\n{text_data[:35000]}")
        return response.text.strip() if response.text else ""
    except Exception as e: return f"Lỗi quét: {str(e)}"

def call_gemini_translate(api_key, text_data, expected_count, glossary, model_name):
    try:
        client = genai.Client(api_key=api_key)
        sys_prompt = f"Dịch {expected_count} đoạn SRT sau sang tiếng Việt phong cách Tiên Hiệp. Thuật ngữ: {glossary}. Trả về đúng {expected_count} đoạn."
        response = client.models.generate_content(
            model=model_name, 
            contents=f"{sys_prompt}\n\n{text_data}",
            config=types.GenerateContentConfig(temperature=0.3)
        )
        res = response.text.strip() if response.text else ""
        match = re.search(r"(\d+\n\d{2}:\d{2}:\d{2},\d{3} -->.*)", res, re.DOTALL)
        return match.group(1) if match else res
    except Exception as e: return f"ERR_SYS: {str(e)}"

# =========================================================
# GIAO DIỆN STREAMLIT
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v74.0")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    model_choice = st.selectbox("🔮 Chọn Model", ["gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-2.5-flash"], index=0)
    b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)
    c_time = st.number_input("Giây nghỉ/Key", 5, 60, 15)
    n_workers = st.slider("Số luồng xử lý", 1, 10, 5)

    if st.button("♻️ RESET HỆ THỐNG", use_container_width=True):
        st.session_state.final_results = None
        st.session_state.console_logs = []
        st.rerun()

tab1, tab2 = st.tabs(["📝 LINH NHÃN", "⚔️ KHAI TRẬN"])

with tab1:
    st.session_state.glossary = st.text_area("Bảng đối chiếu (Gốc: Dịch):", value=st.session_state.glossary, height=350)

with tab2:
    if not file:
        st.info("💡 Hãy nạp file ở Sidebar.")
    elif st.session_state.final_results is None:
        col_keys, col_workers = st.columns([1, 2.5])
        with col_keys:
            st.markdown("#### 📡 Linh Thạch")
            k_places = [st.empty() for _ in range(len(VALID_KEYS))]
        with col_workers:
            st.markdown("#### 🌊 Luồng Xử Lý")
            w_places = [st.empty() for _ in range(n_workers)]
            st.divider()
            p_bar = st.progress(0)
            start_btn = st.button("⚔️ BẮT ĐẦU KHAI TRẬN", use_container_width=True, type="primary")

        # --- CONSOLE RIÊNG BIỆT ---
        st.markdown("#### 📜 Bảng Thống Khổ (Console)")
        console_placeholder = st.empty()

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
            
            # Hiển thị log vào Console
            log_text = "\n".join(st.session_state.console_logs[::-1]) # Đảo ngược để log mới nhất lên đầu
            console_placeholder.markdown(f"<div class='console-box'>{log_text}</div>", unsafe_allow_html=True)

        if 'start_btn' in locals() and start_btn:
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
                                if manager[i]["status"] == "ACTIVE" and not manager[i]["in_use"] and (datetime.now() - manager[i]["last_finished"]).total_seconds() >= c_time:
                                    cur_k = i; manager[i]["in_use"] = True; break
                        if cur_k is None:
                            if not any(k["status"] == "ACTIVE" for k in manager.values()): return "FATAL"
                            time.sleep(1); continue

                        with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Đang dịch...", "style": "w-run"}
                        res = call_gemini_translate(manager[cur_k]["key"], chunk_text, expected, glossary_text, selected_model)
                        
                        with status_lock:
                            manager[cur_k]["last_finished"] = datetime.now(); manager[cur_k]["in_use"] = False
                            
                            if res.count("-->") >= expected:
                                results[batch_idx] = res; stats["done"] += 1
                                with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: ✅ Xong", "style": "w-done"}
                                return "OK"
                            else:
                                # GHI LỖI CHI TIẾT RA CONSOLE
                                err_type = "Thiếu dòng" if "ERR_SYS" not in res else "Lỗi API"
                                if "429" in res: 
                                    manager[cur_k]["status"] = "DEAD"
                                    err_type = "Key Chết (429)"
                                
                                add_log(f"THẤT BẠI - Lô {batch_idx+1} (Key #{cur_k+1}): {err_type} - Đang thử lại...")
                                with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: ⚠️ Lỗi (Xem Console)", "style": "w-retry"}
                                time.sleep(2)

                with ThreadPoolExecutor(max_workers=n_workers) as executor:
                    for i in range(total): executor.submit(worker_logic, i, i % n_workers, st.session_state.glossary, model_choice)
                    while stats["done"] < total:
                        refresh_ui(worker_map)
                        p_bar.progress(stats["done"] / total)
                        time.sleep(0.5)

                st.session_state.final_results = "\n\n".join([results[i] for i in sorted(results.keys())])
                st.rerun()
            except Exception as e: add_log(f"SỤP ĐỔ HỆ THỐNG: {e}")

# =========================================================
# HIỂN THỊ KẾT QUẢ
# =========================================================
if st.session_state.final_results:
    st.success(f"🎉 Bí tịch đã hoàn thành viên mãn!")
    st.download_button("📥 TẢI BẢN FULL (.srt)", st.session_state.final_results, file_name=f"FULL_{file.name if file else 'Dich.srt'}", use_container_width=True)

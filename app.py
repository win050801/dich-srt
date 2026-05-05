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

SELECTED_MODEL = "gemini-3.1-flash-lite-preview"

# =========================================================
# GIAO DIỆN
# =========================================================
st.set_page_config(page_title="Thiên Quân v74.0 - Final Fix", page_icon="🔱", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    .key-box { padding: 8px; border-radius: 6px; text-align: center; border: 1px solid #30363d; font-size: 0.75rem; margin-bottom: 5px; min-height: 60px; }
    .k-active { background: #238636; color: #aff5b4; }
    .k-busy { background: #1f6feb; color: #c2e0ff; }
    .k-cool { background: #9e6a03; color: #ffdf5d; }
    .k-dead { background: #da3633; color: #ffd1d1; }
    .w-box { padding: 8px; border-radius: 4px; border: 1px solid #30363d; font-size: 0.75rem; text-align: center; background: #010409; margin-bottom: 5px; }
    .w-run { color: #58a6ff; border: 1px solid #58a6ff; }
    .w-done { color: #3fb950; border: 1px solid #3fb950; }
    .console-box { 
        background-color: #000000; color: #39ff14; font-family: 'Courier New', monospace; 
        padding: 10px; border-radius: 5px; border: 1px solid #30363d; height: 250px; overflow-y: auto; font-size: 0.85rem;
    }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# QUẢN LÝ DỮ LIỆU
# =========================================================
RAW_KEYS = [os.getenv(f"GEMINI_KEY_{i}") for i in range(1, 21)]
VALID_KEYS = [k.strip() for k in RAW_KEYS if k and len(k.strip()) > 10]

if 'key_manager' not in st.session_state:
    st.session_state.key_manager = {
        i: {"status": "ACTIVE", "in_use": False, "last_finished": datetime.now() - timedelta(seconds=60), "key": k} 
        for i, k in enumerate(VALID_KEYS)
    }
if 'glossary' not in st.session_state: st.session_state.glossary = ""
if 'final_results' not in st.session_state: st.session_state.final_results = None
if 'console_logs' not in st.session_state: st.session_state.console_logs = []
if 'is_running' not in st.session_state: st.session_state.is_running = False

manager = st.session_state.key_manager
status_lock = threading.Lock()
worker_status_lock = threading.Lock()
log_lock = threading.Lock()

def add_log(msg):
    with log_lock:
        timestamp = datetime.now().strftime("%H:%M:%S")
        st.session_state.console_logs.append(f"[{timestamp}] {msg}")
        if len(st.session_state.console_logs) > 100: st.session_state.console_logs.pop(0)

def parse_srt(content):
    return [b.strip() for b in re.split(r'\n\s*\n', content) if b.strip()]

def get_timecode(block):
    m = re.search(r"(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})", block)
    return m.group(1) if m else None

def call_gemini_translate(api_key, text_data, expected, glossary):
    try:
        client = genai.Client(api_key=api_key)
        prompt = f"Dịch {expected} đoạn SRT sang tiếng Việt Tiên Hiệp. Thuật ngữ: {glossary}. GIỮ NGUYÊN mốc thời gian và số thứ tự. Trả về đúng {expected} đoạn."
        response = client.models.generate_content(
            model=SELECTED_MODEL, contents=f"{prompt}\n\n{text_data}",
            config=types.GenerateContentConfig(temperature=0.3)
        )
        res = response.text.strip() if response.text else ""
        match = re.search(r"(\d+\n\d{2}:\d{2}:\d{2},\d{3} -->.*)", res, re.DOTALL)
        return match.group(1) if match else res
    except Exception as e: return f"ERR_SYS: {str(e)}"

# =========================================================
# GIAO DIỆN CHÍNH
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v74.0")
    if not VALID_KEYS: st.error("🛑 Không tìm thấy API Key!"); st.stop()
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    b_size = st.number_input("Đoạn/Lô", 10, 100, 50)
    c_time = st.number_input("Giây nghỉ", 5, 60, 15)
    n_workers = st.slider("Số luồng", 1, 10, 5)
    if st.button("♻️ RESET"): 
        st.session_state.is_running = False
        st.session_state.final_results = None
        st.session_state.console_logs = []
        st.rerun()

tab1, tab2 = st.tabs(["📝 LINH NHÃN", "⚔️ KHAI TRẬN"])
with tab1:
    st.session_state.glossary = st.text_area("Từ điển:", value=st.session_state.glossary, height=300)

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
            p_bar = st.progress(0)
            if st.button("⚔️ BẮT ĐẦU KHAI TRẬN", type="primary", use_container_width=True):
                st.session_state.is_running = True

        console_placeholder = st.empty()

        def refresh_ui(worker_map, stats):
            now = datetime.now()
            for i, k in manager.items():
                diff = (now - k["last_finished"]).total_seconds()
                if k["status"] == "DEAD": cls, txt = "k-dead", "💀 HỎNG"
                elif k["in_use"]: cls, txt = "k-busy", "⚔️ DỊCH"
                elif diff < c_time: cls, txt = "k-cool", f"🧘 {int(c_time-diff)}s"
                else: cls, txt = "k-active", "✅ SẴN SÀNG"
                k_places[i].markdown(f"<div class='key-box {cls}'><b>#{i+1}</b><br>{txt}</div>", unsafe_allow_html=True)
            for i in range(n_workers):
                info = worker_map.get(i, {"msg": "Đang chờ...", "style": "w-idle"})
                w_places[i].markdown(f"<div class='w-box {info['style']}'><b>Worker {i+1}</b>: {info['msg']}</div>", unsafe_allow_html=True)
            log_text = "\n".join(st.session_state.console_logs[::-1])
            console_placeholder.markdown(f"<div class='console-box'>{log_text}</div>", unsafe_allow_html=True)

        if st.session_state.is_running:
            try:
                add_log("⚔️ HỆ THỐNG KHỞI ĐỘNG...")
                raw = file.getvalue().decode("utf-8-sig", errors="replace").strip()
                orig_blocks = parse_srt(raw)
                batches = [orig_blocks[i:i + b_size] for i in range(0, len(orig_blocks), b_size)]
                
                translated_dict = {}
                worker_map = {i: {"msg": "Sẵn sàng", "style": "w-idle"} for i in range(n_workers)}
                stats = {"done": 0} # Dùng Dictionary để tránh lỗi nonlocal SyntaxError
                main_ctx = get_script_run_context()

                def worker_logic(batch_idx, batch_content, worker_id):
                    add_script_run_context(main_ctx)
                    expected = len(batch_content)
                    while True:
                        cur_k = None
                        with status_lock:
                            for i, k in manager.items():
                                if k["status"] == "ACTIVE" and not k["in_use"] and (datetime.now() - k["last_finished"]).total_seconds() >= c_time:
                                    cur_k = i; k["in_use"] = True; break
                        if cur_k is None:
                            time.sleep(1); continue

                        with worker_status_lock: 
                            worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Đang dịch...", "style": "w-run"}
                        
                        res = call_gemini_translate(manager[cur_k]["key"], "\n\n".join(batch_content), expected, st.session_state.glossary)
                        
                        with status_lock:
                            manager[cur_k]["last_finished"] = datetime.now(); manager[cur_k]["in_use"] = False
                            res_blocks = parse_srt(res)
                            if len(res_blocks) >= expected:
                                for j, block in enumerate(res_blocks[:expected]):
                                    translated_dict[batch_idx * b_size + j] = block
                                stats["done"] += 1 # Cập nhật trực tiếp vào dict
                                with worker_status_lock: 
                                    worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Xong", "style": "w-done"}
                                return
                            if "429" in res: manager[cur_k]["status"] = "DEAD"
                            add_log(f"⚠️ Lô {batch_idx+1} thất bại, đang thử lại...")
                            time.sleep(2)

                # CHẠY ĐA LUỒNG
                with ThreadPoolExecutor(max_workers=n_workers) as executor:
                    for i in range(len(batches)):
                        executor.submit(worker_logic, i, batches[i], i % n_workers)
                    
                    while stats["done"] < len(batches):
                        refresh_ui(worker_map, stats)
                        p_bar.progress(stats["done"] / len(batches))
                        time.sleep(0.5)

                # KIỂM TRA LỖI & REPAIR (TỰ ĐỘNG)
                add_log("🔍 KIỂM TRA MỐC THỜI GIAN...")
                broken = [i for i in range(len(orig_blocks)) if i not in translated_dict or get_timecode(orig_blocks[i]) != get_timecode(translated_dict[i])]
                
                if broken:
                    add_log(f"⚡ Phát hiện {len(broken)} câu lệch. Đang đại tu...")
                    repair_batches = [broken[i:i + 20] for i in range(0, len(broken), 20)]
                    for rb_idx, r_indices in enumerate(repair_batches):
                        r_content = [orig_blocks[idx] for idx in r_indices]
                        # Sửa dùng key đầu tiên còn sống để ổn định
                        active_key = next((k["key"] for k in manager.values() if k["status"] == "ACTIVE"), VALID_KEYS[0])
                        fixed = call_gemini_translate(active_key, "\n\n".join(r_content), len(r_indices), st.session_state.glossary)
                        fixed_blocks = parse_srt(fixed)
                        if len(fixed_blocks) >= len(r_indices):
                            for j, idx in enumerate(r_indices): translated_dict[idx] = fixed_blocks[j]
                    add_log("✅ Đã đại tu xong.")

                st.session_state.final_results = "\n\n".join([translated_dict[i] for i in range(len(orig_blocks))])
                st.session_state.is_running = False
                add_log("💎 HOÀN THÀNH!")
                st.rerun()

            except Exception as e: 
                add_log(f"❌ LỖI: {str(e)}")
                st.session_state.is_running = False

if st.session_state.final_results:
    st.success("🎉 Đã hoàn thành bí tịch!")
    st.download_button("📥 TẢI FILE FULL", st.session_state.final_results, file_name=f"FINAL_{file.name if file else 'Dich.srt'}", use_container_width=True)

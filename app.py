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

# --- KHAI MÔN ---
try:
    from dotenv import load_dotenv
    load_dotenv()
except: pass

# =========================================================
# GIAO DIỆN
# =========================================================
st.set_page_config(page_title="Donghua v73.1 - Thần Thông", page_icon="🔱", layout="wide")

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
    .split-box { padding: 10px; border: 1px solid #30363d; border-radius: 8px; background: #161b22; }
    h4 { margin-bottom: 5px !important; color: #58a6ff !important; }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# KHỞI TẠO HỆ THỐNG
# =========================================================
if 'glossary' not in st.session_state: st.session_state.glossary = ""
if 'final_results' not in st.session_state: st.session_state.final_results = None

RAW_KEYS = [os.getenv(f"GEMINI_KEY_{i}") for i in range(1, 21)]
VALID_KEYS = [k.strip() for k in RAW_KEYS if k and len(k.strip()) > 10]

if not VALID_KEYS:
    st.error("🛑 Không tìm thấy Key trong môi trường (GEMINI_KEY_1...20)")
    st.stop()

# Key manager local để luồng xử lý truy cập an toàn
if 'key_data' not in st.session_state:
    st.session_state.key_data = {
        i: {"status": "ACTIVE", "in_use": False, "last_finished": datetime.now() - timedelta(seconds=60), "key": k} 
        for i, k in enumerate(VALID_KEYS)
    }

def reset_app():
    st.session_state.glossary = ""
    st.session_state.final_results = None
    st.rerun()

# =========================================================
# PHÁP THUẬT CỐT LÕI
# =========================================================
def call_gemini_scan(api_key, text_data, model_name):
    try:
        client = genai.Client(api_key=api_key)
        prompt = "Analyze this Chinese SRT. Extract: Character Names, Cultivation Ranks, Magical Items, Locations. Output ONLY 'Chinese: Vietnamese'. No explanations."
        response = client.models.generate_content(model=model_name, contents=f"{prompt}\n\nCONTENT:\n{text_data[:80000]}")
        return response.text.strip() if response.text else ""
    except Exception as e: return f"Lỗi: {str(e)}"

def call_gemini_translate(api_key, text_data, expected_count, glossary, model_name):
    try:
        client = genai.Client(api_key=api_key)
        sys_prompt = f"Bạn là biên kịch Donghua. Dịch {expected_count} đoạn SRT sang tiếng Việt Tiên Hiệp. Thuật ngữ: {glossary}. Trả về định dạng SRT, giữ nguyên thời gian."
        response = client.models.generate_content(
            model=model_name, 
            contents=f"{sys_prompt}\n\n{text_data}",
            config=types.GenerateContentConfig(temperature=0.3)
        )
        res = response.text.strip() if response.text else ""
        if "-->" not in res: return f"ERR_FORMAT: AI không trả về SRT"
        return res
    except Exception as e: return f"ERR_API: {str(e)}"

def split_srt_by_length(srt_content, limit=4):
    blocks = [b.strip() for b in re.split(r'\n\s*\n', srt_content) if b.strip()]
    short, long = [], []
    for block in blocks:
        lines = block.split('\n')
        if len(lines) >= 3:
            txt = " ".join(lines[2:])
            if len(txt.split()) <= limit: short.append(block)
            else: long.append(block)
    return "\n\n".join(short), "\n\n".join(long)

# =========================================================
# GIAO DIỆN Sidebar
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v73.1")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    model_choice = st.selectbox("🔮 Model", ["gemini-3.1-flash-lite-preview", "gemini-3.1-pro-preview", "gemini-2.5-flash", "gemini-2.5-pro"])
    b_size = st.number_input("Số đoạn/Lô", 10, 100, 40)
    c_time = st.number_input("Giây nghỉ/Key", 2, 60, 10)
    n_workers = st.slider("Số luồng", 1, 10, 5)
    st.divider()
    if st.button("♻️ RESET HỆ THỐNG", use_container_width=True): reset_app()

# =========================================================
# TABS XỬ LÝ
# =========================================================
tab1, tab2 = st.tabs(["📝 LINH NHÃN", "⚔️ KHAI TRẬN"])

with tab1:
    if file and st.button("🔍 QUÉT TỪ ĐIỂN", type="primary", use_container_width=True):
        raw_scan = file.getvalue().decode("utf-8-sig", errors="replace")
        with st.spinner("Đang soi chiếu..."):
            st.session_state.glossary = call_gemini_scan(VALID_KEYS[0], raw_scan, model_choice)
        st.rerun()
    st.session_state.glossary = st.text_area("Từ điển (Gốc: Dịch):", value=st.session_state.glossary, height=350)

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
            start_btn = st.button("⚔️ BẮT ĐẦU DỊCH", use_container_width=True, type="primary")

        if start_btn:
            raw = file.getvalue().decode("utf-8-sig", errors="replace").strip()
            blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
            batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
            
            results = {}
            stats = {"done": 0, "total": len(batches)}
            worker_map = {i: {"msg": "Chờ...", "style": "w-idle"} for i in range(n_workers)}
            
            lock = threading.Lock()
            main_ctx = get_script_run_context()

            def worker(batch_idx, worker_id):
                add_script_run_context(main_ctx)
                batch_text = "\n\n".join(batches[batch_idx])
                expected = len(batches[batch_idx])
                
                while True:
                    target_key_idx = -1
                    with lock:
                        for idx, info in st.session_state.key_data.items():
                            if info["status"] == "ACTIVE" and not info["in_use"]:
                                if (datetime.now() - info["last_finished"]).total_seconds() >= c_time:
                                    target_key_idx = idx
                                    info["in_use"] = True
                                    break
                    
                    if target_key_idx == -1:
                        worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Chờ Key...", "style": "w-retry"}
                        time.sleep(1)
                        continue

                    worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Đang dịch...", "style": "w-run"}
                    res = call_gemini_translate(st.session_state.key_data[target_key_idx]["key"], batch_text, expected, st.session_state.glossary, model_choice)
                    
                    with lock:
                        st.session_state.key_data[target_key_idx]["in_use"] = False
                        st.session_state.key_data[target_key_idx]["last_finished"] = datetime.now()
                        
                        if "ERR" not in res and res.count("-->") >= expected:
                            results[batch_idx] = res
                            stats["done"] += 1
                            worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Xong!", "style": "w-done"}
                            return
                        else:
                            if "429" in res or "Quota" in res:
                                st.session_state.key_data[target_key_idx]["status"] = "DEAD"
                            worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Thử lại...", "style": "w-retry"}
                            time.sleep(2)

            with ThreadPoolExecutor(max_workers=n_workers) as executor:
                for i in range(stats["total"]):
                    executor.submit(worker, i, i % n_workers)
                
                while stats["done"] < stats["total"]:
                    # Cập nhật UI Linh Thạch
                    for i, k in st.session_state.key_data.items():
                        diff = (datetime.now() - k["last_finished"]).total_seconds()
                        if k["status"] == "DEAD": cls, txt = "k-dead", "💀"
                        elif k["in_use"]: cls, txt = "k-busy", "⚔️"
                        elif diff < c_time: cls, txt = "k-cool", f"🧘{int(c_time-diff)}s"
                        else: cls, txt = "k-active", "✅"
                        k_places[i].markdown(f"<div class='key-box {cls}'><b>#{i+1}</b> {txt}</div>", unsafe_allow_html=True)
                    
                    # Cập nhật UI Worker
                    for i in range(n_workers):
                        w = worker_map[i]
                        w_places[i].markdown(f"<div class='w-box {w['style']}'>W{i+1}: {w['msg']}</div>", unsafe_allow_html=True)
                    
                    p_bar.progress(stats["done"] / stats["total"])
                    if all(k["status"] == "DEAD" for k in st.session_state.key_data.values()):
                        st.error("🛑 Toàn bộ Key đã cạn linh lực!")
                        break
                    time.sleep(0.5)

            if stats["done"] == stats["total"]:
                st.session_state.final_results = "\n\n".join([results[i] for i in sorted(results.keys())])
                st.rerun()

# =========================================================
# HIỂN THỊ KẾT QUẢ
# =========================================================
if st.session_state.final_results:
    short_srt, long_srt = split_srt_by_length(st.session_state.final_results)
    st.balloons()
    st.success("🔱 Dịch thuật hoàn tất!")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("<div class='split-box'><b>⚡ Đoản câu (≤4 từ)</b></div>", unsafe_allow_html=True)
        st.download_button("📥 Tải SHORT", short_srt, file_name=f"SHORT_{file.name if file else 'file.srt'}", use_container_width=True)
    with col2:
        st.markdown("<div class='split-box'><b>📖 Trường câu (>4 từ)</b></div>", unsafe_allow_html=True)
        st.download_button("📥 Tải LONG", long_srt, file_name=f"LONG_{file.name if file else 'file.srt'}", use_container_width=True)
    with col3:
        st.markdown("<div class='split-box'><b>📜 Toàn bộ bản dịch</b></div>", unsafe_allow_html=True)
        st.download_button("📥 Tải FULL", st.session_state.final_results, file_name=f"FULL_{file.name if file else 'file.srt'}", use_container_width=True)

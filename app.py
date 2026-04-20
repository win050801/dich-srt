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
# GIAO DIỆN (PHONG CÁCH v73.0)
# =========================================================
st.set_page_config(page_title="Donghua v73.0 - Định Tâm", page_icon="🔱", layout="wide")

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
    .split-box { padding: 15px; border: 1px solid #30363d; border-radius: 8px; background: #161b22; margin-top: 10px; }
    h4 { margin-bottom: 5px !important; color: #58a6ff !important; }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# KHỞI TẠO SESSION STATE (ĐỂ KHÔNG MẤT DỮ LIỆU KHI TẢI)
# =========================================================
if 'key_manager' not in st.session_state:
    RAW_KEYS = [os.getenv(f"GEMINI_KEY_{i}") for i in range(1, 21)]
    VALID_KEYS = [k.strip() for k in RAW_KEYS if k and len(k.strip()) > 10]
    if not VALID_KEYS:
        st.error("🛑 Không tìm thấy Key!")
        st.stop()
    st.session_state.key_manager = {
        i: {"status": "ACTIVE", "in_use": False, "last_finished": datetime.now() - timedelta(seconds=60), "key": k} 
        for i, k in enumerate(VALID_KEYS)
    }

if 'glossary' not in st.session_state: st.session_state.glossary = ""
if 'final_results' not in st.session_state: st.session_state.final_results = None
if 'file_name' not in st.session_state: st.session_state.file_name = ""

def reset_app():
    for key in ['glossary', 'final_results', 'file_name']:
        st.session_state[key] = "" if key != 'final_results' else None
    st.rerun()

# =========================================================
# ⚔️ THUẬT TOÁN LINH NHÃN & DỊCH
# =========================================================
def call_gemini_scan(api_key, text_data, model_name):
    try:
        client = genai.Client(api_key=api_key)
        prompt = (
            "You are a professional Chinese-to-Vietnamese translation expert for Donghua. "
            "Extract ALL: Character Names, Cultivation Ranks, Magical Items, and Locations. "
            "Output ONLY: 'Chinese: Sino-Vietnamese'. No extra text."
        )
        response = client.models.generate_content(model=model_name, contents=f"{prompt}\n\nCONTENT:\n{text_data}")
        return response.text.strip() if response.text else ""
    except Exception as e: return f"Lỗi quét: {str(e)}"

def call_gemini_translate(api_key, text_data, expected_count, glossary, model_name):
    try:
        client = genai.Client(api_key=api_key)
        sys_prompt = f"""Dịch {expected_count} đoạn SRT sang tiếng Việt Tiên Hiệp.
DANH SÁCH THUẬT NGỮ: {glossary}
TIÊU CHUẨN: Cổ phong, xưng hô chuẩn, khớp miệng. Trả về đúng định dạng SRT."""
        response = client.models.generate_content(
            model=model_name, 
            contents=f"{sys_prompt}\n\n{text_data}",
            config=types.GenerateContentConfig(temperature=0.3)
        )
        res = response.text.strip() if response.text else ""
        match = re.search(r"(\d+\n\d{2}:\d{2}:\d{2},\d{3} -->.*)", res, re.DOTALL)
        return match.group(1) if match else res
    except Exception as e: return f"ERR_SYS: {str(e)}"

def split_srt_by_length(srt_content, limit=4):
    blocks = [b.strip() for b in re.split(r'\n\s*\n', srt_content) if b.strip()]
    short_blocks, long_blocks = [], []
    for block in blocks:
        lines = block.split('\n')
        if len(lines) >= 3:
            content_text = " ".join(lines[2:])
            word_count = len(content_text.split())
            if word_count <= limit: short_blocks.append(block)
            else: long_blocks.append(block)
    return "\n\n".join(short_blocks), "\n\n".join(long_blocks)

# =========================================================
# GIAO DIỆN CHÍNH
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v73.0")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    
    model_choice = st.selectbox("🔮 Chọn Model", [
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash-lite-preview", 
        "gemini-3-flash-preview", 
        "gemini-2.5-flash",
        "gemini-2.5-pro"
    ], index=1)
    
    b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)
    c_time = st.number_input("Giây nghỉ/Key", 5, 60, 15)
    n_workers = st.slider("Số luồng xử lý", 1, 10, 5)
    
    st.divider()
    if st.button("♻️ HÓA GIẢI TRẬN PHÁP (RESET)", use_container_width=True):
        reset_app()

tab1, tab2 = st.tabs(["📝 LINH NHÃN (ĐỊNH TÍNH)", "⚔️ KHAI TRẬN"])

with tab1:
    st.markdown("#### 🏺 Linh Nhãn (Quét danh từ riêng)")
    if file and st.button("🔍 QUÉT ĐỒNG NHẤT TOÀN FILE", type="primary", use_container_width=True):
        raw_scan = file.getvalue().decode("utf-8-sig", errors="replace")
        manager = st.session_state.key_manager
        scan_key = next((manager[i]["key"] for i in manager if manager[i]["status"] == "ACTIVE"), list(manager.values())[0]["key"])
        with st.spinner("Đang đại khai Linh Nhãn..."):
            st.session_state.glossary = call_gemini_scan(scan_key, raw_scan[:100000], model_choice)
        st.rerun()
    st.session_state.glossary = st.text_area("Bảng đối chiếu (Gốc: Dịch):", value=st.session_state.glossary, height=400)

with tab2:
    if not file:
        st.info("💡 Hãy nạp file ở Sidebar.")
    else:
        st.session_state.file_name = file.name
        col_keys, col_workers = st.columns([1, 2.5])
        with col_keys:
            st.markdown("#### 📡 Linh Thạch")
            k_places = [st.empty() for _ in range(len(st.session_state.key_manager))]
        with col_workers:
            st.markdown("#### 🌊 Luồng Xử Lý")
            w_places = [st.empty() for _ in range(n_workers)]
            st.divider()
            p_bar = st.progress(0); p_text = st.empty()
            start_btn = st.button("⚔️ BẮT ĐẦU KHAI TRẬN", use_container_width=True, type="primary")

def refresh_ui(worker_map):
    now = datetime.now()
    manager = st.session_state.key_manager
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

if 'start_btn' in locals() and start_btn and file:
    try:
        raw = file.getvalue().decode("utf-8-sig", errors="replace").strip()
        blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
        batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
        total = len(batches)
        results = {}
        stats = {"done": 0}
        worker_map = {i: {"msg": "Sẵn sàng", "style": "w-idle"} for i in range(n_workers)}
        status_lock = threading.Lock()
        worker_status_lock = threading.Lock()
        main_ctx = get_script_run_context()

        def worker_logic(batch_idx, worker_id, glossary_text, selected_model):
            add_script_run_context(main_ctx)
            chunk_blocks = batches[batch_idx]; expected = len(chunk_blocks)
            chunk_text = "\n\n".join(chunk_blocks)
            manager = st.session_state.key_manager
            while True:
                cur_k = None
                with status_lock:
                    for i, k in manager.items():
                        if k["status"] == "ACTIVE" and not k["in_use"] and (datetime.now() - k["last_finished"]).total_seconds() >= c_time:
                            cur_k = i; k["in_use"] = True; break
                if cur_k is None:
                    time.sleep(2); continue
                
                res = call_gemini_translate(manager[cur_k]["key"], chunk_text, expected, glossary_text, selected_model)
                
                with status_lock:
                    manager[cur_k]["last_finished"] = datetime.now(); manager[cur_k]["in_use"] = False
                    if res.count("-->") >= expected:
                        results[batch_idx] = res; stats["done"] += 1
                        with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: ✅ Xong", "style": "w-done"}
                        return "OK"
                    else:
                        if "429" in res: manager[cur_k]["status"] = "DEAD"
                        time.sleep(2)

        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            for i in range(total): executor.submit(worker_logic, i, i % n_workers, st.session_state.glossary, model_choice)
            while stats["done"] < total:
                refresh_ui(worker_map)
                p_bar.progress(stats["done"] / total)
                time.sleep(0.5)

        # Lưu kết quả vào session_state để không bị mất khi bấm nút tải
        st.session_state.final_results = "\n\n".join([results[i] for i in sorted(results.keys())])
        st.rerun()

    except Exception as e: st.error(f"Sụp đổ: {e}")

# =========================================================
# HIỂN THỊ KẾT QUẢ VÀ TẢI XUỐNG
# =========================================================
if st.session_state.final_results:
    short_srt, long_srt = split_srt_by_length(st.session_state.final_results, limit=4)
    st.success(f"🎉 Khai trận hoàn tất!")
    
    st.markdown("### 📥 CHIẾN LỢI PHẨM")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='split-box'><b>⚡ ĐOẢN CÂU (≤ 4)</b></div>", unsafe_allow_html=True)
        st.download_button("📥 TẢI ĐOẢN CÂU", short_srt, file_name=f"SHORT_{st.session_state.file_name}", use_container_width=True, key="dl_short")
    with c2:
        st.markdown("<div class='split-box'><b>📖 TRƯỜNG CÂU (> 4)</b></div>", unsafe_allow_html=True)
        st.download_button("📥 TẢI TRƯỜNG CÂU", long_srt, file_name=f"LONG_{st.session_state.file_name}", use_container_width=True, key="dl_long")
    
    st.divider()
    st.download_button(f"📥 TẢI TOÀN BỘ BẢN DỊCH", st.session_state.final_results, file_name=f"FULL_{st.session_state.file_name}", use_container_width=True, key="dl_full")

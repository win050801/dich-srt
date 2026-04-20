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
# GIAO DIỆN v73.7 - NGUYÊN BẢN
# =========================================================
st.set_page_config(page_title="Donghua v73.7 - Nguyên Bản", page_icon="🔱", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    [data-testid="stSidebar"] { background-color: #161b22 !important; border-right: 1px solid #30363d; }
    .key-box { padding: 8px; border-radius: 6px; text-align: center; border: 1px solid #30363d; font-size: 0.75rem; margin-bottom: 5px; min-height: 60px; }
    .k-active { background: #238636; color: #aff5b4; border-color: #2ea043; }
    .k-busy { background: #1f6feb; color: #c2e0ff; border-color: #388bfd; }
    .k-cool { background: #9e6a03; color: #ffdf5d; border-color: #d29922; }
    .k-dead { background: #da3633; color: #ffd1d1; border-color: #f85149; }
    .w-box { padding: 5px; border-bottom: 1px solid #30363d; font-size: 0.85rem; }
    .log-container { background-color: #000; color: #00ff00; padding: 12px; border-radius: 5px; font-family: 'Consolas', monospace; font-size: 0.85rem; height: 350px; overflow-y: auto; border: 1px solid #30363d; line-height: 1.5; }
    .split-box { padding: 10px; border: 1px solid #30363d; border-radius: 8px; background: #161b22; }
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

if 'key_manager' not in st.session_state:
    st.session_state.key_manager = {
        i: {"status": "ACTIVE", "in_use": False, "last_finished": datetime.now() - timedelta(seconds=60), "key": k} 
        for i, k in enumerate(VALID_KEYS)
    }

# =========================================================
# PHÁP THUẬT KIỂM TRA & DỊCH (GIỮ NGUYÊN PROMPT v72.6)
# =========================================================
def verify_key(idx, model_name):
    info = st.session_state.key_manager[idx]
    try:
        client = genai.Client(api_key=info["key"])
        client.models.generate_content(model=model_name, contents="Check", config=types.GenerateContentConfig(max_output_tokens=1))
        return True, "OK"
    except Exception as e:
        err = str(e).lower()
        if any(x in err for x in ["invalid", "403", "not found", "key_invalid"]): return False, "Key Hỏng"
        return True, "Quota"

def call_gemini_translate(api_key, text_data, expected_count, glossary, model_name):
    try:
        client = genai.Client(api_key=api_key)
        sys_prompt = f"""Bạn là bậc thầy biên kịch lồng tiếng cho Donghua. 
Nhiệm vụ: Dịch {expected_count} đoạn SRT sau sang tiếng Việt phong cách Tiên Hiệp/Kiếm Hiệp.

DANH SÁCH THUẬT NGỮ CỐ ĐỊNH:
{glossary}

TIÊU CHUẨN VÀNG:
1. TRAU CHUỐT: Văn phong thoát ý, nhã nhặn, dễ hiểu nhưng đậm chất cổ phong.
2. KHỚP MIỆNG (DUBBING): Câu dịch phải có số âm tiết tương đương tiếng Trung. Dùng từ Hán-Việt để nén nghĩa tối đa cho lồng tiếng.
3. HÀI HƯỚC: Pha trộn sự dí dỏm, 'cà khịa' duyên dáng vào lời thoại. Xưng hô chuẩn mực: Ta, Ngươi, Lão phu, Bổn tọa, Các hạ...
4. ĐỊNH DẠNG: Trả về ĐÚNG {expected_count} đoạn SRT. KHÔNG đổi mốc thời gian, KHÔNG gộp đoạn.

NỘI DUNG CẦN THI TRIỂN:"""
        
        response = client.models.generate_content(
            model=model_name, 
            contents=f"{sys_prompt}\n\n{text_data}",
            config=types.GenerateContentConfig(
                temperature=0.3,
                http_options={'timeout': 60000},
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
# GIAO DIỆN CHÍNH
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v73.7")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    
    # DANH SÁCH MODEL KHÔI PHỤC THEO YÊU CẦU
    model_choice = st.selectbox("🔮 Chọn Model", [
        "gemini-3.1-flash-lite-preview",
        "gemini-3.1-pro-preview",
        "gemini-3-flash-preview", 
        "gemini-2.5-flash",
        "gemini-2.5-pro"
    ], index=0)
    
    b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)
    c_time = st.number_input("Giây nghỉ/Key", 2, 60, 10)
    n_workers = st.slider("Số luồng xử lý", 1, 10, 5)
    
    st.divider()
    if st.button("🔍 KIỂM TRA KEY (TRƯỚC KHI DỊCH)", use_container_width=True):
        with st.spinner("Đang thẩm định..."):
            for i in st.session_state.key_manager:
                ok, _ = verify_key(i, model_choice)
                if not ok: st.session_state.key_manager[i]["status"] = "DEAD"
        st.rerun()

    if st.button("♻️ RESET HỆ THỐNG", use_container_width=True):
        st.session_state.final_results = None
        st.rerun()

tab1, tab2 = st.tabs(["📝 LINH NHÃN", "⚔️ KHAI TRẬN"])

with tab1:
    st.session_state.glossary = st.text_area("Từ điển (Gốc: Dịch):", value=st.session_state.glossary, height=350)

with tab2:
    if not file:
        st.info("💡 Hãy nạp file ở Sidebar.")
    elif st.session_state.final_results is None:
        col_keys, col_workers = st.columns([1, 2.5])
        k_places = [col_keys.empty() for _ in range(len(VALID_KEYS))]
        w_places = [col_workers.empty() for _ in range(n_workers)]
        
        st.markdown("#### 📜 Linh Bảng (Logs)")
        log_placeholder = st.empty()
        p_bar = st.progress(0)
        start_btn = st.button("⚔️ BẮT ĐẦU KHAI TRẬN", use_container_width=True, type="primary")

        if start_btn:
            raw = file.getvalue().decode("utf-8-sig", errors="replace").strip()
            blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
            batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
            
            shared_results = {}
            shared_stats = {"done": 0, "logs": []}
            shared_worker_map = {i: {"msg": "Chờ...", "color": "#8b949e"} for i in range(n_workers)}
            shared_keys = st.session_state.key_manager
            
            lock = threading.Lock()
            main_ctx = get_script_run_context()

            def add_log(msg, color="#00ff00"):
                with lock:
                    ts = datetime.now().strftime("%H:%M:%S")
                    shared_stats["logs"].append(f"<span style='color: {color};'><b>[{ts}]</b> {msg}</span>")
                    if len(shared_stats["logs"]) > 100: shared_stats["logs"].pop(0)

            def worker_logic(batch_idx, worker_id):
                add_script_run_context(main_ctx)
                batch_text = "\n\n".join(batches[batch_idx]); expected = len(batches[batch_idx])
                
                while True:
                    cur_k_idx = -1
                    with lock:
                        for idx, info in shared_keys.items():
                            diff = (datetime.now() - info["last_finished"]).total_seconds()
                            if info["status"] == "ACTIVE" and not info["in_use"] and diff >= c_time:
                                cur_k_idx = idx; info["in_use"] = True; break
                    
                    if cur_k_idx == -1:
                        shared_worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Đợi Key...", "color": "#d29922"}
                        time.sleep(1); continue

                    add_log(f"W{worker_id+1} dùng Key #{cur_k_idx+1} dịch Lô {batch_idx+1}...")
                    res = call_gemini_translate(shared_keys[cur_k_idx]["key"], batch_text, expected, st.session_state.glossary, model_choice)
                    
                    with lock:
                        shared_keys[cur_k_idx]["in_use"] = False
                        shared_keys[cur_k_idx]["last_finished"] = datetime.now()
                        
                        if "ERR" not in res and res.count("-->") >= expected:
                            shared_results[batch_idx] = res; shared_stats["done"] += 1
                            shared_worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Xong ✅", "color": "#3fb950"}
                            add_log(f"✅ Lô {batch_idx+1} hoàn tất.")
                            return
                        else:
                            # Tự động loại bỏ Key hỏng
                            if any(x in res for x in ["403", "INVALID_ARGUMENT", "not found", "429"]):
                                shared_keys[cur_k_idx]["status"] = "DEAD"
                                add_log(f"💀 Key #{cur_k_idx+1} bị loại: {res[:50]}", color="#da3633")
                            else:
                                add_log(f"⚠️ Lô {batch_idx+1} thử lại...", color="#d29922")
                            time.sleep(2)

            with ThreadPoolExecutor(max_workers=n_workers) as executor:
                for i in range(len(batches)): executor.submit(worker_logic, i, i % n_workers)
                
                while shared_stats["done"] < len(batches):
                    # Update Giao diện
                    for i, k in shared_keys.items():
                        diff = (datetime.now() - k["last_finished"]).total_seconds()
                        s_cls = "k-dead" if k["status"] == "DEAD" else ("k-busy" if k["in_use"] else ("k-cool" if diff < c_time else "k-active"))
                        txt = "💀" if k["status"] == "DEAD" else ("⚔️" if k["in_use"] else (f"🧘{int(c_time-diff)}s" if diff < c_time else "✅"))
                        k_places[i].markdown(f"<div class='key-box {s_cls}'><b>#{i+1}</b><br>{txt}</div>", unsafe_allow_html=True)
                    for i in range(n_workers):
                        w = shared_worker_map[i]
                        w_places[i].markdown(f"<div class='w-box' style='color: {w['color']};'>W{i+1}: {w['msg']}</div>", unsafe_allow_html=True)
                    log_placeholder.markdown(f"<div class='log-container'>{'<br>'.join(shared_stats['logs'])}</div>", unsafe_allow_html=True)
                    p_bar.progress(shared_stats["done"] / len(batches))
                    time.sleep(0.8)

            if shared_stats["done"] == len(batches):
                st.session_state.final_results = "\n\n".join([shared_results[i] for i in sorted(shared_results.keys())])
                st.rerun()

# =========================================================
# TẢI XUỐNG
# =========================================================
if st.session_state.final_results:
    short_srt, long_srt = split_srt_by_length(st.session_state.final_results)
    st.success("🔱 Hoàn thành!")
    c1, c2, c3 = st.columns(3)
    c1.download_button("📥 ĐOẢN CÂU (≤4)", short_srt, file_name=f"SHORT_{file.name}", use_container_width=True)
    c2.download_button("📥 TRƯỜNG CÂU (>4)", long_srt, file_name=f"LONG_{file.name}", use_container_width=True)
    c3.download_button("📥 BẢN FULL", st.session_state.final_results, file_name=f"FULL_{file.name}", use_container_width=True)

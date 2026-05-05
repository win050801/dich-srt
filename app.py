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

# CỐ ĐỊNH MODEL
SELECTED_MODEL = "gemini-3.1-flash-lite-preview"

# =========================================================
# GIAO DIỆN
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
    .w-repair { color: #f85149; border: 1px dashed #f85149; }
    .w-done { color: #3fb950; border: 1px solid #3fb950; }
    .w-idle { color: #8b949e; border: 1px dotted #8b949e; }
    .console-box { 
        background-color: #000000; color: #39ff14; 
        font-family: 'Courier New', monospace; padding: 10px; border-radius: 5px; 
        border: 1px solid #30363d; height: 250px; overflow-y: auto; font-size: 0.85rem;
    }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# QUẢN LÝ LINH LỰC & LOGS
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

manager = st.session_state.key_manager
status_lock = threading.Lock()
worker_status_lock = threading.Lock()
log_lock = threading.Lock()

def add_log(msg):
    with log_lock:
        timestamp = datetime.now().strftime("%H:%M:%S")
        st.session_state.console_logs.append(f"[{timestamp}] {msg}")
        if len(st.session_state.console_logs) > 100: st.session_state.console_logs.pop(0)

# =========================================================
# 🛠️ CÔNG CỤ KIỂM TRA & XỬ LÝ SRT
# =========================================================
def parse_srt(content):
    return [b.strip() for b in re.split(r'\n\s*\n', content) if b.strip()]

def get_timecode(block):
    match = re.search(r"(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})", block)
    return match.group(1) if match else None

def get_index(block):
    lines = block.split('\n')
    return lines[0].strip() if lines else None

def call_gemini_translate(api_key, text_data, expected_count, glossary):
    try:
        client = genai.Client(api_key=api_key)
        sys_prompt = (
            f"Dịch {expected_count} đoạn SRT sau sang tiếng việt theo phong cách cổ trang võ hiệp, tự nhiên không được gượng và trau chuốt từ ngữ sao cho dễ hiểu và dễ đọc, các đại từ nhân xưng phải theo lối cổ trang, phân chia ngôi các thứ nhân vật phải rõ ràng,câu từ ngắn gọn nhưng đủ nghĩa để dễ lồng tiếng. Thuật ngữ: {glossary}. "
            f"GIỮ NGUYÊN SỐ THỨ TỰ VÀ MỐC THỜI GIAN CỦA TỪNG ĐOẠN. Trả về đúng {expected_count} đoạn."
        )
        response = client.models.generate_content(
            model=SELECTED_MODEL, 
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
        st.info("💡 Nạp file ở Sidebar.")
    elif st.session_state.final_results is None:
        col_keys, col_workers = st.columns([1, 2.5])
        with col_keys:
            st.markdown("#### 📡 Linh Thạch")
            k_places = [st.empty() for _ in range(len(VALID_KEYS))]
        with col_workers:
            st.markdown("#### 🌊 Luồng Xử Lý")
            w_places = [st.empty() for _ in range(n_workers)]
            st.divider()
            p_bar = st.progress(0); p_text = st.empty()
            start_btn = st.button("⚔️ BẮT ĐẦU KHAI TRẬN", use_container_width=True, type="primary")

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
            log_text = "\n".join(st.session_state.console_logs[::-1])
            console_placeholder.markdown(f"<div class='console-box'>{log_text}</div>", unsafe_allow_html=True)

        if 'start_btn' in locals() and start_btn:
            try:
                raw = file.getvalue().decode("utf-8-sig", errors="replace").strip()
                orig_blocks = parse_srt(raw)
                total_blocks = len(orig_blocks)
                
                # CHIA LÔ BAN ĐẦU
                batches = [orig_blocks[i:i + b_size] for i in range(0, total_blocks, b_size)]
                total_batches = len(batches)
                
                # Cấu trúc lưu trữ: {index_đoạn: nội_dung_dịch}
                translated_dict = {} 
                stats = {"done_batches": 0}
                worker_map = {i: {"msg": "Sẵn sàng", "style": "w-idle"} for i in range(n_workers)}
                main_ctx = get_script_run_context()

                def worker_logic(batch_idx, batch_content, worker_id, is_repair=False):
                    add_script_run_context(main_ctx)
                    expected = len(batch_content)
                    chunk_text = "\n\n".join(batch_content)
                    
                    while True:
                        cur_k = None
                        with status_lock:
                            for i in range(len(VALID_KEYS)):
                                if manager[i]["status"] == "ACTIVE" and not manager[i]["in_use"] and (datetime.now() - manager[i]["last_finished"]).total_seconds() >= c_time:
                                    cur_k = i; manager[i]["in_use"] = True; break
                        if cur_k is None:
                            if not any(k["status"] == "ACTIVE" for k in manager.values()): return
                            time.sleep(1); continue

                        status_msg = "Sửa lỗi..." if is_repair else "Dịch..."
                        style_msg = "w-repair" if is_repair else "w-run"
                        with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: {status_msg}", "style": style_msg}
                        
                        res_text = call_gemini_translate(manager[cur_k]["key"], chunk_text, expected, st.session_state.glossary)
                        
                        with status_lock:
                            manager[cur_k]["last_finished"] = datetime.now(); manager[cur_k]["in_use"] = False
                            
                            res_blocks = parse_srt(res_text)
                            if len(res_blocks) >= expected:
                                # Lưu kết quả theo thứ tự tuyệt đối
                                start_idx = batch_idx * b_size if not is_repair else 0 # (Lưu ý: repair sẽ xử lý logic khác)
                                for j, rb in enumerate(res_blocks[:expected]):
                                    # Trong bước dịch chính, batch_idx là thứ tự lô. 
                                    # Trong repair, ta sẽ truyền danh sách index cụ thể.
                                    pass 
                                return res_blocks[:expected]
                            else:
                                if "429" in res_text: manager[cur_k]["status"] = "DEAD"
                                add_log(f"Thử lại lô {batch_idx+1} (Key #{cur_k+1})")
                                time.sleep(2)

                # --- GIAI ĐOẠN 1: DỊCH TỔNG LỰC ---
                add_log("BẮT ĐẦU GIAO CHIẾN: Dịch toàn bộ file...")
                with ThreadPoolExecutor(max_workers=n_workers) as executor:
                    futures = {executor.submit(worker_logic, i, batches[i], i % n_workers): i for i in range(total_batches)}
                    for future in futures:
                        idx = futures[future]
                        res_blocks = future.result()
                        # Lưu vào từ điển kết quả tạm thời
                        for j, block in enumerate(res_blocks):
                            translated_dict[idx * b_size + j] = block
                        stats["done_batches"] += 1
                        p_bar.progress(stats["done_batches"] / total_batches)
                        refresh_ui(worker_map)

                # --- GIAI ĐOẠN 2: TỔNG KIỂM KÊ & ĐẠI TU (REPAIR) ---
                add_log("TỔNG KIỂM KÊ: Đang quét lỗi mốc thời gian...")
                
                def run_audit():
                    broken_indices = []
                    for i in range(total_blocks):
                        orig = orig_blocks[i]
                        trans = translated_dict.get(i, "")
                        if not trans or get_timecode(orig) != get_timecode(trans) or get_index(orig) != get_index(trans):
                            broken_indices.append(i)
                    return broken_indices

                broken_indices = run_audit()
                
                if broken_indices:
                    add_log(f"PHÁT HIỆN {len(broken_indices)} câu lệch mốc. Đang gom lô để ĐẠI TU...")
                    # Gom các câu lỗi thành các lô mới (ví dụ lô 20 câu để Gemini tập trung sửa thời gian)
                    repair_size = 20
                    repair_batches = [broken_indices[i:i + repair_size] for i in range(0, len(broken_indices), repair_size)]
                    
                    stats["done_repair"] = 0
                    for r_idx, r_batch in enumerate(repair_batches):
                        repair_content = [orig_blocks[idx] for idx in r_batch]
                        # Gửi đi dịch lại
                        fixed_res = worker_logic(r_idx, repair_content, 0, is_repair=True)
                        if fixed_res:
                            for j, idx_in_orig in enumerate(r_batch):
                                translated_dict[idx_in_orig] = fixed_res[j]
                        stats["done_repair"] += 1
                        add_log(f"Đã sửa xong lô repair {r_idx+1}/{len(repair_batches)}")
                
                # --- HOÀN TẤT ---
                final_srt = "\n\n".join([translated_dict[i] for i in range(total_blocks)])
                st.session_state.final_results = final_srt
                st.rerun()
                
            except Exception as e: add_log(f"SỤP ĐỔ: {e}")

# =========================================================
# HIỂN THỊ KẾT QUẢ
# =========================================================
if st.session_state.final_results:
    st.success(f"🎉 Bí tịch đã chuẩn hóa mốc thời gian và hoàn thành!")
    st.download_button("📥 TẢI BẢN FULL (.srt)", st.session_state.final_results, file_name=f"FULL_{file.name if file else 'Dich.srt'}", use_container_width=True)

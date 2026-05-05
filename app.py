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
# GIAO DIỆN (GIỮ NGUYÊN PHONG CÁCH v72.6 GỐC)
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
    h4 { margin-bottom: 5px !important; color: #58a6ff !important; }
    .split-box { padding: 10px; border: 1px solid #30363d; border-radius: 8px; background: #161b22; }
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
if 'final_results' not in st.session_state: st.session_state.final_results = None

manager = st.session_state.key_manager
status_lock = threading.Lock()
worker_status_lock = threading.Lock()

# =========================================================
# ⚔️ CÁC HÀM XỬ LÝ
# =========================================================
def call_gemini_scan(api_key, text_data, model_name):
    try:
        client = genai.Client(api_key=api_key)
        prompt = (
            "Analyze this Chinese SRT. ONLY extract: Character Names, Cultivation Ranks, and Locations. "
            "Translate them to Vietnamese Hán-Việt. Format: 'Original: Vietnamese'. "
            "No sentences, no explanations, no duplicate entries. Focus ONLY on entities."
        )
        response = client.models.generate_content(
            model=model_name,
            contents=f"{prompt}\n\nCONTENT:\n{text_data[:35000]}"
        )
        return response.text.strip() if response.text else ""
    except Exception as e: return f"Lỗi quét: {str(e)}"

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

# Hàm kiểm tra tính hợp lệ của lô dịch
def validate_batch(res_text, expected_count):
    blocks = [b.strip() for b in re.split(r'\n\s*\n', res_text) if b.strip()]
    if len(blocks) != expected_count: return False
    # Kiểm tra xem có đủ mốc thời gian không
    if res_text.count("-->") != expected_count: return False
    return True

def extract_timestamp(block):
    match = re.search(r"\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}", block)
    return match.group(0) if match else ""

# =========================================================
# GIAO DIỆN STREAMLIT
# =========================================================
with st.sidebar:
    st.title("🔱 THIÊN QUÂN v74.0")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    
    model_choice = st.selectbox("🔮 Chọn Model", [
        "gemini-3-flash-preview", 
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash-lite-preview", 
        "gemini-2.5-flash",
        "gemini-2.5-pro"
    ], index=2)
    
    b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)
    c_time = st.number_input("Giây nghỉ/Key", 5, 60, 15)
    n_workers = st.slider("Số luồng xử lý", 1, 10, 5)

    if st.button("♻️ RESET HỆ THỐNG", use_container_width=True):
        st.session_state.final_results = None
        st.rerun()

tab1, tab2 = st.tabs(["📝 LINH NHÃN (TỪ ĐIỂN)", "⚔️ KHAI TRẬN"])

with tab1:
    st.markdown("#### 🏺 Linh Nhãn (Quét tên nhân vật & cảnh giới)")
    if file and st.button("🔍 QUÉT TOÀN BỘ FILE", type="primary", use_container_width=True):
        raw_scan = file.getvalue().decode("utf-8-sig", errors="replace")
        scan_key = next((manager[i]["key"] for i in manager if manager[i]["status"] == "ACTIVE"), VALID_KEYS[0])
        with st.spinner("Đang trích xuất danh tính..."):
            st.session_state.glossary = call_gemini_scan(scan_key, raw_scan, model_choice)
        st.rerun()
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
            p_bar = st.progress(0); p_text = st.empty()
            start_btn = st.button("⚔️ BẮT ĐẦU KHAI TRẬN", use_container_width=True, type="primary")

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

        if 'start_btn' in locals() and start_btn and file:
            try:
                raw_text = file.getvalue().decode("utf-8-sig", errors="replace").strip()
                orig_blocks = [b.strip() for b in re.split(r'\n\s*\n', raw_text) if b.strip()]
                batches = [orig_blocks[i:i + b_size] for i in range(0, len(orig_blocks), b_size)]
                total = len(batches)
                results, stats = {}, {"done": 0}
                worker_map = {i: {"msg": "Sẵn sàng", "style": "w-idle"} for i in range(n_workers)}
                main_ctx = get_script_run_context()

                def worker_logic(batch_idx, worker_id, glossary_text, selected_model, current_batch_data):
                    add_script_run_context(main_ctx)
                    expected = len(current_batch_data)
                    chunk_text = "\n\n".join(current_batch_data)
                    
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
                        
                        with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: Dịch...", "style": "w-run"}
                        res = call_gemini_translate(manager[cur_k]["key"], chunk_text, expected, glossary_text, selected_model)
                        
                        with status_lock:
                            manager[cur_k]["last_finished"] = datetime.now(); manager[cur_k]["in_use"] = False
                            if validate_batch(res, expected):
                                results[batch_idx] = res; stats["done"] += 1
                                with worker_status_lock: worker_map[worker_id] = {"msg": f"Lô {batch_idx+1}: ✅ Xong", "style": "w-done"}
                                return "OK"
                            else:
                                if "429" in res: manager[cur_k]["status"] = "DEAD"
                                time.sleep(2)

                # Chạy luồng dịch chính
                with ThreadPoolExecutor(max_workers=n_workers) as executor:
                    for i in range(total): executor.submit(worker_logic, i, i % n_workers, st.session_state.glossary, model_choice, batches[i])
                    while stats["done"] < total:
                        refresh_ui(worker_map)
                        p_bar.progress(stats["done"] / total)
                        time.sleep(0.5)

                # =========================================================
                # HẬU KIỂM: SO KHỚP MỐC THỜI GIAN
                # =========================================================
                p_text.info("🛠️ Đang kiểm tra linh lực mốc thời gian...")
                full_translated_raw = "\n\n".join([results[i] for i in sorted(results.keys())])
                trans_blocks = [b.strip() for b in re.split(r'\n\s*\n', full_translated_raw) if b.strip()]
                
                # Tìm các câu bị lệch mốc thời gian
                error_indices = []
                for i in range(len(orig_blocks)):
                    orig_ts = extract_timestamp(orig_blocks[i])
                    # Nếu dịch thiếu block hoặc mốc thời gian không khớp
                    if i >= len(trans_blocks) or extract_timestamp(trans_blocks[i]) != orig_ts:
                        error_indices.append(i)
                
                if error_indices:
                    p_text.warning(f"⚠️ Phát hiện {len(error_indices)} mốc thời gian sai lệch. Đang truy hồi...")
                    # Gom những block lỗi thành lô mới để dịch lại
                    fix_batches = [orig_blocks[idx] for idx in error_indices]
                    # Tạm thời reset để chạy lại worker_logic cho các lô lỗi
                    results.clear(); stats["done"] = 0
                    fix_data_batches = [fix_batches[i:i + b_size] for i in range(0, len(fix_batches), b_size)]
                    
                    with ThreadPoolExecutor(max_workers=n_workers) as executor:
                        for i in range(len(fix_data_batches)):
                            executor.submit(worker_logic, i, i % n_workers, st.session_state.glossary, model_choice, fix_data_batches[i])
                        while stats["done"] < len(fix_data_batches):
                            refresh_ui(worker_map)
                            time.sleep(0.5)
                    
                    # Thay thế các block lỗi bằng block đã sửa
                    fixed_blocks_flat = []
                    for i in sorted(results.keys()):
                        fixed_blocks_flat.extend([b.strip() for b in re.split(r'\n\s*\n', results[i]) if b.strip()])
                    
                    for i, orig_idx in enumerate(error_indices):
                        if i < len(fixed_blocks_flat):
                            if orig_idx < len(trans_blocks): trans_blocks[orig_idx] = fixed_blocks_flat[i]
                            else: trans_blocks.append(fixed_blocks_flat[i])

                st.session_state.final_results = "\n\n".join(trans_blocks)
                st.rerun()
            except Exception as e: st.error(f"Sụp đổ: {e}")

# =========================================================
# HIỂN THỊ KẾT QUẢ VÀ TẢI XUỐNG
# =========================================================
if st.session_state.final_results:
    st.success(f"🎉 Bí tịch đã hoàn thành viên mãn!")
    st.download_button(
        "📥 TẢI BẢN DỊCH FULL (.srt)", 
        st.session_state.final_results, 
        file_name=f"FULL_{file.name if file else 'Dich.srt'}", 
        use_container_width=True,
        type="primary"
    )
    with st.expander("Xem trước bản dịch"):
        st.text_area("", st.session_state.final_results, height=400)

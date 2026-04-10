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
# GIAO DIỆN CÀN KHÔN (GỌN GÀNG - TINH TẾ)
# =========================================================
st.set_page_config(page_title="Donghua Càn Khôn v65", page_icon="🔱", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0b0e14; color: #cbd5e1; }
    [data-testid="stSidebar"] { background-color: #161b22 !important; border-right: 1px solid #30363d; }
    .key-box { padding: 8px; border-radius: 6px; text-align: center; border: 1px solid #30363d; font-size: 0.75rem; margin-bottom: 5px; }
    .k-active { background: #064e3b; color: #4ade80; border-color: #238636; }
    .k-busy { background: #1e3a8a; color: #60a5fa; border-color: #1f6feb; }
    .k-cool { background: #451a03; color: #fbbf24; border-color: #9e6a03; }
    .k-dead { background: #490e0e; color: #f87171; border-color: #da3633; }
    .w-box { padding: 6px; border-radius: 4px; border: 1px solid #30363d; font-size: 0.75rem; text-align: center; background: #0d1117; }
    .w-run { color: #58a6ff; border-color: #58a6ff; }
    .w-done { color: #3fb950; border-color: #3fb950; }
    .w-retry { color: #d29922; border-color: #d29922; animation: pulse 1s infinite; }
    @keyframes pulse { 50% { opacity: 0.6; } }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# QUẢN LÝ LINH LỰC
# =========================================================
RAW_KEYS = [os.getenv(f"GEMINI_KEY_{i}") for i in range(1, 21)]
VALID_KEYS = [k.strip() for k in RAW_KEYS if k and len(k.strip()) > 10]

if not VALID_KEYS:
    st.sidebar.error("🛑 Không tìm thấy linh thạch trong .env hoặc Secrets!")
    st.stop()

if 'key_manager' not in st.session_state:
    st.session_state.key_manager = {
        i: {"status": "ACTIVE", "in_use": False, "last_finished": datetime.now() - timedelta(seconds=60), "key": k} 
        for i, k in enumerate(VALID_KEYS)
    }

manager = st.session_state.key_manager
status_lock = threading.Lock()

def validate_result(text, expected_count):
    """Kiểm tra tính nguyên vẹn của linh đan (kết quả dịch)"""
    if not text or len(text.strip()) < 50: return "Rỗng/Quá ngắn"
    
    # Quét chữ Trung (giản thể, phồn thể, bộ thủ mở rộng)
    if re.search(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', text):
        return "Còn chữ Trung"
    
    # Kiểm tra số lượng block (cho phép sai số 5% do lỗi phân tách)
    blocks = [b for b in re.split(r'\n\s*\n', text.strip()) if b.strip()]
    if len(blocks) < expected_count * 0.9:
        return f"Thiếu đoạn ({len(blocks)}/{expected_count})"
    
    return None

def call_gemini(api_key, text_data, expected_count):
    try:
        client = genai.Client(api_key=api_key)
        safety = [{"category": c, "threshold": "BLOCK_NONE"} for c in [
            "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", 
            "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"
        ]]
        
        sys_prompt = (
            f"Bạn là chuyên gia dịch thuật SRT. Dịch sang tiếng Việt võ hiệp.\n"
            f"YÊU CẦU: Dịch đúng {expected_count} đoạn. KHÔNG bỏ sót. KHÔNG để lại chữ Trung Quốc.\n"
            f"Giữ nguyên timestamps và số thứ tự."
        )
        
        response = client.models.generate_content(
            model="gemini-3-flash-preview", 
            contents=f"{sys_prompt}\n\nNỘI DUNG:\n{text_data}",
            config=types.GenerateContentConfig(temperature=0.2, safety_settings=safety)
        )
        
        res_text = response.text.strip() if response.text else ""
        error = validate_result(res_text, expected_count)
        if error: return f"ERR_VAL: {error}"
        return res_text
    except Exception as e:
        return f"ERR_SYS: {str(e)}"

# =========================================================
# GIAO DIỆN ĐIỀU KHIỂN
# =========================================================
with st.sidebar:
    st.title("🔱 CÀN KHÔN v65")
    file = st.file_uploader("📜 Nạp file .srt", type=["srt"])
    b_size = st.number_input("Đoạn/Lô", 10, 150, 70)
    c_time = st.number_input("Giây nghỉ/Key", 0, 120, 15)
    start = st.button("⚔️ KHAI TRẬN", use_container_width=True, type="primary")

col_left, col_right = st.columns([1, 3])
with col_left:
    st.caption("📡 Linh Thạch")
    k_places = [st.empty() for _ in range(len(VALID_KEYS))]

with col_right:
    st.caption("🌊 Luồng Xử Lý")
    w_cols = st.columns(5)
    w_places = [w_cols[i].empty() for i in range(5)]
    st.divider()
    p_bar = st.progress(0)
    msg_box = st.empty()

def refresh_ui():
    now = datetime.now()
    for i in range(len(VALID_KEYS)):
        k = manager[i]
        diff = (now - k["last_finished"]).total_seconds()
        if k["status"] == "DEAD": cls, txt = "k-dead", "💀 HỎNG"
        elif k["in_use"]: cls, txt = "k-busy", "⚔️ DỊCH"
        elif diff < c_time: cls, txt = "k-cool", f"🧘 {int(c_time-diff)}s"
        else: cls, txt = "k-active", "✅ SẴN SÀNG"
        k_places[i].markdown(f"<div class='key-box {cls}'><b>#{i+1}</b> {txt}</div>", unsafe_allow_html=True)

refresh_ui()

# =========================================================
# LÕI PHỤC MA (PROCESSING)
# =========================================================
if start and file:
    try:
        raw = file.getvalue().decode("utf-8-sig", errors="replace").strip()
        blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
        # Chia Batch
        batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
        # Chia Wave (Mỗi wave 5 batch tương ứng 5 worker)
        waves = [batches[i:i + 5] for i in range(0, len(batches), 5)]
        
        results = {} # Lưu kết quả theo đúng index
        total_batches = len(batches)

        for wave_idx, wave_batches in enumerate(waves):
            num_tasks = len(wave_batches)
            w_info = {j: {"msg": "Chờ...", "style": ""} for j in range(5)}

            def worker(rel_idx, chunk_blocks):
                abs_idx = wave_idx * 5 + rel_idx
                expected = len(chunk_blocks)
                text_to_send = "\n\n".join(chunk_blocks)
                retry_limit = 3
                
                for attempt in range(retry_limit):
                    cur_k = None
                    while cur_k is None:
                        with status_lock:
                            for i in range(len(VALID_KEYS)):
                                k = manager[i]
                                if k["status"] == "ACTIVE" and not k["in_use"] and (datetime.now() - k["last_finished"]).total_seconds() >= c_time:
                                    cur_k = i; k["in_use"] = True; break
                        if cur_k is None:
                            if not any(k["status"] == "ACTIVE" for k in manager.values()): return abs_idx, "FATAL"
                            time.sleep(2)

                    w_info[rel_idx] = {"msg": f"Key {cur_k+1} (Lần {attempt+1})", "style": "w-run"}
                    res = call_gemini(manager[cur_k]["key"], text_to_send, expected)
                    
                    with status_lock:
                        manager[cur_k]["last_finished"] = datetime.now()
                        manager[cur_k]["in_use"] = False
                        
                        if "ERR_" not in res:
                            w_info[rel_idx] = {"msg": "✅ Xong", "style": "w-done"}
                            return abs_idx, res
                        else:
                            # Nếu lỗi 429/401 thì giết key, lỗi validation thì cho thử lại
                            if "429" in res or "401" in res: manager[cur_k]["status"] = "DEAD"
                            w_info[rel_idx] = {"msg": "🔄 Thử lại...", "style": "w-retry"}
                            time.sleep(2)
                            cur_k = None # Tìm key mới cho lần thử tiếp theo
                
                return abs_idx, "FAILED"

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(worker, j, wave_batches[j]) for j in range(num_tasks)]
                while not all(f.done() for f in futures):
                    refresh_ui()
                    for j in range(5):
                        info = w_info[j]
                        w_places[j].markdown(f"<div class='w-box {info['style']}'>{info['msg']}</div>", unsafe_allow_html=True)
                    time.sleep(0.5)
                
                for f in futures:
                    idx, res = f.result()
                    if res == "FATAL": st.error("🛑 Trận pháp tan vỡ! Tất cả Key đã hỏng."); st.stop()
                    results[idx] = res # GHÉP ĐÚNG VỊ TRÍ THEO INDEX

            p_bar.progress((wave_idx + 1) / len(waves))
            msg_box.info(f"Đã luyện xong {min((wave_idx+1)*5, total_batches)}/{total_batches} mảnh ghép")

        # KIỂM TRA TỔNG THỂ TRƯỚC KHI XUẤT BẢN
        final_srt_blocks = []
        for i in range(total_batches):
            content = results.get(i, f"\n{i+1}\n00:00:00,000 --> 00:00:00,000\n[Mảnh ghép {i+1} bị lỗi]\n")
            final_srt_blocks.append(content)
        
        st.success("🎉 Càn Khôn Nhất Định! Bí tịch đã hoàn thành.")
        st.download_button("📥 TẢI BẢN DỊCH HOÀN HẢO", "\n\n".join(final_srt_blocks), file_name=f"Fixed_v65_{file.name}", use_container_width=True)
        st.balloons()

    except Exception as e:
        st.error(f"Sụp đổ bất ngờ: {e}")
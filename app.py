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
# GIAO DIỆN PHONG THÁI VÕ HIỆP TỐI GIẢN
# =========================================================
st.set_page_config(page_title="Donghua v67 - Vô Trung Sinh Hữu", page_icon="🔱", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    [data-testid="stSidebar"] { background-color: #161b22 !important; border-right: 1px solid #30363d; }
    .key-box { padding: 6px; border-radius: 6px; text-align: center; border: 1px solid #30363d; font-size: 0.75rem; margin-bottom: 5px; }
    .k-active { background: #238636; color: #aff5b4; }
    .k-busy { background: #1f6feb; color: #c2e0ff; }
    .k-cool { background: #9e6a03; color: #ffdf5d; }
    .k-dead { background: #da3633; color: #ffd1d1; }
    .w-box { padding: 8px; border-radius: 4px; border: 1px solid #30363d; font-size: 0.75rem; text-align: center; background: #010409; }
    .w-run { color: #58a6ff; border: 1px solid #58a6ff; }
    .w-retry { color: #d29922; border: 2px dashed #d29922; animation: blinker 1s linear infinite; }
    @keyframes blinker { 50% { opacity: 0; } }
    .w-done { color: #3fb950; border: 1px solid #3fb950; }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# QUẢN LÝ LINH LỰC
# =========================================================
RAW_KEYS = [os.getenv(f"GEMINI_KEY_{i}") for i in range(1, 21)]
VALID_KEYS = [k.strip() for k in RAW_KEYS if k and len(k.strip()) > 10]

if not VALID_KEYS:
    st.sidebar.error("🛑 Không tìm thấy linh thạch! Hãy nạp Key vào .env hoặc Secrets.")
    st.stop()

if 'key_manager' not in st.session_state:
    st.session_state.key_manager = {
        i: {"status": "ACTIVE", "in_use": False, "last_finished": datetime.now() - timedelta(seconds=60), "key": k} 
        for i, k in enumerate(VALID_KEYS)
    }

manager = st.session_state.key_manager
status_lock = threading.Lock()

def check_clean_vietnamese(text, expected_count):
    """Kính chiếu yêu: Chỉ cho phép tiếng Việt sạch và đủ mốc thời gian"""
    if not text or len(text.strip()) < 30: return False
    
    # Quét toàn bộ dải chữ Hán (giản thể, phồn thể, bộ thủ)
    if re.search(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', text):
        return False
    
    # Đếm mốc thời gian -->
    if text.count("-->") < expected_count:
        return False
        
    return True

def call_gemini(api_key, text_data, expected_count):
    try:
        client = genai.Client(api_key=api_key)
        safety = [{"category": c, "threshold": "BLOCK_NONE"} for c in [
            "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", 
            "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"
        ]]
        
        sys_prompt = (
            f"Bạn là một dịch giả võ hiệp cổ trang chuyên nghiệp.\n"
            f"NHIỆM VỤ: Dịch SRT sang tiếng Việt.\n"
            f"YÊU CẦU BẮT BUỘC:\n"
            f"1. Phải có đủ {expected_count} đoạn dịch (mỗi đoạn bắt đầu bằng số và mốc thời gian).\n"
            f"2. TUYỆT ĐỐI KHÔNG TRẢ VỀ CHỮ TRUNG QUỐC. Nếu không dịch được, hãy bỏ qua chữ đó nhưng phải giữ tiếng Việt.\n"
            f"3. Giữ nguyên timestamps chuẩn xác."
        )
        
        response = client.models.generate_content(
            model="gemini-3.1-pro-preview", 
            contents=f"{sys_prompt}\n\nNỘI DUNG:\n{text_data}",
            config=types.GenerateContentConfig(temperature=0.15, safety_settings=safety)
        )
        
        return response.text.strip() if response.text else ""
    except Exception as e:
        return f"ERR_SYSTEM: {str(e)}"

# =========================================================
# GIAO DIỆN SIDEBAR
# =========================================================
with st.sidebar:
    st.title("🔱 VÔ TRUNG SINH HỮU")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    b_size = st.number_input("Số đoạn/Lô", 10, 100, 50)
    c_time = st.number_input("Giây nghỉ/Key", 0, 60, 15)
    start = st.button("⚔️ KHAI TRẬN", use_container_width=True, type="primary")

col_left, col_right = st.columns([1, 3])
with col_left:
    st.caption("📡 Trạng thái Key")
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
# LÕI VẬN HÀNH
# =========================================================
if start and file:
    try:
        raw = file.getvalue().decode("utf-8-sig", errors="replace").strip()
        blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
        batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
        waves = [batches[i:i + 5] for i in range(0, len(batches), 5)]
        
        results = {}
        total_batches = len(batches)

        for wave_idx, wave_batches in enumerate(waves):
            num_tasks = len(wave_batches)
            w_info = {j: {"msg": "Chờ...", "style": ""} for j in range(5)}

            def worker(rel_idx, chunk_blocks):
                abs_idx = wave_idx * 5 + rel_idx
                expected_count = len(chunk_blocks)
                chunk_text = "\n\n".join(chunk_blocks)
                
                # VÒNG LẶP LUÂN HỒI: Chạy đến khi sạch tiếng Trung mới thôi
                attempt = 0
                while True:
                    attempt += 1
                    cur_k = None
                    # Tìm Key rảnh
                    with status_lock:
                        for i in range(len(VALID_KEYS)):
                            k = manager[i]
                            if k["status"] == "ACTIVE" and not k["in_use"] and (datetime.now() - k["last_finished"]).total_seconds() >= c_time:
                                cur_k = i; k["in_use"] = True; break
                    
                    if cur_k is None:
                        if not any(k["status"] == "ACTIVE" for k in manager.values()): return abs_idx, "FATAL"
                        w_info[rel_idx] = {"msg": "⏳ Đợi Key...", "style": "w-retry"}
                        time.sleep(2); continue

                    w_info[rel_idx] = {"msg": f"Key {cur_k+1} (Lần {attempt})", "style": "w-run"}
                    res_raw = call_gemini(manager[cur_k]["key"], chunk_text, expected_count)
                    
                    with status_lock:
                        manager[cur_k]["last_finished"] = datetime.now()
                        manager[cur_k]["in_use"] = False
                        
                        # KIỂM TRA CHẤT LƯỢNG
                        if check_clean_vietnamese(res_raw, expected_count):
                            w_info[rel_idx] = {"msg": "✅ Hoàn tất", "style": "w-done"}
                            return abs_idx, res_raw
                        else:
                            # Nếu lỗi 429/401 thì phế Key, nếu lỗi nội dung thì bắt dịch lại
                            if "429" in res_raw or "401" in res_raw:
                                manager[cur_k]["status"] = "DEAD"
                            
                            w_info[rel_idx] = {"msg": f"🔄 Lỗi/Tiếng Trung (Thử lại {attempt})", "style": "w-retry"}
                            time.sleep(1.5)
                            cur_k = None # Ép tìm Key khác

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
                    if res == "FATAL": st.error("🛑 Trận pháp sụp đổ! Hãy nạp thêm Gmail mới."); st.stop()
                    results[idx] = res

            p_bar.progress((wave_idx + 1) / len(waves))
            msg_box.info(f"Tiến độ: {min((wave_idx+1)*5, total_batches)}/{total_batches} lô đã luyện xong.")

        # HỢP NHẤT BÍ TỊCH
        final_srt = "\n\n".join([results[i] for i in range(total_batches)])
        st.success("🎉 Bí tịch v67 đã hoàn thành! Sạch bóng tiếng Trung.")
        st.download_button("📥 TẢI BẢN DỊCH TINH KHIẾT", final_srt, file_name=f"V67_Pure_{file.name}", use_container_width=True)
        st.balloons()

    except Exception as e:
        st.error(f"Sụp đổ bất ngờ: {e}")
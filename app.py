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
except ImportError:
    pass

# =========================================================
# GIAO DIỆN THANH MINH (ZEN DARK)
# =========================================================
st.set_page_config(page_title="Donghua Thanh Minh v64", page_icon="🗡️", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0f172a; color: #cbd5e1; }
    [data-testid="stSidebar"] { background-color: #1e293b !important; border-right: 1px solid #334155; }
    .key-box { padding: 8px; border-radius: 6px; text-align: center; border: 1px solid #334155; font-size: 0.75rem; margin-bottom: 5px; }
    .k-active { background: #064e3b; color: #4ade80; border-color: #22c55e; }
    .k-busy { background: #1e3a8a; color: #60a5fa; border-color: #3b82f6; }
    .k-cool { background: #451a03; color: #fbbf24; border-color: #d97706; }
    .k-dead { background: #450a0a; color: #f87171; border-color: #ef4444; }
    .w-box { padding: 6px; border-radius: 4px; border: 1px solid #334155; font-size: 0.75rem; text-align: center; background: #1e293b; min-height: 45px; }
    .w-run { color: #60a5fa; border-color: #3b82f6; border-style: solid; }
    .w-retry { color: #fbbf24; border-color: #fbbf24; border-style: dashed; animation: blink 1s infinite; }
    .w-done { color: #4ade80; border-color: #22c55e; }
    @keyframes blink { 50% { opacity: 0.5; } }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# QUẢN LÝ LINH LỰC
# =========================================================
RAW_KEYS = [os.getenv(f"GEMINI_KEY_{i}") for i in range(1, 21)]
VALID_KEYS = [k.strip() for k in RAW_KEYS if k and len(k.strip()) > 10]

if not VALID_KEYS:
    st.sidebar.error("🛑 Không tìm thấy linh thạch! Hãy nạp vào .env hoặc Secrets.")
    st.stop()

if 'key_manager' not in st.session_state:
    st.session_state.key_manager = {
        i: {
            "status": "ACTIVE", "in_use": False, 
            "last_finished": datetime.now() - timedelta(seconds=60),
            "key": k
        } for i, k in enumerate(VALID_KEYS)
    }

manager = st.session_state.key_manager
status_lock = threading.Lock()

def check_content_issue(text):
    """Kính chiếu yêu: Phát hiện chữ Trung Quốc và các lỗi rỗng"""
    if not text or len(text.strip()) < 10:
        return "Rỗng hoặc quá ngắn"
    
    # Regex mở rộng: Bao gồm cả chữ Hán phồn thể, giản thể và các bộ thủ
    chinese_pattern = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]')
    if chinese_pattern.search(text):
        return "Còn chữ Trung"
    
    return None

def call_gemini(api_key, text_data, expected_count):
    try:
        client = genai.Client(api_key=api_key)
        safety = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
        
        # Khẩu quyết tăng cường sự tập trung
        sys_prompt = (
            f"Bạn là chuyên gia dịch thuật phim kiếm hiệp. Dịch SRT sang tiếng Việt.\n"
            f"YÊU CẦU NGHIÊM NGẶT:\n"
            f"1. Dịch ĐỦ {expected_count} đoạn. Không gộp đoạn, không bỏ đoạn.\n"
            f"2. CHỈ trả về tiếng Việt. Tuyệt đối không giữ lại chữ Trung Quốc.\n"
            f"3. Xưng hô kiểu cổ trang (Ta, ngươi, lão phu, bổn tọa...).\n"
            f"4. Giữ nguyên định dạng SRT (Số thứ tự, mốc thời gian)."
        )
        
        response = client.models.generate_content(
            model="gemini-3-flash-preview", 
            contents=f"{sys_prompt}\n\nNỘI DUNG CẦN DỊCH:\n{text_data}",
            config=types.GenerateContentConfig(temperature=0.2, safety_settings=safety)
        )
        
        res_text = response.text.strip() if response.text else ""
        
        # Kiểm tra chân tâm (Số đoạn)
        res_blocks = [b for b in re.split(r'\n\s*\n', res_text) if b.strip()]
        if abs(len(res_blocks) - expected_count) > 2: # Cho phép sai số lệch 1-2 block do regex
             return f"ERR: Sai số đoạn ({len(res_blocks)}/{expected_count})"
        
        # Kiểm tra tạp chất (Chữ Trung)
        issue = check_content_issue(res_text)
        if issue: return f"ERR: {issue}"
             
        return res_text
    except Exception as e:
        return f"ERR_SYSTEM: {str(e)}"

# =========================================================
# GIAO DIỆN & SIDEBAR
# =========================================================
with st.sidebar:
    st.title("🗡️ THANH MINH v64")
    file = st.file_uploader("📜 Nạp bí tịch (.srt)", type=["srt"])
    b_size = st.number_input("Số đoạn/Lô", 10, 150, 70)
    c_time = st.number_input("Giây nghỉ/Key", 0, 120, 15)
    start = st.button("⚔️ KHAI TRẬN", use_container_width=True, type="primary")

col_k, col_w = st.columns([1, 2.5])
with col_k:
    st.caption("📡 Trạng thái Key")
    k_placeholders = [st.empty() for _ in range(len(VALID_KEYS))]

with col_w:
    st.caption("🌊 Luồng xử lý Workers")
    w_cols = st.columns(5)
    w_placeholders = [w_cols[i].empty() for i in range(5)]
    st.divider()
    progress_info = st.empty()
    p_bar = st.progress(0)

def refresh_ui():
    now = datetime.now()
    for i in range(len(VALID_KEYS)):
        k = manager[i]
        diff = (now - k["last_finished"]).total_seconds()
        if k["status"] == "DEAD": cls, txt = "k-dead", "💀 HỎNG"
        elif k["in_use"]: cls, txt = "k-busy", "⚔️ DỊCH"
        elif diff < c_time: cls, txt = "k-cool", f"🧘 {int(c_time-diff)}s"
        else: cls, txt = "k-active", "✅ SẴN SÀNG"
        k_placeholders[i].markdown(f"<div class='key-box {cls}'><b>Key {i+1}</b>: {txt}</div>", unsafe_allow_html=True)

refresh_ui()

# =========================================================
# LÕI XỬ LÝ - THANH MINH TRẬN
# =========================================================
if start and file:
    try:
        raw = file.getvalue().decode("utf-8-sig", errors="replace").strip()
        blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
        batches = [blocks[i:i + b_size] for i in range(0, len(blocks), b_size)]
        waves = [batches[i:i + 5] for i in range(0, len(batches), 5)]
        
        results = {}
        for wave_idx, wave_batches in enumerate(waves):
            num_tasks = len(wave_batches)
            w_status = {j: {"msg": "Chờ...", "style": ""} for j in range(5)}

            def worker(t_idx, chunk_blocks):
                expected = len(chunk_blocks)
                chunk_text = "\n\n".join(chunk_blocks)
                retry_count = 0
                
                while retry_count < 3: # Cho phép thử lại 3 lần cho mỗi lô
                    cur_k = None
                    with status_lock:
                        for i in range(len(VALID_KEYS)):
                            k = manager[i]
                            if k["status"] == "ACTIVE" and not k["in_use"] and (datetime.now() - k["last_finished"]).total_seconds() >= c_time:
                                cur_k = i; k["in_use"] = True; break
                    
                    if cur_k is None:
                        if not any(k["status"] == "ACTIVE" for k in manager.values()): return t_idx, "FATAL"
                        w_status[t_idx] = {"msg": "⏳ Đợi Key...", "style": ""}
                        time.sleep(2); continue

                    w_status[t_idx] = {"msg": f"⚔️ Key {cur_k+1}...", "style": "w-run"}
                    res = call_gemini(manager[cur_k]["key"], chunk_text, expected)
                    
                    with status_lock:
                        manager[cur_k]["last_finished"] = datetime.now()
                        manager[cur_k]["in_use"] = False
                        
                        if "ERR" not in res:
                            w_status[t_idx] = {"msg": "✅ Xong", "style": "w-done"}
                            return t_idx, res
                        else:
                            # Nếu lỗi hệ thống nặng (429, 401) mới giết Key
                            if "ERR_SYSTEM" in res and ("429" in res or "401" in res):
                                manager[cur_k]["status"] = "DEAD"
                            
                            retry_count += 1
                            w_status[t_idx] = {"msg": f"🔄 Lần {retry_count}...", "style": "w-retry"}
                            time.sleep(1)
                            cur_k = None
                return t_idx, "FAILED_AFTER_RETRIES"

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(worker, j, wave_batches[j]) for j in range(num_tasks)]
                while not all(f.done() for f in futures):
                    refresh_ui()
                    cols = monitor_container.columns(5) if 'monitor_container' in locals() else st.columns(5)
                    for j in range(5):
                        s = w_status[j]
                        w_placeholders[j].markdown(f"<div class='w-box {s['style']}'>{s['msg']}</div>", unsafe_allow_html=True)
                    time.sleep(0.5)
                
                for f in futures:
                    idx, res = f.result()
                    if res == "FATAL": st.error("🛑 Trận pháp gãy!"); st.stop()
                    if res == "FAILED_AFTER_RETRIES":
                         st.warning(f"⚠️ Lô {wave_idx*5 + idx + 1} không thể làm sạch sau 3 lần thử. Bỏ qua.")
                         res = ""
                    results[wave_idx * 5 + idx] = res

            p_bar.progress((wave_idx + 1) / len(waves))
            progress_info.info(f"Đã luyện xong đợt {wave_idx+1}/{len(waves)}")

        st.success("🎉 Thanh Minh Trận hoàn tất!")
        final_srt = "\n\n".join([results[i] for i in range(len(batches)) if i in results])
        st.download_button("📥 TẢI BẢN DỊCH SẠCH", final_srt, file_name=f"Fixed_{file.name}", use_container_width=True)
    except Exception as e:
        st.error(f"Sụp đổ: {e}")
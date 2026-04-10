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

# --- PHÁP BẢO KHAI MÔN ĐỘC FILE .ENV ---
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# =========================================================
# GIAO DIỆN TỐI GIẢN (ZEN STYLE)
# =========================================================
st.set_page_config(page_title="Donghua Truy Nguyên v62", page_icon="🔍", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0f172a; color: #cbd5e1; }
    [data-testid="stSidebar"] { background-color: #1e293b !important; border-right: 1px solid #334155; }
    .key-box {
        padding: 6px; border-radius: 6px; text-align: center;
        border: 1px solid #334155; font-size: 0.75rem; margin-bottom: 5px;
    }
    .k-active { background: #064e3b; color: #4ade80; border-color: #22c55e; }
    .k-busy { background: #1e3a8a; color: #60a5fa; border-color: #3b82f6; }
    .k-cool { background: #451a03; color: #fbbf24; border-color: #d97706; }
    .k-dead { background: #450a0a; color: #f87171; border-color: #ef4444; }
    .w-box {
        padding: 5px; border-radius: 4px; border: 1px solid #334155;
        font-size: 0.75rem; text-align: center; background: #1e293b;
    }
    .w-run { color: #60a5fa; border-color: #3b82f6; }
    .w-done { color: #4ade80; border-color: #22c55e; }
    h2, h3 { color: #38bdf8 !important; }
    </style>
    """, unsafe_allow_html=True)

# =========================================================
# QUẢN LÝ LINH LỰC
# =========================================================
RAW_KEYS = [os.getenv(f"GEMINI_KEY_{i}") for i in range(1, 21)]
VALID_KEYS = [k.strip() for k in RAW_KEYS if k and len(k.strip()) > 10]

if not VALID_KEYS:
    st.sidebar.error("🛑 Thiếu linh thạch trong .env!")
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

def call_gemini(api_key, text_data):
    try:
        client = genai.Client(api_key=api_key)
        # CẬP NHẬT KHẨU QUYẾT: NGHIÊM CẤM THIẾU ĐOẠN
        sys_prompt = (
            "Dịch SRT sang tiếng Việt võ hiệp chuyên nghiệp. "
            "QUAN TRỌNG: Dịch đầy đủ TẤT CẢ các đoạn. KHÔNG ĐƯỢC bỏ sót bất kỳ số thứ tự nào. "
            "Số lượng đoạn kết quả phải bằng chính xác số lượng đoạn đầu vào. Giữ nguyên timestamps.Chỉ dịch nội dung không tự ý thêm bất cứ gì"
        )
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-preview", 
            contents=f"{sys_prompt}\n\nNỘI DUNG CẦN DỊCH:\n{text_data}",
            config=types.GenerateContentConfig(temperature=0.2)
        )
        return response.text.strip() if response.text else "EMPTY"
    except Exception as e:
        return f"ERR: {str(e)}"

# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:
    st.title("🔍 TRUY NGUYÊN")
    file = st.file_uploader("📜 Nạp file .srt", type=["srt"])
    b_size = st.number_input("Số đoạn/Key", 10, 150, 70)
    c_time = st.number_input("Giây nghỉ/Key", 0, 120, 15)
    start = st.button("⚔️ KHỞI CHẠY", use_container_width=True, type="primary")

# =========================================================
# GIAO DIỆN CHÍNH
# =========================================================
col_k, col_w = st.columns([1, 2])

with col_k:
    st.caption("📡 Trạng thái Key")
    k_placeholders = [st.empty() for _ in range(len(VALID_KEYS))]

with col_w:
    st.caption("🌊 Tiến trình (Workers)")
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
        k_placeholders[i].markdown(f"<div class='key-box {cls}'><b>#{i+1}</b> {txt}</div>", unsafe_allow_html=True)

refresh_ui()

# =========================================================
# LÕI XỬ LÝ - TRUY NGUYÊN
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
            w_status = {j: "Chờ..." for j in range(5)}

            def worker(t_idx, chunk):
                while True:
                    cur_k = None
                    with status_lock:
                        for i in range(len(VALID_KEYS)):
                            k = manager[i]
                            if k["status"] == "ACTIVE" and not k["in_use"] and (datetime.now() - k["last_finished"]).total_seconds() >= c_time:
                                cur_k = i; k["in_use"] = True; break
                    
                    if cur_k is None:
                        if not any(k["status"] == "ACTIVE" for k in manager.values()): return t_idx, "FATAL"
                        w_status[t_idx] = "Đợi rảnh..."
                        time.sleep(2); continue

                    w_status[t_idx] = f"Key {cur_k+1}..."
                    res = call_gemini(manager[cur_k]["key"], chunk)
                    
                    with status_lock:
                        manager[cur_k]["last_finished"] = datetime.now(); manager[cur_k]["in_use"] = False
                        if "ERR:" not in res and res != "EMPTY":
                            w_status[t_idx] = "✅ Xong"
                            return t_idx, res
                        else:
                            # Nếu lỗi hoặc rỗng, khai tử key đó
                            manager[cur_k]["status"] = "DEAD"
                            cur_k = None # Lặp lại để tìm key khác

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(worker, j, "\n\n".join(wave_batches[j])) for j in range(num_tasks)]
                while not all(f.done() for f in futures):
                    refresh_ui()
                    for j in range(5):
                        st_txt = w_status[j]
                        style = "w-run" if "Key" in st_txt else ("w-done" if "✅" in st_txt else "")
                        w_placeholders[j].markdown(f"<div class='w-box {style}'>{st_txt}</div>", unsafe_allow_html=True)
                    time.sleep(0.5)
                
                for f in futures:
                    idx, res = f.result()
                    if res == "FATAL": st.error("🛑 Trận pháp gãy! Hết linh lực."); st.stop()
                    # Lưu chính xác vị trí mảnh ghép
                    results[wave_idx * 5 + idx] = res

            p_val = (wave_idx + 1) / len(waves)
            p_bar.progress(p_val)
            progress_info.write(f"Đã luyện xong đợt {wave_idx+1}/{len(waves)}")

        # --- BƯỚC KIỂM TRA CHÂN TÂM ---
        if len(results) < len(batches):
            st.warning(f"⚠️ Cảnh báo: Chỉ tìm thấy {len(results)}/{len(batches)} mảnh ghép. Một số đoạn có thể đã bị thất lạc!")
        
        final_srt = "\n\n".join([results[i] for i in range(len(batches)) if i in results])
        
        st.success("🎉 Trận pháp hoàn tất!")
        st.download_button("📥 TẢI BẢN DỊCH (KIỂM TRA LẠI)", final_srt, file_name=f"Fixed_{file.name}", use_container_width=True)
        st.balloons()
        
    except Exception as e:
        st.error(f"Sụp đổ: {e}")
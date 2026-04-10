import sys
import os
import streamlit as st
from google import genai
from google.genai import types
import time
import re
import traceback
from concurrent.futures import ThreadPoolExecutor
import threading
from datetime import datetime, timedelta

# =========================================================
# BỨC TƯỜNG BẢO VỆ UTF-8 & GIAO DIỆN
# =========================================================
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

st.set_page_config(page_title="Donghua Bất Khuất v55", page_icon="🛡️", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0b0d11; color: #e0e0e0; }
    .key-card { padding: 10px; border-radius: 8px; text-align: center; margin-bottom: 10px; border: 1px solid #334155; }
    .key-active { background: #064e3b; color: #6ee7b7; border-color: #10b981; }
    .key-busy { background: #1e3a8a; color: #93c5fd; border-color: #3b82f6; }
    .key-cooldown { background: #78350f; color: #fbbf24; border-color: #d97706; }
    .key-dead { background: #450a0a; color: #fca5a5; border-color: #ef4444; text-decoration: line-through; }
    .worker-box { padding: 12px; border-radius: 8px; text-align: center; font-size: 0.85em; min-height: 100px; }
    .status-running { background: #1e3a8a; border: 1px solid #3b82f6; color: #93c5fd; }
    .status-wait { background: #334155; border: 1px dashed #94a3b8; color: #cbd5e1; }
    .status-done { background: #022c22; border: 1px solid #059669; color: #6ee7b7; }
    .countdown-box { padding: 15px; background: #111827; border: 1px dashed #fbbf24; border-radius: 8px; color: #fcd34d; text-align: center; }
    h1 { color: #10b981 !important; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

st.markdown("<h1>🛡️ V55.0 - BẤT KHUẤT MẬT THẤT (SECURE)</h1>", unsafe_allow_html=True)

# =========================================================
# TRIỆU HỒI LINH THẠCH TỪ MẬT THẤT (OS GETENV)
# =========================================================
RAW_KEYS = [
    os.getenv("GEMINI_KEY_1"),
    os.getenv("GEMINI_KEY_2"),
    os.getenv("GEMINI_KEY_3"),
    os.getenv("GEMINI_KEY_4"),
    os.getenv("GEMINI_KEY_5")
]
# Chỉ lấy những Key thực sự tồn tại
VALID_KEYS = [k for k in RAW_KEYS if k and k.strip()]

if not VALID_KEYS:
    st.error("🛑 CHƯA NẠP LINH THẠCH! Hãy kiểm tra GitHub Secrets hoặc Streamlit Secrets.")
    st.info("Đại hiệp cần nạp các biến: GEMINI_KEY_1, GEMINI_KEY_2... vào phần Secrets.")
    st.stop()

# =========================================================
# QUẢN LÝ TRẠNG THÁI TRẬN PHÁP
# =========================================================
status_lock = threading.Lock()

if 'key_manager' not in st.session_state:
    st.session_state.key_manager = {
        i: {
            "status": "ACTIVE", 
            "in_use": False, 
            "last_finished": datetime.now() - timedelta(seconds=20),
            "key": k
        } for i, k in enumerate(VALID_KEYS)
    }

manager = st.session_state.key_manager

def call_gemini(api_key, text_data):
    try:
        client = genai.Client(api_key=api_key)
        sys_prompt = "Dịch SRT sang tiếng Việt võ hiệp cổ trang. Xưng hô chuẩn xác. Giữ nguyên timestamps."
        response = client.models.generate_content(
            model="gemini-3-flash-preview", 
            contents=f"{sys_prompt}\n\n{text_data}",
            config=types.GenerateContentConfig(temperature=0.2)
        )
        return response.text.strip() if response.text else "EMPTY"
    except Exception as e:
        return f"ERR: {str(e)}"

# --- GIAO DIỆN REAL-TIME ---
st.markdown(f"### 📡 Linh lực hiện có: {len(VALID_KEYS)} viên")
key_cols_ui = st.columns(len(VALID_KEYS))
placeholders = [key_cols_ui[i].empty() for i in range(len(VALID_KEYS))]

def render_realtime_keys():
    now = datetime.now()
    for i in range(len(VALID_KEYS)):
        k = manager.get(i, {"status": "DEAD"})
        diff = (now - k.get("last_finished", now)).total_seconds()
        
        if k["status"] == "DEAD": cls, txt = "key-dead", "❌ HỎNG"
        elif k.get("in_use"): cls, txt = "key-busy", "⚔️ LÂM TRẬN"
        elif diff < 15: cls, txt = "key-cooldown", f"🧘 HỒI SỨC ({int(15-diff)}s)"
        else: cls, txt = "key-active", "✅ SẴN SÀNG"
            
        placeholders[i].markdown(f"<div class='key-card {cls}'><b>Key #{i+1}</b><br>{txt}</div>", unsafe_allow_html=True)

render_realtime_keys()

# --- XỬ LÝ FILE ---
file = st.file_uploader("Tải file .srt lên", type=["srt"])

if file:
    if st.button("KÍCH HOẠT BẤT KHUẤT MẬT THẤT ⚔️"):
        try:
            raw_content = file.getvalue().decode("utf-8-sig", errors="replace").strip()
            blocks = [b.strip() for b in re.split(r'\n\s*\n', raw_content) if b.strip()]
            
            # --- CHIẾN THUẬT BATCH 70 ---
            batch_size = 70 
            batches = [blocks[i:i + batch_size] for i in range(0, len(blocks), batch_size)]
            waves = [batches[i:i + 5] for i in range(0, len(batches), 5)]
            
            final_results_map = {}
            progress_bar = st.progress(0.0)
            wave_info = st.empty()
            monitor_container = st.empty()
            timer_box = st.empty()

            for wave_idx, wave_batches in enumerate(waves):
                num_actual_tasks = len(wave_batches)
                display_status = {j: {"status": "idle", "msg": "Chờ lệnh"} for j in range(5)}
                wave_info.markdown(f"#### 🌊 Đợt sóng {wave_idx+1}/{len(waves)}")

                def worker(task_idx, text_chunk, local_manager):
                    while True:
                        current_key_idx = None
                        now = datetime.now()
                        
                        with status_lock:
                            for i in range(len(VALID_KEYS)):
                                k = local_manager.get(i)
                                # ĐIỀU KIỆN: SỐNG + KHÔNG BẬN + NGHỈ ĐỦ 15S
                                if k and k["status"] == "ACTIVE" and not k["in_use"]:
                                    if (now - k["last_finished"]).total_seconds() >= 15:
                                        current_key_idx = i
                                        local_manager[current_key_idx]["in_use"] = True
                                        break
                        
                        if current_key_idx is None:
                            any_alive = any(k["status"] == "ACTIVE" for k in local_manager.values())
                            if not any_alive: return task_idx, "FATAL_ERROR"
                            display_status[task_idx] = {"status": "wait", "msg": "⏳ Đợi Key hồi sức..."}
                            time.sleep(2)
                            continue

                        display_status[task_idx] = {"status": "running", "msg": f"Key #{current_key_idx+1} xuất chiêu..."}
                        res = call_gemini(local_manager[current_key_idx]["key"], text_chunk)
                        
                        with status_lock:
                            local_manager[current_key_idx]["last_finished"] = datetime.now()
                            local_manager[current_key_idx]["in_use"] = False
                            
                            if "ERR:" not in res:
                                display_status[task_idx] = {"status": "done", "msg": "✅ Xong!"}
                                return task_idx, res
                            else:
                                local_manager[current_key_idx]["status"] = "DEAD"
                                display_status[task_idx] = {"status": "wait", "msg": "❌ HỎNG!"}
                                time.sleep(1)
                                current_key_idx = None

                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = [executor.submit(worker, j, "\n\n".join(wave_batches[j]), manager) for j in range(num_actual_tasks)]
                    while True:
                        render_realtime_keys()
                        done_count = 0
                        cols = monitor_container.columns(5)
                        for j in range(5):
                            s = display_status[j]
                            cols[j].markdown(f"<div class='worker-box status-{s['status']}'>🔮 <b>Vị trí {j+1}</b><br>{s['msg']}</div>", unsafe_allow_html=True)
                            if s['status'] in ["done", "idle"]: done_count += 1
                        
                        if any(f.done() and f.result() == "FATAL_ERROR" for f in futures):
                            st.error("🛑 TẤT CẢ LINH THẠCH ĐÃ CẠN KIỆT! Hãy thay Gmail mới.")
                            st.stop()
                        if done_count == 5: break
                        time.sleep(0.5)
                    
                    for future in futures:
                        t_idx, res = future.result()
                        final_results_map[wave_idx * 5 + t_idx] = res

                progress_bar.progress((wave_idx + 1) / len(waves))
                if wave_idx < len(waves) - 1:
                    for i in range(15, 0, -1):
                        render_realtime_keys()
                        timer_box.markdown(f"<div class='countdown-box'>⏳ Đợt {wave_idx+1} hoàn tất. Nghỉ đợt {i}s...</div>", unsafe_allow_html=True)
                        time.sleep(1)
                    timer_box.empty()

            ordered = [final_results_map[i] for i in range(len(batches)) if i in final_results_map]
            st.download_button("📥 TẢI PHỤ ĐỀ V55", "\n\n".join(ordered), file_name=f"V55_Secure_{file.name}")
            st.balloons()

        except Exception as e:
            st.error(f"Sụp đổ: {e}")
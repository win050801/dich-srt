import sys
# =========================================================
# BỨC TƯỜNG BẢO VỆ UTF-8
# =========================================================
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

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
# NẠP 5 VIÊN LINH THẠCH GEMINI MỚI VÀO ĐÂY
# =========================================================
LIST_API_KEYS = [
    "AIzaSyDRIUktlc_jqlgMxZnQf9SOzuQ7ZxlMrrw",
    "AIzaSyDyFADpldbryZX9llfA7A5qnQy8ucEdDIY",
    "AIzaSyCdhM-5X8Jr47XYH6Akx8Q9QKIuXRmW6aE",
    "AIzaSyDxexUAUExQms_j1sy1ykc66LNpo6TYHgE",
    "AIzaSyBE1kXb8SZZvH9VVXqZMVCJOu5Xye1F7gk"
]
# =========================================================

st.set_page_config(page_title="Donghua Vạn Biến v52", page_icon="🛑", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0b0d11; color: #e0e0e0; }
    .key-card { padding: 10px; border-radius: 8px; text-align: center; margin-bottom: 10px; border: 1px solid #334155; }
    .key-active { background: #064e3b; color: #6ee7b7; border-color: #10b981; }
    .key-busy { background: #1e3a8a; color: #93c5fd; border-color: #3b82f6; }
    .key-dead { background: #450a0a; color: #fca5a5; border-color: #ef4444; text-decoration: line-through; }
    .worker-box { padding: 12px; border-radius: 8px; text-align: center; font-size: 0.85em; min-height: 100px; }
    .status-running { background: #1e3a8a; border: 1px solid #3b82f6; color: #93c5fd; }
    .status-wait { background: #334155; border: 1px dashed #94a3b8; color: #cbd5e1; }
    .status-done { background: #022c22; border: 1px solid #059669; color: #6ee7b7; }
    .status-fatal { background: #7f1d1d; border: 2px solid #ef4444; color: #fecaca; font-weight: bold; }
    .countdown-box { padding: 15px; background: #111827; border: 1px dashed #fbbf24; border-radius: 8px; color: #fcd34d; text-align: center; }
    h1 { color: #ef4444 !important; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

st.markdown("<h1>🛑 VẠN BIẾN QUY NHẤT - TỔNG LỆNH NGẮT (V52)</h1>", unsafe_allow_html=True)

status_lock = threading.Lock()

if 'key_manager' not in st.session_state:
    st.session_state.key_manager = {
        i: {
            "status": "ACTIVE", 
            "errors": 0, 
            "in_use": False, 
            "is_rate_limited": False,
            "call_history": [], 
            "key": k.strip()
        } 
        for i, k in enumerate(LIST_API_KEYS) if "..." not in k and k.strip()
    }

manager = st.session_state.key_manager

def call_gemini(api_key, text_data):
    try:
        client = genai.Client(api_key=api_key)
        sys_prompt = (
        "Bạn là đại sư dịch thuật Donghua chuyên nghiệp. "
        "Dịch các đoạn SRT sau sang tiếng Việt phong cách VÕ HIỆP, CỔ TRANG.\n"
        "XƯNG HÔ: Ta, Ngươi, Lão phu, Tiểu tử, Bổn tọa, Tiền bối, Huynh, Đệ, Muội...\n"
        "VĂN PHONG: Hào sảng, trau chuốt, tự nhiên cho thuyết minh. GIỮ NGUYÊN timestamps.\n"
        "QUY TẮC: KHÔNG gộp/tách đoạn. Chỉ trả về nội dung SRT."
        )
        response = client.models.generate_content(
            model="gemini-3-flash-preview", 
            contents=f"{sys_prompt}\n\n{text_data}",
            config=types.GenerateContentConfig(temperature=0.2)
        )
        return response.text.strip() if response.text else "EMPTY"
    except Exception as e:
        return f"ERR: {str(e)}"

def check_rate_limit_local(local_manager, key_idx):
    now = datetime.now()
    one_minute_ago = now - timedelta(seconds=60)
    with status_lock:
        k = local_manager[key_idx]
        k["call_history"] = [t for t in k["call_history"] if t > one_minute_ago]
        if len(k["call_history"]) >= 5:
            k["is_rate_limited"] = True
            return False
        k["call_history"].append(now)
        k["is_rate_limited"] = False
        return True

# --- BẢNG TRẠNG THÁI REAL-TIME ---
st.markdown("### 📡 Trạng Thái Ngũ Hành Linh Thạch")
key_placeholders = st.columns(5)
placeholders = [key_placeholders[i].empty() for i in range(5)]

def render_realtime_keys():
    for i in range(5):
        k = manager.get(i, {"status": "DEAD"})
        recent_calls = len([t for t in k.get("call_history", []) if t > datetime.now() - timedelta(seconds=60)])
        if k["status"] == "DEAD": cls, txt = "key-dead", "❌ ĐÃ HỎNG"
        elif k["is_rate_limited"]: cls, txt = "key-limit", "🧘 TỊNH TÂM"
        elif k["in_use"]: cls, txt = "key-busy", "⚔️ LÂM TRẬN"
        else: cls, txt = "key-active", "✅ RẢNH"
        placeholders[i].markdown(f"<div class='key-card {cls}'><b>Key #{i+1}</b><br>{txt}<br><small>Hạn mức: {recent_calls}/5</small></div>", unsafe_allow_html=True)

render_realtime_keys()

file = st.file_uploader("Tải file .srt lên", type=["srt"])

if file:
    if st.button("KÍCH HOẠT TRẬN PHÁP V52 ⚔️"):
        try:
            raw_content = file.getvalue().decode("utf-8-sig", errors="replace").strip()
            blocks = [b.strip() for b in re.split(r'\n\s*\n', raw_content) if b.strip()]
            
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
                        with status_lock:
                            # Tìm Key sống và không bận
                            for i in range(5):
                                k = local_manager.get(i)
                                if k and k["status"] == "ACTIVE" and not k["in_use"]:
                                    current_key_idx = i
                                    local_manager[current_key_idx]["in_use"] = True
                                    break
                        
                        if current_key_idx is None:
                            # KIỂM TRA SINH TỬ: Còn bất kỳ ai sống không?
                            any_alive = any(k["status"] == "ACTIVE" for k in local_manager.values())
                            if not any_alive:
                                display_status[task_idx] = {"status": "fatal", "msg": "❌ HẾT KEY!"}
                                return task_idx, "FATAL_ERROR"
                            
                            display_status[task_idx] = {"status": "wait", "msg": "⏳ Chờ Key rảnh..."}
                            time.sleep(3)
                            continue

                        if not check_rate_limit_local(local_manager, current_key_idx):
                            with status_lock: local_manager[current_key_idx]["in_use"] = False
                            display_status[task_idx] = {"status": "wait", "msg": "🧘 Nghỉ dưỡng..."}
                            time.sleep(5)
                            current_key_idx = None
                            continue

                        display_status[task_idx] = {"status": "running", "msg": f"Key #{current_key_idx+1} dịch..."}
                        res = call_gemini(local_manager[current_key_idx]["key"], text_chunk)
                        
                        with status_lock:
                            local_manager[current_key_idx]["in_use"] = False
                            if "ERR:" not in res:
                                display_status[task_idx] = {"status": "done", "msg": "✅ Hoàn tất!"}
                                return task_idx, res
                            else:
                                # LỖI 1 LẦN -> KHAI TỬ LUÔN
                                local_manager[current_key_idx]["status"] = "DEAD"
                                display_status[task_idx] = {"status": "wait", "msg": f"❌ Key #{current_key_idx+1} HỎNG!"}
                                time.sleep(2)
                                current_key_idx = None # Quay lại tìm người tiếp theo

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
                        
                        # KIỂM TRA LỆNH NGẮT TỪ WORKER
                        if any(f.done() and f.result() == "FATAL_ERROR" for f in futures):
                            st.error("🛑 CẢNH BÁO TỐI CAO: Tất cả 5 linh thạch đã cạn kiệt năng lượng hoặc bị Google phong ấn. Trận pháp buộc phải dừng lại để bảo toàn requests!")
                            st.warning("Lời khuyên: Đại hiệp hãy thay 5 Key mới (Gmail mới) và khởi động lại.")
                            st.stop() # DỪNG TOÀN BỘ APP TẠI ĐÂY

                        if done_count == 5: break
                        time.sleep(0.5)
                    
                    for future in futures:
                        t_idx, res = future.result()
                        final_results_map[wave_idx * 5 + t_idx] = res

                progress_bar.progress((wave_idx + 1) / len(waves))
                if wave_idx < len(waves) - 1:
                    for i in range(20, 0, -1):
                        render_realtime_keys()
                        timer_box.markdown(f"<div class='countdown-box'>⏳ Nghỉ dưỡng sức đợt {wave_idx+1}. Còn {i} giây...</div>", unsafe_allow_html=True)
                        time.sleep(1)
                    timer_box.empty()

            ordered = [final_results_map[i] for i in range(len(batches)) if i in final_results_map]
            st.download_button("📥 TẢI PHỤ ĐỀ V52", "\n\n".join(ordered), file_name=f"V52_Final_{file.name}")
            st.balloons()
            render_realtime_keys()

        except Exception as e:
            st.error(f"Sụp đổ: {e}")
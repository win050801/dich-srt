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

# =========================================================
# NẠP 5 VIÊN LINH THẠCH GEMINI VÀO ĐÂY
# =========================================================
LIST_API_KEYS = [
    "AIzaSyCTpvM7EmyXiJ93PKMHDNDK_rDiR33pdHI",
    "AIzaSyDa3R-P4ZoTEJqKGhAolR0gKoR29fS9fjw",
    "AIzaSyBADzpSc2Gv7q6ZroUVBcefVhONbVpGUJo",
    "AIzaSyCopyWAn_dGN-QU1C9NWwiiI4NpsNkZq0I",
    "AIzaSyALXMyBw1Noob3CJCHRar67KyEA51mv9zk"
]
# =========================================================

st.set_page_config(page_title="Donghua Đại Phách v43", page_icon="⚔️", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0b0d11; color: #e0e0e0; }
    .wave-box { padding: 15px; background: #1e293b; border-left: 5px solid #3b82f6; border-radius: 8px; margin-bottom: 15px; }
    .worker-box { padding: 12px; border-radius: 8px; text-align: center; font-size: 0.85em; min-height: 100px; margin-bottom: 10px; }
    .status-running { background: #1e3a8a; border: 1px solid #3b82f6; color: #93c5fd; }
    .status-done { background: #064e3b; border: 1px solid #10b981; color: #6ee7b7; }
    .status-idle { background: #334155; border: 1px dashed #64748b; color: #94a3b8; opacity: 0.5; }
    .status-warning { background: #78350f; border: 1px solid #f59e0b; color: #fcd34d; }
    .status-dead { background: #450a0a; border: 1px solid #ef4444; color: #fca5a5; font-weight: bold; }
    .countdown-box { padding: 15px; background: #1f2937; border: 1px dashed #fbbf24; border-radius: 8px; color: #fcd34d; text-align: center; margin: 20px 0; }
    h1 { color: #60a5fa !important; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

st.markdown("<h1>⚔️ ĐẠI PHÁCH KỲ MÔN - THAY KEY (V43)</h1>", unsafe_allow_html=True)

def call_gemini(api_key, text_data):
    try:
        client = genai.Client(api_key=api_key)
        sys_prompt = (
        "Bạn là một đại sư dịch thuật phim cổ trang Trung Quốc. "
        "Hãy dịch các đoạn SRT sau sang tiếng Việt phong cách VÕ HIỆP/TIÊN HIỆP.\n\n"
        "QUY TẮC:\n"
        "- Xưng hô: Ta, Ngươi, Huynh, Đệ, Muội, Lão phu, Tiểu tử, Bổn tọa, Tiền bối, Vãn bối...\n"
        "- Văn phong: Hào sảng, trau chuốt, dễ đọc cho Voice-over.\n"
        "- Kỹ thuật: GIỮ NGUYÊN timestamps. KHÔNG gộp/tách đoạn.\n"
        "- Chỉ trả về nội dung SRT."
    )
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-preview", 
            contents=f"{sys_prompt}\n\nNỘI DUNG SRT:\n{text_data}",
            config=types.GenerateContentConfig(temperature=0.2)
        )
        return response.text.strip() if response.text else "EMPTY"
    except Exception as e:
        return f"ERR: {str(e)}"

def countdown_timer(seconds, placeholder):
    for i in range(seconds, 0, -1):
        placeholder.markdown(f"<div class='countdown-box'>⏳ Thu hồi công lực: {i} giây...</div>", unsafe_allow_html=True)
        time.sleep(1)
    placeholder.empty()

file = st.file_uploader("Tải file .srt lên", type=["srt"])
valid_keys = [k.strip() for k in LIST_API_KEYS if "..." not in k and k.strip()]

if file:
    if len(valid_keys) < 5:
        st.error("❌ Đại hiệp hãy điền đủ 5 Key vào mã nguồn!")
    elif st.button("KHỞI ĐỘNG ĐẠI PHÁCH TRẬN ⚔️"):
        try:
            start_time = time.time()
            raw_content = file.getvalue().decode("utf-8-sig", errors="replace").replace('\r\n', '\n').strip()
            blocks = [b.strip() for b in re.split(r'\n\s*\n', raw_content) if b.strip()]
            
            batch_size = 40
            batches = [blocks[i:i + batch_size] for i in range(0, len(blocks), batch_size)]
            waves = [batches[i:i + 5] for i in range(0, len(batches), 5)]
            total_waves = len(waves)
            
            final_results_map = {}
            progress_bar = st.progress(0.0)
            wave_info = st.empty()
            monitor_container = st.empty()
            timer_box = st.empty()

            for wave_idx, wave_batches in enumerate(waves):
                num_actual_tasks = len(wave_batches)
                # display_status: lưu thông tin hiển thị của 5 slot Key
                display_status = {j: {"status": "idle", "msg": "Đang nghỉ", "key_idx": j} for j in range(5)}
                
                wave_info.markdown(f"<div class='wave-box'>🌊 <b>ĐỢT SÓNG {wave_idx+1}/{total_waves}</b><br>Đang điều động linh thạch ứng biến...</div>", unsafe_allow_html=True)

                def worker(task_idx, text_chunk):
                    """
                    task_idx: index của đoạn trong đợt sóng (0-4)
                    text_chunk: nội dung cần dịch
                    """
                    # Bắt đầu với Key tương ứng slot
                    current_key_idx = task_idx 
                    total_errors_this_task = 0
                    
                    while True:
                        key_to_use = valid_keys[current_key_idx]
                        display_status[task_idx] = {
                            "status": "running", 
                            "msg": f"Key #{current_key_idx+1}<br>Đang dịch...",
                            "key_idx": current_key_idx
                        }
                        
                        # Gửi lệnh dịch
                        res = call_gemini(key_to_use, text_chunk)
                        
                        if "ERR:" not in res:
                            display_status[task_idx] = {
                                "status": "done", 
                                "msg": f"✅ Xong!<br>(Bởi Key #{current_key_idx+1})",
                                "key_idx": current_key_idx
                            }
                            return task_idx, res
                        else:
                            total_errors_this_task += 1
                            
                            # Nếu lỗi quá 5 lần trên Key hiện tại -> THAY KEY
                            if total_errors_this_task >= 5:
                                display_status[task_idx] = {
                                    "status": "dead", 
                                    "msg": f"❌ Key #{current_key_idx+1} KIỆT SỨC!<br>Đang thay người...",
                                    "key_idx": current_key_idx
                                }
                                time.sleep(2)
                                
                                # Tìm Key tiếp theo (xoay vòng)
                                current_key_idx = (current_key_idx + 1) % 5
                                total_errors_this_task = 0 # Reset đếm lỗi cho Key mới
                                continue 
                            
                            # Nếu chưa quá 5 lần -> Thử lại chính Key đó
                            display_status[task_idx] = {
                                "status": "warning", 
                                "msg": f"⚠️ Key #{current_key_idx+1} NGHẼN<br>Thử lại lần {total_errors_this_task}",
                                "key_idx": current_key_idx
                            }
                            time.sleep(5)

                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = []
                    for j in range(num_actual_tasks):
                        futures.append(executor.submit(worker, j, "\n\n".join(wave_batches[j])))
                    
                    while True:
                        done_count = 0
                        cols = monitor_container.columns(5)
                        for j in range(5):
                            s = display_status[j]
                            style = f"status-{s['status']}"
                            cols[j].markdown(f"<div class='worker-box {style}'>🔮 <b>Vị trí {j+1}</b><br>{s['msg']}</div>", unsafe_allow_html=True)
                            if s['status'] == "done" or s['status'] == "idle":
                                done_count += 1
                        if done_count == 5: break
                        time.sleep(0.5)
                    
                    for future in futures:
                        t_idx, res = future.result()
                        final_results_map[wave_idx * 5 + t_idx] = res

                progress_bar.progress((wave_idx + 1) / total_waves)
                if wave_idx < total_waves - 1:
                    countdown_timer(20, timer_box)

            ordered = [final_results_map[i] for i in range(len(batches))]
            st.download_button("📥 TẢI FILE DỊCH", "\n\n".join(ordered), file_name=f"V43_ThayKey_{file.name}")
            st.balloons()

        except Exception as e:
            st.error(f"Sụp đổ: {e}")
            st.code(traceback.format_exc())
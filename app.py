import sys
# =========================================================
# BỨC TƯỜNG BẢO VỆ UTF-8 (CHỐNG LỖI FONT TIẾNG VIỆT)
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
    "AIzaSyBl_1hempgYfUPK36VMclsLLyX76zFAeQo",
    "AIzaSyCopyWAn_dGN-QU1C9NWwiiI4NpsNkZq0I",
    "AIzaSyALXMyBw1Noob3CJCHRar67KyEA51mv9zk"
]
# =========================================================

st.set_page_config(page_title="Donghua Ngũ Hành v42", page_icon="☯️", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0b0d11; color: #e0e0e0; }
    .stButton>button { 
        background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%); 
        color: white; border: none; font-weight: bold; border-radius: 12px; height: 3.5em; width: 100%;
    }
    .wave-box { 
        padding: 15px; background: #1e293b; border-left: 5px solid #3b82f6; 
        border-radius: 8px; margin-bottom: 15px; font-size: 1.1em;
    }
    .worker-box {
        padding: 10px; border-radius: 8px; text-align: center; font-size: 0.9em; box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .status-running { background: #1e3a8a; border: 1px solid #3b82f6; color: #93c5fd; }
    .status-done { background: #064e3b; border: 1px solid #10b981; color: #6ee7b7; }
    .status-error { background: #7f1d1d; border: 1px solid #ef4444; color: #fca5a5; }
    .countdown-box {
        padding: 15px; background: #1f2937; border: 1px dashed #fbbf24;
        border-radius: 8px; color: #fcd34d; text-align: center; font-weight: bold; margin: 20px 0;
    }
    h1 { color: #60a5fa !important; text-align: center; text-shadow: 1px 1px 2px #000; }
    </style>
    """, unsafe_allow_html=True)

st.markdown("<h1>☯️ DONGHUA STUDIO - NGŨ HÀNH TRẬN (V42)</h1>", unsafe_allow_html=True)

# --- HÀM GỌI API GEMINI ---
def call_gemini(api_key, text_data):
    try:
        client = genai.Client(api_key=api_key)
        sys_prompt = "Bạn là đại sư dịch thuật Donghua chuyên nghiệp. Dịch SRT sang tiếng Việt võ hiệp (Ta, Ngươi...). Giữ nguyên timestamps. CHỈ trả về nội dung tiếng việt giữ nguyên định dạng SRT."
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-preview", 
            contents=f"{sys_prompt}\n\nNỘI DUNG SRT:\n{text_data}",
            config=types.GenerateContentConfig(temperature=0.2)
        )
        if response.text:
            return response.text.strip()
        else:
            return "GOOGLE_ERROR: Phản hồi rỗng."
    except Exception as e:
        return f"GOOGLE_ERROR: {str(e)}"

# --- HÀM ĐẾM NGƯỢC ---
def countdown_timer(seconds, placeholder):
    for i in range(seconds, 0, -1):
        placeholder.markdown(
            f"<div class='countdown-box'>⏳ Đã thu công! Hệ thống đang tản nhiệt... Chờ {i} giây để xuất chiêu đợt tiếp theo.</div>", 
            unsafe_allow_html=True
        )
        time.sleep(1)
    placeholder.empty()

# --- XỬ LÝ CHÍNH ---
file = st.file_uploader("Tải file .srt lên", type=["srt"])
valid_keys = [k.strip() for k in LIST_API_KEYS if "..." not in k and k.strip()]

if file:
    if len(valid_keys) != 5:
        st.error("❌ Đại hiệp phải điền ĐỦ 5 API Key vào mảng LIST_API_KEYS để kích hoạt Ngũ Hành Trận!")
    elif st.button("KÍCH HOẠT NGŨ HÀNH LIÊN HOÀN ⚔️"):
        try:
            start_time = time.time()
            
            # Xử lý file
            raw_content = file.getvalue().decode("utf-8-sig", errors="replace").replace('\r\n', '\n').strip()
            blocks = [b.strip() for b in re.split(r'\n\s*\n', raw_content) if b.strip()]
            
            # 1. Cắt lô 40 đoạn
            batch_size = 40
            batches = [blocks[i:i + batch_size] for i in range(0, len(blocks), batch_size)]
            
            # 2. Nhóm 5 lô thành 1 "Đợt Sóng" (Wave)
            waves = [batches[i:i + 5] for i in range(0, len(batches), 5)]
            total_waves = len(waves)
            
            final_results_map = {}
            
            progress_bar = st.progress(0.0)
            wave_info = st.empty()
            monitor_container = st.empty()
            timer_box = st.empty()
            
            # --- VÒNG LẶP THEO ĐỢT SÓNG ---
            for wave_idx, wave_batches in enumerate(waves):
                num_tasks = len(wave_batches)
                
                wave_info.markdown(
                    f"<div class='wave-box'>🌊 <b>ĐANG ĐÁNH ĐỢT SÓNG {wave_idx + 1}/{total_waves}</b><br>"
                    f"Sử dụng {num_tasks} Key cùng lúc để dịch {num_tasks} đoạn...</div>", 
                    unsafe_allow_html=True
                )
                
                # Biến lưu trạng thái của 5 Key trong đợt này
                shared_status = {j: {"status": "running", "msg": "Đang vận công..."} for j in range(num_tasks)}
                wave_results = {}
                
                # Hàm cho mỗi Key (Luồng phụ)
                def worker(j_idx, text_chunk):
                    key = valid_keys[j_idx] # Key số j dịch đoạn số j
                    attempt = 0
                    while True:
                        shared_status[j_idx] = {"status": "running", "msg": f"Đang dịch..."}
                        res = call_gemini(key, text_chunk)
                        
                        if "GOOGLE_ERROR:" not in res and len(res) > 5:
                            shared_status[j_idx] = {"status": "done", "msg": "✅ Xong!"}
                            return j_idx, res
                        else:
                            attempt += 1
                            error_short = res.replace('GOOGLE_ERROR:', '').strip()[:25] + "..."
                            shared_status[j_idx] = {"status": "error", "msg": f"⚠️ Lỗi!<br>Thử lại Lần {attempt}"}
                            time.sleep(5) # Nghỉ 5s nếu lỗi rồi dịch lại
                
                # Kích hoạt 5 luồng chạy song song
                with ThreadPoolExecutor(max_workers=num_tasks) as executor:
                    futures = [executor.submit(worker, j, "\n\n".join(wave_batches[j])) for j in range(num_tasks)]
                    
                    # Luồng chính vẽ giao diện cập nhật liên tục (Chống lỗi SessionContext)
                    while True:
                        all_done = True
                        
                        # Vẽ 5 cột
                        cols = monitor_container.columns(5)
                        for j in range(num_tasks):
                            status_data = shared_status[j]
                            style = "status-done" if status_data["status"] == "done" else ("status-error" if status_data["status"] == "error" else "status-running")
                            
                            cols[j].markdown(
                                f"<div class='worker-box {style}'>🔮 <b>Key #{j+1}</b><br>{status_data['msg']}</div>", 
                                unsafe_allow_html=True
                            )
                            
                            if status_data["status"] != "done":
                                all_done = False
                        
                        if all_done:
                            break
                        time.sleep(0.5) # Quét UI mỗi nửa giây
                    
                    # Lấy kết quả khi tất cả đã xong
                    for future in futures:
                        j_idx, res = future.result()
                        global_batch_idx = wave_idx * 5 + j_idx
                        final_results_map[global_batch_idx] = res
                
                # Cập nhật thanh tiến độ
                progress_bar.progress((wave_idx + 1) / total_waves)
                
                # NGHỈ 20 GIÂY NẾU CHƯA PHẢI ĐỢT CUỐI
                if wave_idx < total_waves - 1:
                    countdown_timer(20, timer_box)
            
            # --- HOÀN TẤT VÀ LẮP RÁP FILE ---
            ordered_results = [final_results_map[i] for i in range(len(batches))]
            final_srt = "\n\n".join(ordered_results)
            duration = int(time.time() - start_time)
            
            wave_info.markdown(
                f"<div class='wave-box' style='border-left-color: #10b981; background: #064e3b; color: white;'>"
                f"✨ <b>VIÊN MÃN HOÀN TOÀN!</b><br>Đã dịch xong toàn bộ file trong {duration} giây.</div>", 
                unsafe_allow_html=True
            )
            monitor_container.empty()
            st.balloons()
            st.download_button("📥 TẢI FILE DỊCH VỀ", final_srt, file_name=f"V42_NguHanh_{file.name}")

        except Exception as e:
            st.error(f"💥 PHÁP TRẬN SỤP ĐỔ: {e}")
            st.code(traceback.format_exc(), language="python")
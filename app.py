import streamlit as st
from google import genai
from google.genai import types
import time
import re

# --- 1. GIAO DIỆN HOÀNG KIM v19 ---
st.set_page_config(page_title="Gemini 3 Donghua Studio", page_icon="🐉", layout="centered")

st.markdown("""
    <style>
    .stApp { background-color: #0b0d11; color: #e0e0e0; }
    .stButton>button {
        background: linear-gradient(135deg, #FFD700 0%, #B8860B 100%);
        color: black; border: none; font-weight: bold; border-radius: 10px;
        height: 3.5em; width: 100%; transition: 0.3s;
    }
    .stButton>button:hover { transform: scale(1.01); box-shadow: 0 0 20px #FFD700; }
    .status-card {
        padding: 25px; background: #161b22; border-radius: 15px;
        border-left: 8px solid #FFD700; text-align: center;
    }
    .milestone { color: #FFD700; font-size: 1.3em; font-weight: bold; margin-top: 10px; }
    h1 { color: #FFD700 !important; text-shadow: 2px 2px 4px #000; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. SIDEBAR CẤU HÌNH ---
with st.sidebar:
    st.header("⚔️ Linh Căn Cấu Hình")
    api_key = st.text_input("Gemini API Key:", type="password")
    # Khuyên dùng 1.5 Flash để cực kỳ ổn định, ít lỗi 503
    model_choice = st.selectbox(
        "Chọn Pháp Khí:",
        [ "gemini-3-flash-preview"]
    )
    st.divider()
    batch_size = st.select_slider("Độ dài mỗi đợt dịch:", options=[30, 50, 80, 100, 120], value=80)
    st.caption("Version 19.0 - 503 Auto-Recovery")

st.markdown("<h1 style='text-align: center;'>🐉 DONGHUA STUDIO V19.0</h1>", unsafe_allow_html=True)

# --- 3. HÀM DỊCH THUẬT ---
def translate_core(client, model_id, text_data):
    sys_prompt = (
        "Bạn là đại sư dịch thuật Donghua chuyên nghiệp. "
        "Dịch các đoạn SRT sau sang tiếng Việt phong cách VÕ HIỆP, CỔ TRANG.\n"
        "XƯNG HÔ: Ta, Ngươi, Lão phu, Tiểu tử, Bổn tọa, Tiền bối, Huynh, Đệ...\n"
        "GIỮ NGUYÊN timestamps. CHỈ trả về SRT."
    )
    try:
        response = client.models.generate_content(
            model=model_id,
            contents=f"{sys_prompt}\n\nNỘI DUNG:\n{text_data}",
            config=types.GenerateContentConfig(temperature=0.3)
        )
        return response.text.strip()
    except Exception as e:
        return f"ERROR_{str(e)}"

# --- 4. XỬ LÝ CHÍNH ---
file = st.file_uploader("Tải file .srt cần luyện hóa", type=["srt"])

if file and api_key:
    if st.button("KHỞI ĐỘNG PHÁP TRẬN KHÁNG NGHẼN ⚔️"):
        try:
            client = genai.Client(api_key=api_key)
            raw_content = file.getvalue().decode("utf-8")
            normalized = raw_content.replace('\r\n', '\n').strip()
            blocks = re.split(r'\n\s*\n', normalized)
            blocks = [b.strip() for b in blocks if b.strip()]
            
            total_batches = (len(blocks) + batch_size - 1) // batch_size
            translated_final = []
            
            ui_placeholder = st.container()
            with ui_placeholder:
                st.markdown("<div class='status-card'>", unsafe_allow_html=True)
                p_text = st.empty()
                p_bar = st.progress(0.0)
                m_text = st.empty() 
                t_text = st.empty() 
                st.markdown("</div>", unsafe_allow_html=True)

            for i in range(0, len(blocks), batch_size):
                batch = blocks[i : i + batch_size]
                batch_str = "\n\n".join(batch)
                curr_idx = (i // batch_size) + 1
                
                pct = int((curr_idx / total_batches) * 100)
                p_text.markdown(f"🚀 **Đang luyện hóa:** <span style='font-size:1.8em; color:#FFD700;'>{pct}%</span>", unsafe_allow_html=True)
                p_bar.progress(curr_idx / total_batches)
                
                # Mốc cảnh giới 25-50-75-100
                if pct >= 100: m_text.markdown("<div class='milestone'>✨ CẢNH GIỚI VIÊN MÃN (100%)</div>", unsafe_allow_html=True)
                elif pct >= 75: m_text.markdown("<div class='milestone'>⚡ ĐẠI THÀNH (75%)</div>", unsafe_allow_html=True)
                elif pct >= 50: m_text.markdown("<div class='milestone'>🔥 TRUNG THÀNH (50%)</div>", unsafe_allow_html=True)
                elif pct >= 25: m_text.markdown("<div class='milestone'>🔰 NHẬP MÔN (25%)</div>", unsafe_allow_html=True)

                success = False
                while not success:
                    res = translate_core(client, model_choice, batch_str)
                    if "ERROR_" not in res:
                        translated_final.append(res)
                        success = True
                        t_text.empty()
                    else:
                        # XỬ LÝ LỖI 503 HOẶC 429
                        t_text.warning("⚠️ Máy chủ đang nghẽn nặng (503/429). Tự động hồi sức sau 30s...")
                        time.sleep(30) # Nghỉ lâu hơn để Google hồi phục
                
                # NGHỈ CỐ ĐỊNH 10 GIÂY
                if curr_idx < total_batches:
                    for r in range(7, 0, -1):
                        t_text.markdown(f"⏳ **Nghỉ hồi nội lực:** `{r} giây` nữa dịch tiếp...")
                        time.sleep(1)
                    t_text.empty()

            st.success("🏮 ĐÃ LUYỆN XONG PHỤ ĐỀ!")
            st.balloons()
            st.download_button("📥 TẢI FILE DỊCH V19", "\n\n".join(translated_final), file_name=f"V19_{file.name}")
            
        except Exception as e:
            st.error(f"Pháp trận bị phá vỡ: {e}")
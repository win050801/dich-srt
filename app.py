import streamlit as st
from google import genai
from google.genai import types
import time
import random

# --- 1. CẤU HÌNH GIAO DIỆN ---
st.set_page_config(page_title="Gemini 3 Donghua Studio", page_icon="🐉", layout="centered")

st.markdown("""
    <style>
    .stApp { background-color: #0b0d11; color: #e0e0e0; }
    .stButton>button {
        background: linear-gradient(135deg, #FFD700 0%, #B8860B 100%);
        color: black; border: none; font-weight: bold; border-radius: 10px;
        height: 3em; width: 100%; transition: 0.3s;
    }
    .stButton>button:hover { transform: scale(1.01); box-shadow: 0 0 15px #FFD700; }
    .status-card {
        padding: 20px; background: #161b22; border-radius: 15px;
        border-left: 6px solid #FFD700; margin-bottom: 20px;
    }
    h1 { color: #FFD700 !important; text-shadow: 2px 2px 4px #000; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. THANH CÀI ĐẶT ---
with st.sidebar:
    st.header("⚙️ Thiết Lập")
    api_key = st.text_input("Gemini API Key:", type="password")
    st.divider()
    batch_size = st.select_slider("Số đoạn mỗi lần dịch:", options=[30, 50, 80, 100], value=50)
    st.info("Model: gemini-3-flash-preview")

st.markdown("<h1 style='text-align: center;'>🐉 DONGHUA STUDIO V11.0</h1>", unsafe_allow_html=True)

# --- 3. HÀM DỊCH THUẬT VÕ HIỆP ---
def translate_now(client, text_data):
    sys_prompt = (
        "Bạn là đại sư dịch thuật Donghua chuyên nghiệp. "
        "Dịch các đoạn SRT sau sang tiếng Việt phong cách VÕ HIỆP, CỔ TRANG.\n"
        "Xưng hô: Ta, Ngươi, Lão phu, Tiểu tử, Bổn tọa, Tiền bối, Huynh, Đệ...\n"
        "Văn phong trau chuốt, hào sảng. GIỮ NGUYÊN timestamps. CHỈ trả về SRT."
    )
    try:
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=f"{sys_prompt}\n\nNỘI DUNG:\n{text_data}",
            config=types.GenerateContentConfig(temperature=0.3)
        )
        return response.text.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"

# --- 4. XỬ LÝ TẢI FILE ---
file = st.file_uploader("Tải lên file .srt", type=["srt"])

if file and api_key:
    if st.button("BẮT ĐẦU LUYỆN PHỤ ĐỀ ⚔️"):
        try:
            client = genai.Client(api_key=api_key)
            content = file.getvalue().decode("utf-8").strip()
            blocks = [b.strip() for b in content.split('\n\n') if b.strip()]
            
            # Sửa lỗi dòng 75: Đảm bảo viết đầy đủ biến batch_size
            total_batches = (len(blocks) + batch_size - 1) // batch_size
            translated_final = []
            
            ui_placeholder = st.container()
            with ui_placeholder:
                st.markdown("<div class='status-card'>", unsafe_allow_html=True)
                p_text = st.empty()
                p_bar = st.progress(0)
                t_text = st.empty()
                st.markdown("</div>", unsafe_allow_html=True)

            for i in range(0, len(blocks), batch_size):
                batch = blocks[i : i + batch_size]
                batch_str = "\n\n".join(batch)
                curr_idx = (i // batch_size) + 1
                
                pct = int((curr_idx / total_batches) * 100)
                p_text.markdown(f"🔥 **Tiến độ:** `{pct}%` | Phần {curr_idx}/{total_batches}")
                p_bar.progress(curr_part := curr_idx / total_batches)

                success = False
                while not success:
                    res = translate_now(client, batch_str)
                    if "ERROR:" not in res:
                        translated_final.append(res)
                        success = True
                    else:
                        t_text.warning("⚠️ Đang nghẽn API. Chờ 15 giây...")
                        time.sleep(15)
                
                if curr_idx < total_batches:
                    wait = random.randint(7, 10)
                    for r in range(wait, 0, -1):
                        t_text.markdown(f"⏳ **Hồi nội lực:** `{r} giây` nữa dịch tiếp...")
                        time.sleep(1)
                    t_text.empty()

            st.success("🏮 HOÀN TẤT!")
            st.balloons()
            st.download_button("📥 TẢI FILE DỊCH", "\n\n".join(translated_final), file_name=f"V11_{file.name}")
            
        except Exception as e:
            st.error(f"Lỗi: {e}")
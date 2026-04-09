import streamlit as st
from google import genai
import time

# 1. Cấu hình giao diện
st.set_page_config(page_title="Gemini SRT Translator", page_icon="🎬")
st.title("🎬 Trình dịch phụ đề SRT (Batch 50)")

# 2. Sidebar cài đặt
with st.sidebar:
    st.header("Cài đặt")
    api_key = st.text_input("Nhập Gemini API Key:", type="password")
    batch_size = st.number_input("Số đoạn mỗi lần dịch:", min_value=10, max_value=100, value=50)
    st.info("Lấy API Key tại Google AI Studio")

# 3. Hàm chia nhỏ file SRT
def split_srt(content, size):
    # SRT chia các đoạn bằng 2 dấu xuống dòng (\n\n)
    blocks = content.strip().split('\n\n')
    for i in range(0, len(blocks), size):
        yield blocks[i:i + size]

# 4. Giao diện tải file
uploaded_file = st.file_uploader("Chọn file .srt cần dịch", type=["srt"])

if uploaded_file:
    content = uploaded_file.getvalue().decode("utf-8")
    
    if st.button("Bắt đầu dịch 🚀"):
        if not api_key:
            st.error("⚠️ Vui lòng nhập API Key ở bên trái!")
        else:
            try:
                client = genai.Client(api_key=api_key)
                blocks = content.strip().split('\n\n')
                total_batches = (len(blocks) + batch_size - 1) // batch_size
                
                translated_result = []
                progress_bar = st.progress(0)
                status = st.empty()

                for i, batch in enumerate(split_srt(content, batch_size)):
                    status.text(f"Đang dịch phần {i+1}/{total_batches}...")
                    
                    batch_text = "\n\n".join(batch)
                    prompt = f"Dịch các đoạn phụ đề SRT sau sang tiếng Việt. Giữ nguyên số thứ tự và thời gian (00:00:00,000). Chỉ trả về file SRT đã dịch:\n\n{batch_text}"
                    
                    response = client.models.generate_content(
                        model="gemini-2.0-flash",
                        contents=prompt
                    )
                    
                    translated_result.append(response.text.strip())
                    progress_bar.progress((i + 1) / total_batches)
                    time.sleep(1) # Nghỉ 1 giây để tránh lỗi

                # Gộp kết quả và cho tải về
                final_srt = "\n\n".join(translated_result)
                st.success("✅ Đã dịch xong!")
                st.download_button("Tải file .srt đã dịch", final_srt, file_name="phim_tieng_viet.srt")
                
            except Exception as e:
                st.error(f"Lỗi: {str(e)}")

# Commit changes sau khi dán xong!

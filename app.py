import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
import datetime

# 設定頁面資訊
st.set_page_config(page_title="台北羽球場地快搜", layout="wide", page_icon="🏸")

# --- 核心爬蟲函式 (加上快取裝飾器) ---
# ttl=3600 代表這筆資料會被快取 3600 秒 (1小時)
# 1小時內有人再查同一間學校，不會真正執行爬蟲，而是直接回傳暫存檔
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_school_data(school_name):
    # 這裡未來可以擴充成 Dictionary 來對應不同學校的 URL
    if school_name == "興雅國中":
        target_url = "https://www.syajh.tp.edu.tw/more_infor.php?p_id=36"
        base_url = "https://www.syajh.tp.edu.tw/"
    else:
        return {"status": "error", "message": "尚未支援此學校"}

    try:
        headers = {'User-Agent': 'Mozilla/5.0 ...'} # 省略長字串
        response = requests.get(target_url, headers=headers, timeout=10)
        # ... (中間爬蟲邏輯同上，省略以節省篇幅) ...
        # 假設這裡成功抓到了 data
        
        # 模擬回傳資料
        return {
            "status": "success",
            "title": "113年度羽球場租借公告",
            "date": "2024-03-01",
            "url": target_url,
            "last_updated": datetime.datetime.now().strftime("%H:%M:%S")
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- 前端介面 ---
st.title("🏸 台北市學校羽球場地資訊")
st.caption("資料來源：各校官方網站 | 自動快取更新：每小時")

col1, col2 = st.columns([1, 2])

with col1:
    school = st.selectbox("選擇場地", ["興雅國中", "更多學校開發中..."])
    
    # 重新整理按鈕 (強制清除快取)
    if st.button("強制刷新資料"):
        st.cache_data.clear()
        st.rerun()

with col2:
    if school == "興雅國中":
        with st.spinner('正在連線學校主機...'):
            data = fetch_school_data(school)
            
            if data['status'] == 'success':
                st.success(f"資料取得成功 (更新時間: {data.get('last_updated')})")
                
                # 漂亮的卡片顯示
                with st.container(border=True):
                    st.markdown(f"### {data['title']}")
                    st.markdown(f"**公告日期**: {data['date']}")
                    st.link_button("前往官網查看詳情", data['url'])
            else:
                st.error("讀取失敗，請稍後再試")
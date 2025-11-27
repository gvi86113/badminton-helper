import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import pytz
import re
from urllib.parse import urljoin

# --- 設定台北時區 ---
TP_TIMEZONE = pytz.timezone('Asia/Taipei')

# --- 工具函式 ---

def get_current_time():
    return datetime.now(TP_TIMEZONE)

def parse_taiwan_date(date_str):
    """
    將各種格式的日期 (113-05-20, 2024/05/20) 統一轉為 datetime 物件
    """
    if not date_str:
        return None
    
    # 移除空白與特殊字元
    date_str = date_str.strip()
    
    # 處理民國年 (例如 113-01-01 或 113/01/01)
    minguo_match = re.match(r'(\d{3})[./-](\d{1,2})[./-](\d{1,2})', date_str)
    if minguo_match:
        year = int(minguo_match.group(1)) + 1911
        month = int(minguo_match.group(2))
        day = int(minguo_match.group(3))
        return TP_TIMEZONE.localize(datetime(year, month, day))
    
    # 處理西元年 (例如 2024-01-01)
    western_match = re.match(r'(\d{4})[./-](\d{1,2})[./-](\d{1,2})', date_str)
    if western_match:
        year = int(western_match.group(1))
        month = int(western_match.group(2))
        day = int(western_match.group(3))
        return TP_TIMEZONE.localize(datetime(year, month, day))
        
    return None

# --- 爬蟲邏輯 ---

class SchoolScraper:
    def __init__(self, name, list_url, base_url):
        self.name = name
        self.list_url = list_url
        self.base_url = base_url
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0'
        }

    def fetch_data(self, days_limit=120):
        """抓取並回傳符合條件的資料列表"""
        results = []
        try:
            response = requests.get(self.list_url, headers=self.headers, timeout=10)
            if response.status_code != 200:
                return []
            
            # 根據不同學校類型呼叫不同的解析函式
            if "syajh" in self.base_url:
                results = self._parse_xingya(response.text)
            elif "nss" in self.list_url: # 仁愛、信義等 NSS 系統
                results = self._parse_nss(response.text)
            
            # 過濾資料：1. 包含「羽球」 2. 時間在限制天數內
            filtered_results = []
            limit_date = get_current_time() - timedelta(days=days_limit)
            
            for item in results:
                # 關鍵字過濾
                if "羽球" not in item['title']:
                    continue
                
                # 日期過濾
                item_date = parse_taiwan_date(item['date'])
                if item_date and item_date > limit_date:
                    item['parsed_date'] = item_date # 存起來做排序用
                    filtered_results.append(item)
            
            return filtered_results
            
        except Exception as e:
            print(f"Error scraping {self.name}: {e}")
            return []

    def _parse_xingya(self, html):
        """解析興雅國中 (傳統 PHP 表格)"""
        soup = BeautifulSoup(html, 'html.parser')
        items = []
        # 興雅的列表通常在表格內，這裡抓取所有含有連結的列
        # 尋找結構：通常是 tr -> td -> a
        rows = soup.find_all('tr')
        for row in rows:
            # 嘗試找日期 (格式通常是 YYYY-MM-DD)
            text_content = row.get_text()
            date_match = re.search(r'\d{4}-\d{2}-\d{2}', text_content)
            
            a_tag = row.find('a')
            if date_match and a_tag:
                date_str = date_match.group(0)
                title = a_tag.get_text(strip=True)
                link = urljoin(self.base_url, a_tag['href'])
                
                items.append({
                    "school": self.name,
                    "date": date_str,
                    "title": title,
                    "url": link
                })
        return items

    def _parse_nss(self, html):
        """解析 NSS 系統 (仁愛、信義)"""
        soup = BeautifulSoup(html, 'html.parser')
        items = []
        
        # NSS 系統結構通常是 div 列表
        # 嘗試抓取常見的列表 class，這裡針對你提供的網址結構進行通用解析
        # 這些網站通常將標題放在 title 屬性或特定的 div 中
        
        # 策略：抓取所有含有 href 的區塊，並試圖從區塊文字中分離日期與標題
        # NSS 的列表項目通常包在 r-ent 或類似結構，或直接找 data-date
        
        # 嘗試更通用的抓法：抓取所有 "panel-heading" 或列表項目
        # 由於 NSS 結構複雜，我們這裡用一個 trick: 抓取所有連結，檢查其父元素是否有日期
        
        for a_tag in soup.find_all('a', href=True):
            parent_text = a_tag.parent.get_text() if a_tag.parent else ""
            grandparent_text = a_tag.parent.parent.get_text() if a_tag.parent and a_tag.parent.parent else ""
            
            # 合併文字來找日期
            full_text = (a_tag.get_text() + " " + parent_text + " " + grandparent_text).strip()
            
            # 尋找日期 (NSS 常見格式: 2024/11/27 或 2024-11-27)
            date_match = re.search(r'\d{4}[-/]\d{2}[-/]\d{2}', full_text)
            
            if date_match:
                title = a_tag.get_text(strip=True)
                # 排除太短的連結文字 (例如 "更多")
                if len(title) > 4: 
                    link = urljoin(self.base_url, a_tag['href'])
                    items.append({
                        "school": self.name,
                        "date": date_match.group(0),
                        "title": title,
                        "url": link
                    })
        
        # 去除重複 (NSS 有時會有手機版/電腦版重複連結)
        seen = set()
        unique_items = []
        for item in items:
            key = item['url']
            if key not in seen:
                seen.add(key)
                unique_items.append(item)
                
        return unique_items

# --- 主程式 ---

st.set_page_config(page_title="台北市學校羽球公告彙整", layout="wide", page_icon="🏸")

st.title("🏸 台北市學校羽球場地公告彙整 (近120天)")
st.caption(f"目前時間 (台北): {get_current_time().strftime('%Y-%m-%d %H:%M')}")

# 定義目標學校與其列表網址 (這是關鍵，不能只用內文網址)
# 這裡根據你提供的內文網址，推導出列表網址
SCHOOL_LIST = [
    {
        "name": "興雅國中",
        "base_url": "https://www.syajh.tp.edu.tw/",
        "list_url": "https://www.syajh.tp.edu.tw/more_infor.php?p_id=36"
    },
    {
        "name": "仁愛國小",
        "base_url": "https://www.japs.tp.edu.tw/",
        "list_url": "https://www.japs.tp.edu.tw/nss/main/freeze/5a9759adef37531ea27bf1b0/Cqfg8H21612" # 推導出的公告列表
    },
    {
        "name": "信義國小",
        "base_url": "https://www.syes.tp.edu.tw/",
        "list_url": "https://www.syes.tp.edu.tw/nss/main/freeze/5abf2d62aa93092cee58ceb4/N84R5hZ3727" # 推導出的公告列表
    }
]

# 快取函式 (每 30 分鐘更新一次)
@st.cache_data(ttl=1800, show_spinner=False)
def get_all_school_data():
    all_data = []
    
    # 建立進度條
    progress_text = "正在掃描各校公告..."
    my_bar = st.progress(0, text=progress_text)
    
    total_schools = len(SCHOOL_LIST)
    for idx, school_info in enumerate(SCHOOL_LIST):
        scraper = SchoolScraper(school_info['name'], school_info['list_url'], school_info['base_url'])
        data = scraper.fetch_data(days_limit=120)
        all_data.extend(data)
        
        # 更新進度
        progress = (idx + 1) / total_schools
        my_bar.progress(progress, text=f"已掃描: {school_info['name']} (找到 {len(data)} 筆)")
        
    my_bar.empty()
    return all_data

# 執行按鈕
if st.button("🔄 立即更新資料", type="primary"):
    st.cache_data.clear()
    st.rerun()

# 獲取資料
with st.spinner('資料彙整中...'):
    raw_data = get_all_school_data()

if not raw_data:
    st.warning("近 120 天內沒有找到含有「羽球」關鍵字的公告。")
else:
    # 轉換成 DataFrame 以利排序與顯示
    df = pd.DataFrame(raw_data)
    
    # 確保依照日期排序 (新 -> 舊)
    df = df.sort_values(by='parsed_date', ascending=False)
    
    # 重整顯示資料
    display_df = df[['date', 'school', 'title', 'url']].copy()
    display_df.columns = ['公告日期', '學校', '標題', '連結']
    
    # 顯示統計
    st.success(f"共找到 {len(df)} 筆公告")

    # 卡片式顯示 (比表格在手機上更好讀)
    for index, row in display_df.iterrows():
        with st.container(border=True):
            col1, col2 = st.columns([1, 4])
            with col1:
                st.markdown(f"**{row['學校']}**")
                st.caption(f"📅 {row['公告日期']}")
            with col2:
                st.markdown(f"[{row['標題']}]({row['連結']})")

    # 如果需要表格模式，可以解開下面這行
    # st.dataframe(display_df, hide_index=True, use_container_width=True, column_config={"連結": st.column_config.LinkColumn()})

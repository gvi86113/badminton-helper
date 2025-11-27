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
    if not date_str:
        return None
    date_str = str(date_str).strip()
    
    # 嘗試抓取各種日期格式
    # 格式: 113.05.20, 113-05-20, 113/05/20
    minguo_match = re.search(r'(\d{3})[./-](\d{1,2})[./-](\d{1,2})', date_str)
    if minguo_match:
        year = int(minguo_match.group(1)) + 1911
        month = int(minguo_match.group(2))
        day = int(minguo_match.group(3))
        return TP_TIMEZONE.localize(datetime(year, month, day))
    
    # 格式: 2024-05-20, 2024/05/20
    western_match = re.search(r'(\d{4})[./-](\d{1,2})[./-](\d{1,2})', date_str)
    if western_match:
        year = int(western_match.group(1))
        month = int(western_match.group(2))
        day = int(western_match.group(3))
        return TP_TIMEZONE.localize(datetime(year, month, day))
        
    return None

# --- 爬蟲邏輯 ---
class SchoolScraper:
    def __init__(self, name, list_url, base_url, debug_mode=False):
        self.name = name
        self.list_url = list_url
        self.base_url = base_url
        self.debug = debug_mode
        self.logs = [] # 儲存 Log

    def log(self, msg):
        if self.debug:
            self.logs.append(f"[{self.name}] {msg}")

    def fetch_data(self, days_limit=120):
        results = []
        try:
            self.log(f"開始請求網址: {self.list_url}")
            response = requests.get(self.list_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
            }, timeout=15)
            
            self.log(f"HTTP 狀態碼: {response.status_code}")
            
            if response.status_code != 200:
                self.log("請求失敗，跳過")
                return [], self.logs
            
            # 解析
            if "syajh" in self.base_url:
                raw_items = self._parse_xingya(response.text)
            elif "nss" in self.list_url:
                raw_items = self._parse_nss(response.text)
            else:
                raw_items = []

            self.log(f"原始抓取筆數 (未過濾): {len(raw_items)}")
            
            # 過濾
            filtered_results = []
            limit_date = get_current_time() - timedelta(days=days_limit)
            
            for item in raw_items:
                # 日期解析與檢查
                item_date = parse_taiwan_date(item['date'])
                item['parsed_date'] = item_date
                
                debug_info = f"標題: {item['title'][:10]}... | 日期: {item['date']}"

                if not item_date:
                    self.log(f"❌ 日期解析失敗: {debug_info}")
                    continue

                days_diff = (get_current_time() - item_date).days
                
                # 關鍵字過濾 (寬鬆一點，先不過濾羽球，只標記)
                has_keyword = "羽球" in item['title']
                
                if item_date > limit_date:
                    if has_keyword:
                        filtered_results.append(item)
                        self.log(f"✅ 保留: {debug_info} (距今 {days_diff} 天)")
                    else:
                         self.log(f"⚠️ 捨棄 (無關鍵字): {debug_info}")
                else:
                    self.log(f"⏳ 捨棄 (過期): {debug_info} (距今 {days_diff} 天, 限制 {days_limit} 天)")
            
            return filtered_results, self.logs
            
        except Exception as e:
            self.log(f"發生錯誤: {str(e)}")
            return [], self.logs

    def _parse_xingya(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        items = []
        rows = soup.find_all('tr')
        self.log(f"找到 {len(rows)} 個表格列")
        for row in rows:
            text = row.get_text()
            # 興雅日期格式通常是 2024-11-20
            date_match = re.search(r'\d{4}-\d{2}-\d{2}', text)
            a_tag = row.find('a')
            
            if date_match and a_tag:
                items.append({
                    "school": self.name,
                    "date": date_match.group(0),
                    "title": a_tag.get_text(strip=True),
                    "url": urljoin(self.base_url, a_tag['href'])
                })
        return items

    def _parse_nss(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        items = []
        # NSS 系統結構複雜，改用更暴力的抓法：抓所有連結，往上找日期
        all_links = soup.find_all('a', href=True)
        self.log(f"掃描頁面連結數: {len(all_links)}")
        
        for a_tag in all_links:
            # 往上找 2 層父元素來搜尋日期文字
            container = a_tag.parent.parent if a_tag.parent else a_tag
            text_context = container.get_text()
            
            # 支援 2024/11/20 或 2024-11-20
            date_match = re.search(r'\d{4}[-/]\d{2}[-/]\d{2}', text_context)
            
            if date_match:
                title = a_tag.get_text(strip=True)
                # 過濾掉太短的導覽列連結
                if len(title) > 4:
                    items.append({
                        "school": self.name,
                        "date": date_match.group(0),
                        "title": title,
                        "url": urljoin(self.base_url, a_tag['href'])
                    })
        
        # 去重
        seen = set()
        unique = []
        for i in items:
            if i['url'] not in seen:
                seen.add(i['url'])
                unique.append(i)
        return unique

# --- 主程式 ---

st.set_page_config(page_title="台北市學校羽球公告彙整", layout="wide", page_icon="🏸")

st.sidebar.title("⚙️ 設定與除錯")
debug_mode = st.sidebar.checkbox("開啟工程師除錯模式 (Show Logs)", value=True)
days_limit_input = st.sidebar.number_input("搜尋天數範圍 (天)", value=365, min_value=30, max_value=9999) # 預設改大一點測試

st.title("🏸 台北市學校羽球場地公告")
st.caption(f"目前系統時間: {get_current_time().strftime('%Y-%m-%d %H:%M')}")

SCHOOL_LIST = [
    {"name": "興雅國中", "base_url": "https://www.syajh.tp.edu.tw/", "list_url": "https://www.syajh.tp.edu.tw/more_infor.php?p_id=36"},
    {"name": "仁愛國小", "base_url": "https://www.japs.tp.edu.tw/", "list_url": "https://www.japs.tp.edu.tw/nss/main/freeze/5a9759adef37531ea27bf1b0/Cqfg8H21612"},
    {"name": "信義國小", "base_url": "https://www.syes.tp.edu.tw/", "list_url": "https://www.syes.tp.edu.tw/nss/main/freeze/5abf2d62aa93092cee58ceb4/N84R5hZ3727"}
]

if st.button("🔄 立即更新資料", type="primary"):
    st.cache_data.clear()
    st.rerun()

all_data = []
all_logs = {}

with st.spinner('機器人巡邏中...'):
    for school in SCHOOL_LIST:
        scraper = SchoolScraper(school['name'], school['list_url'], school['base_url'], debug_mode=debug_mode)
        data, logs = scraper.fetch_data(days_limit=days_limit_input)
        all_data.extend(data)
        all_logs[school['name']] = logs

# 顯示結果
if not all_data:
    st.warning(f"近 {days_limit_input} 天內沒有找到含有「羽球」關鍵字的公告。")
else:
    df = pd.DataFrame(all_data)
    df = df.sort_values(by='parsed_date', ascending=False)
    st.success(f"共找到 {len(df)} 筆公告")
    
    for index, row in df.iterrows():
        with st.container(border=True):
            col1, col2 = st.columns([1, 4])
            with col1:
                st.markdown(f"**{row['school']}**")
                st.caption(row['date'])
            with col2:
                st.markdown(f"[{row['title']}]({row['url']})")

# 顯示除錯 Log
if debug_mode:
    st.markdown("---")
    st.subheader("🛠️ 工程師除錯日誌 (Debug Logs)")
    for school_name, logs in all_logs.items():
        with st.expander(f"{school_name} - 執行紀錄", expanded=False):
            for log in logs:
                if "❌" in log or "⚠️" in log:
                    st.error(log)
                elif "✅" in log:
                    st.success(log)
                else:
                    st.text(log)

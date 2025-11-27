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
    # 確保回傳當下的台北時間
    return datetime.now(TP_TIMEZONE)

def parse_taiwan_date(date_str):
    if not date_str:
        return None
    date_str = str(date_str).strip()
    
    # 【修正重點】優先嘗試匹配西元年 (4碼年份)，避免 2025 被誤判為民國 025 年
    # 格式: 2024-05-20, 2024/05/20
    western_match = re.search(r'(\d{4})[./-](\d{1,2})[./-](\d{1,2})', date_str)
    if western_match:
        year = int(western_match.group(1))
        month = int(western_match.group(2))
        day = int(western_match.group(3))
        return TP_TIMEZONE.localize(datetime(year, month, day))

    # 再嘗試匹配民國年 (3碼年份)
    # 格式: 113.05.20, 113-05-20, 113/05/20
    minguo_match = re.search(r'(\d{3})[./-](\d{1,2})[./-](\d{1,2})', date_str)
    if minguo_match:
        year = int(minguo_match.group(1)) + 1911
        month = int(minguo_match.group(2))
        day = int(minguo_match.group(3))
        return TP_TIMEZONE.localize(datetime(year, month, day))
        
    return None

# --- 爬蟲核心邏輯 ---
class SchoolScraper:
    def __init__(self, name, list_url, base_url, debug_mode=False):
        self.name = name
        self.list_url = list_url
        self.base_url = base_url
        self.debug = debug_mode
        self.logs = [] 

    def log(self, msg):
        if self.debug:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{timestamp}] [{self.name}] {msg}")

    def fetch_data(self, days_limit=120):
        results = []
        try:
            self.log(f"開始請求網址: {self.list_url}")
            response = requests.get(self.list_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
            }, timeout=20)
            
            if response.status_code != 200:
                self.log(f"❌ 請求失敗 (Status: {response.status_code})")
                return [], self.logs
            
            # 解析頁面
            if "syajh" in self.base_url:
                raw_items = self._parse_xingya(response.text)
            elif "nss" in self.list_url:
                raw_items = self._parse_nss(response.text)
            else:
                raw_items = []

            self.log(f"頁面解析完成，找到 {len(raw_items)} 個潛在項目")
            
            # 過濾資料
            filtered_results = []
            limit_date = get_current_time() - timedelta(days=days_limit)
            
            # 定義關鍵字 (OR 邏輯)
            KEYWORDS = ["羽球", "場地"]

            for item in raw_items:
                # 1. 日期檢查
                item_date = parse_taiwan_date(item['date'])
                item['parsed_date'] = item_date
                
                short_title = (item['title'][:15] + '..') if len(item['title']) > 15 else item['title']
                debug_info = f"標題: {short_title} | 日期: {item['date']}"

                if not item_date:
                    self.log(f"❌ 日期無法解析: {debug_info}")
                    continue

                # 2. 關鍵字檢查
                has_keyword = any(k in item['title'] for k in KEYWORDS)
                
                # 3. 時間範圍與過濾
                days_diff = (get_current_time() - item_date).days
                
                if item_date > limit_date:
                    if has_keyword:
                        filtered_results.append(item)
                        # 只有符合關鍵字的才顯示綠色勾勾，保持版面乾淨
                        self.log(f"✅ 保留: {debug_info} (命中關鍵字)")
                    else:
                        # 不符合關鍵字的項目，直接忽略，不寫入 Log 干擾視線，除非你需要極度詳細的除錯
                        # self.log(f"⚠️ 捨棄 (無關鍵字): {debug_info}")
                        pass
                else:
                    # 只有當它「有關鍵字」但「過期」時才顯示，避免顯示一堆過期的無關公告
                    if has_keyword:
                        self.log(f"⏳ 捨棄 (過期): {debug_info} (距今 {days_diff} 天 > {days_limit} 天)")
            
            return filtered_results, self.logs
            
        except Exception as e:
            self.log(f"🔥 程式錯誤: {str(e)}")
            return [], self.logs

    def _parse_xingya(self, html):
        """
        興雅國中解析器 (加強版)
        """
        soup = BeautifulSoup(html, 'html.parser')
        items = []
        all_links = soup.find_all('a', href=True)
        
        self.log(f"掃描頁面 {len(all_links)} 個連結...")

        for link in all_links:
            title = link.get_text(strip=True)
            url = link['href']
            
            if len(title) < 4: continue # 過濾無效連結

            # 往上找父層抓日期 (嘗試 4 層，確保抓到 RWD 的 row)
            container = link
            found_date = None
            
            for _ in range(4): # 往上爬 4 層
                if container.parent:
                    container = container.parent
                    row_text = container.get_text(" ", strip=True) # 用空格分隔
                    
                    # Regex: 抓 2025-11-27
                    date_match = re.search(r'\d{4}-\d{2}-\d{2}', row_text)
                    if date_match:
                        found_date = date_match.group(0)
                        break # 找到了就停止往上爬
                else:
                    break
            
            if found_date:
                full_url = urljoin(self.base_url, url)
                items.append({
                    "school": self.name,
                    "date": found_date,
                    "title": title,
                    "url": full_url
                })

        # 去重
        seen = set()
        unique_items = []
        for item in items:
            if item['url'] not in seen:
                seen.add(item['url'])
                unique_items.append(item)
        return unique_items

    def _parse_nss(self, html):
        """NSS 系統解析器"""
        soup = BeautifulSoup(html, 'html.parser')
        items = []
        all_links = soup.find_all('a', href=True)
        
        for a_tag in all_links:
            container = a_tag
            found_date = None
            # 同樣嘗試往上爬
            for _ in range(3):
                if container.parent:
                    container = container.parent
                    row_text = container.get_text(" ", strip=True)
                    date_match = re.search(r'\d{4}[-/]\d{2}[-/]\d{2}', row_text)
                    if date_match:
                        found_date = date_match.group(0)
                        break
            
            if found_date:
                title = a_tag.get_text(strip=True)
                if len(title) > 4:
                    items.append({
                        "school": self.name,
                        "date": found_date,
                        "title": title,
                        "url": urljoin(self.base_url, a_tag['href'])
                    })
        
        seen = set()
        unique = []
        for i in items:
            if i['url'] not in seen:
                seen.add(i['url'])
                unique.append(i)
        return unique

# --- Streamlit 前端 ---

st.set_page_config(page_title="台北市學校羽球公告彙整", layout="wide", page_icon="🏸")

st.sidebar.title("⚙️ 設定與除錯")
debug_mode = st.sidebar.checkbox("開啟工程師除錯模式 (Show Logs)", value=True)
# 預設 365 天，確保不會因為過濾太嚴格而看起來像沒資料
days_limit_input = st.sidebar.number_input("搜尋天數範圍 (天)", value=365, min_value=30, step=30) 

st.title("🏸 台北市學校羽球場地公告")
current_time = get_current_time()
st.caption(f"目前系統時間 (台北): {current_time.strftime('%Y-%m-%d %H:%M')}")

SCHOOL_LIST = [
    {"name": "興雅國中", "base_url": "https://www.syajh.tp.edu.tw/", "list_url": "https://www.syajh.tp.edu.tw/more_infor.php?p_id=36"},
    # 註解另外兩間，專注測試興雅
    # {"name": "仁愛國小", "base_url": "https://www.japs.tp.edu.tw/", "list_url": "https://www.japs.tp.edu.tw/nss/main/freeze/5a9759adef37531ea27bf1b0/Cqfg8H21612"},
    # {"name": "信義國小", "base_url": "https://www.syes.tp.edu.tw/", "list_url": "https://www.syes.tp.edu.tw/nss/main/freeze/5abf2d62aa93092cee58ceb4/N84R5hZ3727"}
]

if st.button("🔄 立即更新資料", type="primary"):
    st.cache_data.clear()
    st.rerun()

all_data = []
all_logs = {}

with st.spinner('正在掃描並過濾資料 (關鍵字: 羽球 OR 場地)...'):
    for school in SCHOOL_LIST:
        scraper = SchoolScraper(school['name'], school['list_url'], school['base_url'], debug_mode=debug_mode)
        data, logs = scraper.fetch_data(days_limit=days_limit_input)
        all_data.extend(data)
        all_logs[school['name']] = logs

if not all_data:
    st.warning(f"近 {days_limit_input} 天內沒有找到含有「羽球」或「場地」的公告。")
else:
    df = pd.DataFrame(all_data)
    df = df.sort_values(by='parsed_date', ascending=False)
    
    st.success(f"共找到 {len(df)} 筆公告")
    
    for index, row in df.iterrows():
        with st.container(border=True):
            col1, col2 = st.columns([1, 5])
            with col1:
                st.markdown(f"**{row['school']}**")
                st.caption(f"📅 {row['date']}")
            with col2:
                st.markdown(f"#### [{row['title']}]({row['url']})")
                if row['parsed_date']:
                    days_diff = (current_time - row['parsed_date']).days
                    if days_diff < 0:
                        st.caption(f"未來公告 ({-days_diff} 天後)")
                    else:
                        st.caption(f"{days_diff} 天前發布")

if debug_mode:
    st.markdown("---")
    st.subheader("🛠️ 工程師除錯日誌")
    for school_name, logs in all_logs.items():
        with st.expander(f"{school_name} - 執行紀錄 ({len(logs)} 行)", expanded=True):
            for log in logs:
                if "❌" in log or "🔥" in log:
                    st.error(log)
                elif "⚠️" in log:
                    st.warning(log)
                elif "✅" in log:
                    st.success(log)
                else:
                    st.text(log)

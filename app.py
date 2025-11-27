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
    
    # 優先嘗試匹配西元年 (4碼年份)
    western_match = re.search(r'(\d{4})[./-](\d{1,2})[./-](\d{1,2})', date_str)
    if western_match:
        year = int(western_match.group(1))
        month = int(western_match.group(2))
        day = int(western_match.group(3))
        return TP_TIMEZONE.localize(datetime(year, month, day))

    # 再嘗試匹配民國年 (3碼年份)
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

    def fetch_data(self, days_limit=120, max_pages=3):
        """
        支援翻頁的資料抓取
        max_pages: 最大翻頁數 (預設 3 頁)
        """
        all_results = []
        current_url = self.list_url
        page_num = 0
        
        try:
            # 翻頁迴圈：只要有網址且還沒超過頁數上限，就繼續抓
            while current_url and page_num < max_pages:
                page_num += 1
                self.log(f"📄 正在讀取第 {page_num} 頁: {current_url}")
                
                response = requests.get(current_url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
                }, timeout=20)
                
                if response.status_code != 200:
                    self.log(f"❌ 第 {page_num} 頁請求失敗 (Status: {response.status_code})")
                    break # 這一頁失敗就停止翻頁
                
                # 解析頁面 (現在會回傳 next_url)
                next_url = None
                raw_items = []
                
                if "syajh" in self.base_url:
                    raw_items, next_url = self._parse_xingya(response.text)
                elif "nss" in self.list_url:
                    raw_items, next_url = self._parse_nss(response.text)
                else:
                    raw_items, next_url = [], None

                self.log(f"第 {page_num} 頁解析完成，找到 {len(raw_items)} 個項目。下一頁連結: {'有' if next_url else '無'}")
                
                # --- 開始過濾這一頁的資料 ---
                limit_date = get_current_time() - timedelta(days=days_limit)
                KEYWORDS = ["羽球", "場地"]

                for item in raw_items:
                    item_date = parse_taiwan_date(item['date'])
                    item['parsed_date'] = item_date
                    
                    short_title = (item['title'][:15] + '..') if len(item['title']) > 15 else item['title']
                    debug_info = f"標題: {short_title} | 日期: {item['date']}"

                    if not item_date:
                        self.log(f"❌ 日期無法解析: {debug_info}")
                        continue

                    has_keyword = any(k in item['title'] for k in KEYWORDS)
                    
                    if item_date > limit_date:
                        if has_keyword:
                            all_results.append(item)
                            self.log(f"✅ 保留: {debug_info} (命中關鍵字)")
                    else:
                        if has_keyword:
                            self.log(f"⏳ 捨棄 (過期): {debug_info}")

                # 設定下一輪的網址
                current_url = next_url
                
                # 如果沒有下一頁，就跳出迴圈
                if not current_url:
                    self.log("🏁 已無下一頁，停止翻頁。")
                    break
            
            return all_results, self.logs
            
        except Exception as e:
            self.log(f"🔥 程式錯誤: {str(e)}")
            return [], self.logs

    def _parse_xingya(self, html):
        """
        興雅國中解析器 (支援翻頁與 RWD)
        回傳: (items, next_page_url)
        """
        soup = BeautifulSoup(html, 'html.parser')
        items = []
        
        # 1. 抓取內容
        all_links = soup.find_all('a', href=True)
        # self.log(f"掃描頁面 {len(all_links)} 個連結...") # Log太多先註解

        for link in all_links:
            title = link.get_text(strip=True)
            url = link['href']
            
            if len(title) < 4: continue

            container = link
            found_date = None
            
            for _ in range(4):
                if container.parent:
                    container = container.parent
                    row_text = container.get_text(" ", strip=True)
                    date_match = re.search(r'\d{4}-\d{2}-\d{2}', row_text)
                    if date_match:
                        found_date = date_match.group(0)
                        break
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
        
        # 2. 抓取下一頁連結 (更寬鬆的搜尋邏輯)
        next_url = None
        # 直接遍歷所有連結，檢查文字內容是否包含「下一頁」
        pagination_links = soup.find_all('a', href=True)
        for link in pagination_links:
            # 去除空白後檢查文字
            link_text = link.get_text(strip=True)
            if "下一頁" in link_text:
                href = link['href']
                # 排除 javascript void 或空連結
                if "javascript" not in href.lower() and href != "#":
                    full_url = urljoin(self.base_url, href)
                    # 只有當網址不一樣時才視為下一頁 (避免原地打轉)
                    if full_url != self.list_url:
                        next_url = full_url
                        self.log(f"🔗 發現翻頁連結: {next_url}")
                        break
        
        return unique_items, next_url

    def _parse_nss(self, html):
        """NSS 系統解析器"""
        soup = BeautifulSoup(html, 'html.parser')
        items = []
        all_links = soup.find_all('a', href=True)
        
        for a_tag in all_links:
            container = a_tag
            found_date = None
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
        
        # NSS 系統通常是動態載入或單頁顯示較多，暫不支援簡單翻頁
        return unique, None

# --- Streamlit 前端 ---

st.set_page_config(page_title="台北市學校羽球公告彙整", layout="wide", page_icon="🏸")

st.sidebar.title("⚙️ 設定與除錯")
debug_mode = st.sidebar.checkbox("開啟工程師除錯模式 (Show Logs)", value=True)
days_limit_input = st.sidebar.number_input("搜尋天數範圍 (天)", value=365, min_value=30, step=30)
# 新增翻頁設定
max_pages_input = st.sidebar.number_input("最大翻頁數", value=3, min_value=1, max_value=10, help="設定每個學校最多往後爬幾頁")

st.title("🏸 台北市學校羽球場地公告")
current_time = get_current_time()
st.caption(f"目前系統時間 (台北): {current_time.strftime('%Y-%m-%d %H:%M')}")

SCHOOL_LIST = [
    {"name": "興雅國中", "base_url": "https://www.syajh.tp.edu.tw/", "list_url": "https://www.syajh.tp.edu.tw/more_infor.php?p_id=36"},
    # {"name": "仁愛國小", "base_url": "https://www.japs.tp.edu.tw/", "list_url": "https://www.japs.tp.edu.tw/nss/main/freeze/5a9759adef37531ea27bf1b0/Cqfg8H21612"},
    # {"name": "信義國小", "base_url": "https://www.syes.tp.edu.tw/", "list_url": "https://www.syes.tp.edu.tw/nss/main/freeze/5abf2d62aa93092cee58ceb4/N84R5hZ3727"}
]

if st.button("🔄 立即更新資料", type="primary"):
    st.cache_data.clear()
    st.rerun()

all_data = []
all_logs = {}

with st.spinner(f'正在掃描並翻頁 (最多 {max_pages_input} 頁)...'):
    for school in SCHOOL_LIST:
        scraper = SchoolScraper(school['name'], school['list_url'], school['base_url'], debug_mode=debug_mode)
        # 傳入 max_pages 參數
        data, logs = scraper.fetch_data(days_limit=days_limit_input, max_pages=max_pages_input)
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

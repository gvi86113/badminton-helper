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

# --- 爬蟲核心邏輯 ---
class SchoolScraper:
    def __init__(self, name, list_url, base_url, debug_mode=False):
        self.name = name
        self.list_url = list_url
        self.base_url = base_url
        self.debug = debug_mode
        self.logs = [] # 儲存 Log

    def log(self, msg):
        if self.debug:
            # 加上時間戳記方便追蹤
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{timestamp}] [{self.name}] {msg}")

    def fetch_data(self, days_limit=120):
        results = []
        try:
            self.log(f"開始請求網址: {self.list_url}")
            # 加入 Timeout 防止卡住，並模擬瀏覽器 User-Agent
            response = requests.get(self.list_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
            }, timeout=20)
            
            self.log(f"HTTP 狀態碼: {response.status_code}")
            
            if response.status_code != 200:
                self.log("❌ 請求失敗，跳過此學校")
                return [], self.logs
            
            # 根據學校類型選擇解析器
            if "syajh" in self.base_url:
                raw_items = self._parse_xingya(response.text)
            elif "nss" in self.list_url:
                raw_items = self._parse_nss(response.text)
            else:
                raw_items = []

            self.log(f"頁面解析完成，共抓到 {len(raw_items)} 個潛在項目 (未過濾)")
            
            # 開始過濾資料
            filtered_results = []
            # 計算截止日期 (今天 - N天)
            limit_date = get_current_time() - timedelta(days=days_limit)
            
            for item in raw_items:
                # 日期解析
                item_date = parse_taiwan_date(item['date'])
                item['parsed_date'] = item_date
                
                # 簡短標題用於 Log
                short_title = (item['title'][:10] + '..') if len(item['title']) > 10 else item['title']
                debug_info = f"標題: {short_title} | 日期: {item['date']}"

                if not item_date:
                    self.log(f"❌ 日期格式錯誤: {debug_info}")
                    continue

                # 計算這則公告距今幾天
                days_diff = (get_current_time() - item_date).days
                
                # 關鍵字檢查 (寬鬆過濾)
                # 只要標題含有 "羽球" 或 "租借" 都先列入觀察
                has_keyword = "羽球" in item['title']
                
                # 判斷是否過期 (注意：未來的公告 item_date > limit_date 恆成立，所以未來的也會被抓進來，這是正確的)
                if item_date > limit_date:
                    if has_keyword:
                        filtered_results.append(item)
                        self.log(f"✅ 保留: {debug_info}")
                    else:
                         self.log(f"⚠️ 捨棄 (無關鍵字): {debug_info}")
                else:
                    self.log(f"⏳ 捨棄 (過期): {debug_info} (距今 {days_diff} 天)")
            
            return filtered_results, self.logs
            
        except Exception as e:
            self.log(f"🔥 發生嚴重錯誤: {str(e)}")
            return [], self.logs

    def _parse_xingya(self, html):
        """
        興雅國中解析器 (針對 RWD 改版優化)
        策略：不找 Table，直接找所有連結，並往父層搜尋日期字串
        """
        soup = BeautifulSoup(html, 'html.parser')
        items = []
        
        # 1. 抓出所有帶有 href 的連結
        all_links = soup.find_all('a', href=True)
        self.log(f"掃描到 {len(all_links)} 個連結，開始分析結構...")
        
        for link in all_links:
            title = link.get_text(strip=True)
            url = link['href']
            
            # 過濾掉明顯不是公告的連結 (例如 "回首頁", "更多", "如果是空字串")
            if len(title) < 4:
                continue
                
            # 2. 往上找父層元素來抓日期
            # 興雅的日期通常在連結的旁邊，或是上一層 div 裡
            try:
                # 抓取該連結所在的「容器」文字
                # parent 是上一層，parent.parent 是上上一層 (通常能涵蓋整行)
                container = link.parent
                row_text = container.get_text()
                
                # 如果上一層文字太少，可能排版比較深，再往上一層找
                if len(row_text) < 20 and link.parent.parent:
                     container = link.parent.parent
                     row_text = container.get_text()

                # 使用 Regex 抓取日期 (格式: 2025-11-21 或 113-11-21)
                # 這裡針對興雅截圖看到的 2025-11-21 做優化
                date_match = re.search(r'\d{4}-\d{2}-\d{2}', row_text)
                
                if date_match:
                    date_str = date_match.group(0)
                    full_url = urljoin(self.base_url, url)
                    
                    items.append({
                        "school": self.name,
                        "date": date_str,
                        "title": title,
                        "url": full_url
                    })
            except Exception:
                # 結構如果不對就跳過，不影響其他連結
                continue

        # 去除重複 (RWD 頁面常會有電腦版/手機版兩個一樣的連結)
        seen = set()
        unique_items = []
        for item in items:
            if item['url'] not in seen:
                seen.add(item['url'])
                unique_items.append(item)
                
        return unique_items

    def _parse_nss(self, html):
        """
        NSS 系統解析器 (仁愛、信義)
        """
        soup = BeautifulSoup(html, 'html.parser')
        items = []
        all_links = soup.find_all('a', href=True)
        
        for a_tag in all_links:
            # 嘗試往上找日期
            container = a_tag.parent.parent if a_tag.parent else a_tag
            text_context = container.get_text()
            
            # 支援 2024/11/20 或 2024-11-20
            date_match = re.search(r'\d{4}[-/]\d{2}[-/]\d{2}', text_context)
            
            if date_match:
                title = a_tag.get_text(strip=True)
                if len(title) > 4:
                    items.append({
                        "school": self.name,
                        "date": date_match.group(0),
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

# --- Streamlit 前端介面 ---

st.set_page_config(page_title="台北市學校羽球公告彙整", layout="wide", page_icon="🏸")

# 側邊欄設定
st.sidebar.title("⚙️ 設定與除錯")
debug_mode = st.sidebar.checkbox("開啟工程師除錯模式 (Show Logs)", value=True)
# 預設天數設為 400，避免因為系統時間與公告時間跨年導致看不到
days_limit_input = st.sidebar.number_input("搜尋天數範圍 (天)", value=400, min_value=30, step=30) 

st.title("🏸 台北市學校羽球場地公告")
st.caption(f"目前系統時間 (台北): {get_current_time().strftime('%Y-%m-%d %H:%M')}")

# 定義學校清單
# 註解掉暫時有問題的學校，先專注修復興雅
SCHOOL_LIST = [
    {
        "name": "興雅國中", 
        "base_url": "https://www.syajh.tp.edu.tw/", 
        "list_url": "https://www.syajh.tp.edu.tw/more_infor.php?p_id=36"
    },
    # {
    #     "name": "仁愛國小", 
    #     "base_url": "https://www.japs.tp.edu.tw/", 
    #     "list_url": "https://www.japs.tp.edu.tw/nss/main/freeze/5a9759adef37531ea27bf1b0/Cqfg8H21612"
    # },
    # {
    #     "name": "信義國小", 
    #     "base_url": "https://www.syes.tp.edu.tw/", 
    #     "list_url": "https://www.syes.tp.edu.tw/nss/main/freeze/5abf2d62aa93092cee58ceb4/N84R5hZ3727"
    # }
]

if st.button("🔄 立即更新資料", type="primary"):
    st.cache_data.clear()
    st.rerun()

all_data = []
all_logs = {}

# 執行爬蟲
with st.spinner('機器人正在掃描學校官網...'):
    for school in SCHOOL_LIST:
        scraper = SchoolScraper(school['name'], school['list_url'], school['base_url'], debug_mode=debug_mode)
        data, logs = scraper.fetch_data(days_limit=days_limit_input)
        all_data.extend(data)
        all_logs[school['name']] = logs

# 顯示結果區
if not all_data:
    st.warning(f"近 {days_limit_input} 天內沒有找到含有「羽球」關鍵字的公告。請檢查除錯日誌。")
else:
    # 轉換成 DataFrame 方便處理
    df = pd.DataFrame(all_data)
    # 依照日期排序 (新 -> 舊)
    df = df.sort_values(by='parsed_date', ascending=False)
    
    st.success(f"共找到 {len(df)} 筆公告")
    
    # 卡片式顯示
    for index, row in df.iterrows():
        with st.container(border=True):
            col1, col2 = st.columns([1, 5])
            with col1:
                st.markdown(f"**{row['school']}**")
                # 顯示日期 (如果有 parsing 成功)
                date_display = row['date']
                st.caption(f"📅 {date_display}")
            with col2:
                st.markdown(f"#### [{row['title']}]({row['url']})")
                # 可以在這裡加入更多資訊，例如 "距今 X 天"
                if row['parsed_date']:
                    days_ago = (get_current_time() - row['parsed_date']).days
                    if days_ago < 0:
                        st.caption(f"未來公告 ({-days_ago} 天後)")
                    else:
                        st.caption(f"{days_ago} 天前發布")

# 顯示除錯 Log
if debug_mode:
    st.markdown("---")
    st.subheader("🛠️ 工程師除錯日誌 (Debug Logs)")
    for school_name, logs in all_logs.items():
        with st.expander(f"{school_name} - 執行紀錄", expanded=True):
            for log in logs:
                if "❌" in log or "🔥" in log:
                    st.error(log)
                elif "⚠️" in log or "⏳" in log:
                    st.warning(log)
                elif "✅" in log:
                    st.success(log)
                else:
                    st.text(log)

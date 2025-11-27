def _parse_xingya(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        items = []
        
        # 策略：不找表格，直接找頁面上所有的連結
        # 因為截圖顯示標題本身就是連結
        all_links = soup.find_all('a', href=True)
        self.log(f"頁面上共有 {len(all_links)} 個連結，開始過濾...")
        
        for link in all_links:
            title = link.get_text(strip=True)
            url = link['href']
            
            # 1. 先過濾標題長度，太短的通常是導覽列 (如 "首頁", "更多")
            if len(title) < 5:
                continue
                
            # 2. 往上找父層元素來抓日期
            # 截圖中的日期 (2025-11-21) 在連結的旁邊
            # 我們往上找 3 層父元素 (parent)，通常就能涵蓋到日期區塊
            # 這是最通用的抓法，不管它是 table 還是 div
            try:
                # 抓取該連結所在的「整行」文字
                row_container = link.parent.parent 
                row_text = row_container.get_text() if row_container else ""
                
                # 如果往上兩層沒抓到，再往上一層試試看 (有的排版比較深)
                if len(row_text) < 20: 
                     row_text = link.parent.parent.parent.get_text()

                # 使用 Regex 抓取日期 (格式: 2025-11-21)
                date_match = re.search(r'\d{4}-\d{2}-\d{2}', row_text)
                
                if date_match:
                    date_str = date_match.group(0)
                    
                    # 組合完整連結
                    full_url = urljoin(self.base_url, url)
                    
                    items.append({
                        "school": self.name,
                        "date": date_str,
                        "title": title,
                        "url": full_url
                    })
            except Exception:
                continue # 如果結構異常就跳過這個連結

        # 去除重複 (有時候 RWD 網頁會有兩個一樣的連結)
        seen = set()
        unique_items = []
        for item in items:
            if item['url'] not in seen:
                seen.add(item['url'])
                unique_items.append(item)
                
        return unique_items

import os
import json
import time
import urllib.parse
import pandas as pd
import requests
import re
from bs4 import BeautifulSoup
from datetime import datetime

# --- 設定區 ---
EXCEL_PATH = os.path.join("public", "drugs.xlsx")
JSON_DB_PATH = os.path.join("public", "data.json")
BASE_URL = "https://mcp.fda.gov.tw"
MAX_CHAR_LIMIT = 15000  # 限制每個藥品最多存 1.5 萬字 (電子仿單通常不會超過這數字)

def clean_text(text):
    """
    強力清潔工：只保留有意義的仿單文字
    """
    if not text: return ""
    
    # 1. 將多個連續換行變為單一換行
    text = re.sub(r'\n\s*\n', '\n', text)
    # 2. 去除多餘的空白
    text = re.sub(r'[ \t]+', ' ', text)
    
    # 3. 如果文字還是太長，強制截斷 (防止檔案爆炸)
    if len(text) > MAX_CHAR_LIMIT:
        text = text[:MAX_CHAR_LIMIT] + "\n... (內容過長已截斷) ..."
        
    return text.strip()

def fetch_fda_html_only(license_id):
    """
    只抓取電子仿單 (HTML)
    """
    safe_license = urllib.parse.quote(license_id)
    url = f"{BASE_URL}/im_detail_1/{safe_license}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0"
    }
    
    print(f"    檢查: {license_id} ...")
    
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code != 200:
            return f"連線錯誤 (Code {res.status_code})"
            
        soup = BeautifulSoup(res.text, 'html.parser')

        # 1. 移除網頁上的雜訊 (導覽列、頁尾、腳本、樣式)
        # 這一步非常重要，能大幅減少檔案大小
        for junk in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe", "svg"]):
            junk.extract()

        # 2. 鎖定內容區塊
        # 衛福部網站通常將內容放在 class="im_detail_content" 或類似的容器中
        # 如果找不到，我們就抓 body，但前面已經清除了大部分雜訊
        content_div = soup.find('div', class_='im_detail_content')
        
        if not content_div:
            # 嘗試另一個常見的容器 class (以防改版)
            content_div = soup.find('div', class_='container')
        
        # 如果還是找不到特定容器，就用整個 body
        if not content_div:
            content_div = soup.body

        if not content_div:
            return "無法解析網頁結構"

        # 3. 提取文字
        page_text = content_div.get_text(separator='\n')
        
        # ==========================================
        # 🚨 [新增] 垃圾頁面過濾器 🚨
        # 如果抓到的文字包含這些「搜尋頁面」的特徵詞，代表連結失效了，被導回首頁
        # 這樣就不會存入一堆「阿曼、巴貝多...」的無用國家列表
        if "西藥品仿單資料查詢" in page_text and "許可證字號查詢" in page_text:
            return "查無電子仿單資料 (連結失效或已下架)"
        # ==========================================
        
        # 4. 驗證是否真的有仿單內容 (避免抓到其他種類的空頁面)
        # 檢查是否包含關鍵字
        keywords = ["適應症", "用法用量", "警語", "副作用", "禁忌", "交互作用", "劑型"]
        hit_count = sum(1 for k in keywords if k in page_text)
        
        if hit_count >= 1:
            # 是一個有效的電子仿單
            return clean_text(page_text)
        else:
            return "此藥品無電子仿單資料 (可能僅有 PDF)"

    except Exception as e:
        return f"讀取失敗: {str(e)}"

def main():
    print("=== 電子仿單監測系統 (HTML Only) ===")
    
    if not os.path.exists(EXCEL_PATH):
        print(f"找不到 {EXCEL_PATH}")
        return

    try:
        df = pd.read_excel(EXCEL_PATH)
        df['許可證字號'] = df['許可證字號'].astype(str).str.strip()
    except Exception as e:
        print(f"Excel 讀取失敗: {e}")
        return

    # 讀取舊資料庫 (如果檔案太大壞掉，就重開一個)
    if os.path.exists(JSON_DB_PATH):
        try:
            with open(JSON_DB_PATH, 'r', encoding='utf-8') as f:
                db = json.load(f)
                old_items = {item['license']: item for item in db['items']}
        except:
            print("舊資料庫損毀或格式不符，將建立新資料庫。")
            old_items = {}
    else:
        old_items = {}

    new_items_list = []

    for index, row in df.iterrows():
        lic_id = row['許可證字號']
        drug_name = row['藥名']
        drug_code = row['院內代碼']
        
        # 執行新的抓取邏輯
        current_text = fetch_fda_html_only(lic_id)
        
        old_record = old_items.get(lic_id, {})
        old_text = old_record.get('current_text', "")
        last_change = old_record.get('last_change_date', datetime.now().strftime('%Y-%m-%d'))
        
        is_changed = False
        # 比對邏輯：只有當新舊都有文字，且不相同時才算異動
        if old_text and current_text != old_text:
            # 排除掉「無電子仿單」或「查無資料」這種系統訊息的變動
            # 如果兩邊都是系統訊息，就不算異動
            system_msgs = ["無電子仿單", "查無電子仿單資料"]
            
            is_new_sys_msg = any(msg in current_text for msg in system_msgs)
            is_old_sys_msg = any(msg in old_text for msg in system_msgs)

            # 如果新舊文字包含系統訊息，我們稍微放寬標準
            # 只有當「真正內容」變成「系統訊息」（下架），或「系統訊息」變成「真正內容」（上架）才算
            # 但為了簡單起見，只要文字不同，且不是純粹的格式差異，就算異動
            # 這裡我們維持您原本的邏輯，但加上對新訊息的排除
            
            if not (is_new_sys_msg and is_old_sys_msg):
                 is_changed = True
                 last_change = datetime.now().strftime('%Y-%m-%d')
                 print(f"    [!] 發現異動: {drug_name}")
        
        if not old_text:
            old_text = current_text 

        new_items_list.append({
            "code": drug_code,
            "name": drug_name,
            "license": lic_id,
            "fda_url": f"{BASE_URL}/im_detail_1/{urllib.parse.quote(lic_id)}",
            "old_text": old_text if is_changed else current_text,
            "current_text": current_text,
            "is_changed": is_changed,
            "last_change_date": last_change
        })
        
        # 稍微暫停一下，對伺服器溫柔一點
        time.sleep(0.5)

    final_data = {
        "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "items": new_items_list
    }
    
    # 檢查最終檔案大小
    json_str = json.dumps(final_data, ensure_ascii=False, indent=2)
    print(f"資料庫大小預估: {len(json_str)/1024/1024:.2f} MB")

    with open(JSON_DB_PATH, 'w', encoding='utf-8') as f:
        f.write(json_str)
        
    print(f"更新完成")

if __name__ == "__main__":
    main()

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

# ✅ 放寬限制：改成 3 萬字，讓您能看到完整內容
# 透過下面的「空間節省邏輯」，我們有本錢存這麼多字！
MAX_CHAR_LIMIT = 30000 

def clean_text(text):
    """
    強力清潔工：只保留有意義的仿單文字
    """
    if not text: return ""
    
    # 1. 將多個連續換行變為單一換行
    text = re.sub(r'\n\s*\n', '\n', text)
    # 2. 去除多餘的空白
    text = re.sub(r'[ \t]+', ' ', text)
    
    # 3. 安全閥：雖然放寬了，還是要防範那種 100 萬字的異常資料
    if len(text) > MAX_CHAR_LIMIT:
        text = text[:MAX_CHAR_LIMIT] + f"\n... (內容過長，僅顯示前 {MAX_CHAR_LIMIT} 字) ..."
        
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

        # 1. 移除網頁上的雜訊
        for junk in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe", "svg"]):
            junk.extract()

        # 2. 鎖定內容區塊
        content_div = soup.find('div', class_='im_detail_content')
        if not content_div:
            content_div = soup.find('div', class_='container')
        if not content_div:
            content_div = soup.body

        if not content_div:
            return "無法解析網頁結構"

        # 3. 提取文字
        page_text = content_div.get_text(separator='\n')
        
        # 🚨 垃圾頁面過濾器 (保留這個功能，這也是省空間的關鍵)
        if "西藥品仿單資料查詢" in page_text and "許可證字號查詢" in page_text:
            return "查無電子仿單資料 (連結失效或已下架)"
        
        # 4. 驗證是否真的有仿單內容
        keywords = ["適應症", "用法用量", "警語", "副作用", "禁忌", "交互作用", "劑型"]
        hit_count = sum(1 for k in keywords if k in page_text)
        
        if hit_count >= 1:
            return clean_text(page_text)
        else:
            return "此藥品無電子仿單資料 (可能僅有 PDF)"

    except Exception as e:
        return f"讀取失敗: {str(e)}"

def main():
    print("=== 電子仿單監測系統 (Smart Save Mode) ===")
    
    if not os.path.exists(EXCEL_PATH):
        print(f"找不到 {EXCEL_PATH}")
        return

    try:
        df = pd.read_excel(EXCEL_PATH)
        df['許可證字號'] = df['許可證字號'].astype(str).str.strip()
    except Exception as e:
        print(f"Excel 讀取失敗: {e}")
        return

    # 讀取舊資料庫
    if os.path.exists(JSON_DB_PATH):
        try:
            with open(JSON_DB_PATH, 'r', encoding='utf-8') as f:
                db = json.load(f)
                old_items = {item['license']: item for item in db['items']}
        except:
            print("舊資料庫損毀，將建立新資料庫。")
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
        
        # 💡 [關鍵邏輯] 還原舊資料
        # 如果資料庫裡的 old_text 是空的 (因為上次為了省空間沒存)，
        # 代表上次沒有異動，所以「舊的 old_text」其實就是「資料庫裡的 current_text」。
        saved_old_text = old_record.get('old_text', "")
        if not saved_old_text:
             saved_old_text = old_record.get('current_text', "")

        last_change = old_record.get('last_change_date', datetime.now().strftime('%Y-%m-%d'))
        
        is_changed = False
        
        # 比對邏輯
        if saved_old_text and current_text != saved_old_text:
            system_msgs = ["無電子仿單", "查無電子仿單資料"]
            is_new_sys_msg = any(msg in current_text for msg in system_msgs)
            is_old_sys_msg = any(msg in saved_old_text for msg in system_msgs)
            
            if not (is_new_sys_msg and is_old_sys_msg):
                 is_changed = True
                 last_change = datetime.now().strftime('%Y-%m-%d')
                 print(f"    [!] 發現異動: {drug_name}")
        
        # 如果是第一次執行，把舊資料設為跟新的一樣
        if not saved_old_text:
            saved_old_text = current_text 

        # ==========================================
        # 🚨 [核心修正] 智慧省空間邏輯 🚨
        # 1. 只有當「is_changed 為 True」時，我們才存 old_text。
        # 2. 如果沒異動，old_text 存成空字串 ""。
        # 3. 這樣可以節省 50% 的空間，讓我們可以放心地把字數限制調大！
        # ==========================================
        new_items_list.append({
            "code": drug_code,
            "name": drug_name,
            "license": lic_id,
            "fda_url": f"{BASE_URL}/im_detail_1/{urllib.parse.quote(lic_id)}",
            
            "old_text": saved_old_text if is_changed else "", # ✅ 省空間關鍵
            "current_text": current_text,
            
            "is_changed": is_changed,
            "last_change_date": last_change
        })
        
        time.sleep(0.5)

    final_data = {
        "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "items": new_items_list
    }
    
    json_str = json.dumps(final_data, ensure_ascii=False, indent=2)
    print(f"資料庫大小預估: {len(json_str)/1024/1024:.2f} MB")

    with open(JSON_DB_PATH, 'w', encoding='utf-8') as f:
        f.write(json_str)
        
    print(f"更新完成")

if __name__ == "__main__":
    main()

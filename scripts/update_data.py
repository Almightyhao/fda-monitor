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

# ✅ 字數限制：既然我們已經切掉最佔空間的臨床資料，
# 剩下的「適應症、副作用」通常不會超過 1.5 萬字，這裡設個 20000 當作最後一道防線即可。
MAX_CHAR_LIMIT = 20000 

def clean_text(text):
    """
    強力清潔工：只保留有意義的仿單文字，並切除後段學術資料
    """
    if not text: return ""
    
    # 1. 將多個連續換行變為單一換行
    text = re.sub(r'\n\s*\n', '\n', text)
    # 2. 去除多餘的空白
    text = re.sub(r'[ \t]+', ' ', text)
    
    # ==========================================
    # ✂️ [新增] 手術刀切除法：排除後段學術資料 ✂️
    # ==========================================
    # 這些關鍵字通常出現在仿單的後大半段，我們一看到就切斷
    # 包含全形數字、半形數字、或純文字標題，盡量涵蓋各種寫法
    cut_off_keywords = [
        "10 藥理特性", "10.藥理特性", "10. 藥理特性", "拾、藥理特性",
        "11 藥物動力學", "11.藥物動力學", "11. 藥物動力學", "拾壹、藥物動力學",
        "12 臨床試驗", "12.臨床試驗", "12. 臨床試驗", "拾貳、臨床試驗",
        "藥理特性", "藥物動力學特性", "臨床試驗資料" # 最後用純關鍵字兜底
    ]
    
    # 尋找這些關鍵字中，最早出現的位置
    earliest_cut_index = -1
    cut_reason = ""
    
    for keyword in cut_off_keywords:
        idx = text.find(keyword)
        # 如果找到了，且比目前找到的更前面 (或還沒找到過)
        if idx != -1:
            # 確保不是在文章開頭就被切掉 (例如目錄區)，我們假設這些章節至少在 500 字以後
            if idx > 100: 
                if earliest_cut_index == -1 or idx < earliest_cut_index:
                    earliest_cut_index = idx
                    cut_reason = keyword

    # 如果有找到切點，就執行切除
    if earliest_cut_index != -1:
        text = text[:earliest_cut_index]
        text += f"\n\n--- (已省略「{cut_reason}」及後續詳細資料以節省空間) ---"

    # ==========================================
    
    # 3. 最後防線：如果切完還是太長 (極少見)，再強制截斷
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
        
        # 🚨 垃圾頁面過濾器
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
    print("=== 電子仿單監測系統 (Extreme Save Mode) ===")
    
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
        
        current_text = fetch_fda_html_only(lic_id)
        
        old_record = old_items.get(lic_id, {})
        
        # 還原舊資料邏輯 (對應上次的省空間邏輯)
        saved_old_text = old_record.get('old_text', "")
        if not saved_old_text:
             saved_old_text = old_record.get('current_text', "")

        last_change = old_record.get('last_change_date', datetime.now().strftime('%Y-%m-%d'))
        
        is_changed = False
        
        if saved_old_text and current_text != saved_old_text:
            system_msgs = ["無電子仿單", "查無電子仿單資料"]
            is_new_sys_msg = any(msg in current_text for msg in system_msgs)
            is_old_sys_msg = any(msg in saved_old_text for msg in system_msgs)
            
            if not (is_new_sys_msg and is_old_sys_msg):
                 is_changed = True
                 last_change = datetime.now().strftime('%Y-%m-%d')
                 print(f"    [!] 發現異動: {drug_name}")
        
        if not saved_old_text:
            saved_old_text = current_text 

        new_items_list.append({
            "code": drug_code,
            "name": drug_name,
            "license": lic_id,
            "fda_url": f"{BASE_URL}/im_detail_1/{urllib.parse.quote(lic_id)}",
            # 只在異動時存舊資料
            "old_text": saved_old_text if is_changed else "", 
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

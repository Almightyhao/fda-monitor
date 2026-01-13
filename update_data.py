import os
import json
import time
import io
import urllib.parse
import pandas as pd
import requests
import pdfplumber
from bs4 import BeautifulSoup
from datetime import datetime

# --- 設定區 ---
# 檔案路徑 (相對於腳本執行位置)
EXCEL_PATH = os.path.join("public", "drugs.xlsx")
JSON_DB_PATH = os.path.join("public", "data.json")
BASE_URL = "https://mcp.fda.gov.tw"

def fetch_fda_content(license_id):
    """
    核心功能：輸入許可證號，回傳該藥品的仿單文字內容。
    """
    # 1. 編碼許可證號 (處理中文網址)
    safe_license = urllib.parse.quote(license_id)
    url = f"{BASE_URL}/im_detail_1/{safe_license}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0"
    }
    
    print(f"   正在檢查: {license_id} ...")
    
    try:
        # 2. 請求網頁
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return f"錯誤: 無法連線至 FDA (Code {res.status_code})"
            
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 3. 尋找 PDF 連結 (邏輯：含有 .pdf 且文字包含 '仿單' 或連結包含 'insert')
        pdf_url = None
        for a in soup.find_all('a', href=True):
            href = a['href']
            text = a.get_text()
            if '.pdf' in href.lower() and ('仿單' in text or 'insert' in href.lower()):
                pdf_url = urllib.parse.urljoin(BASE_URL, href)
                break
        
        if not pdf_url:
            # 如果找不到 PDF，嘗試抓取網頁上的純文字描述
            return "系統提示：未找到仿單 PDF 連結，請確認衛福部網站是否僅提供圖片。"

        # 4. 下載並解析 PDF
        print(f"   -> 發現 PDF，正在解析文字...")
        pdf_res = requests.get(pdf_url, headers=headers, timeout=20)
        
        full_text = []
        with pdfplumber.open(io.BytesIO(pdf_res.content)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text.append(text)
        
        if not full_text:
            return "系統提示：PDF 為掃描檔圖片，無法提取文字。"
            
        return "\n".join(full_text)

    except Exception as e:
        return f"讀取失敗: {str(e)}"

def main():
    print("=== 仿單異動監測系統啟動 ===")
    
    # 1. 讀取 Excel 清單
    if not os.path.exists(EXCEL_PATH):
        print(f"錯誤：找不到 {EXCEL_PATH}，請確認檔案位置。")
        return

    try:
        df = pd.read_excel(EXCEL_PATH)
        # 確保將欄位轉為字串並去除空白
        df['許可證字號'] = df['許可證字號'].astype(str).str.strip()
    except Exception as e:
        print(f"讀取 Excel 失敗: {e}")
        return

    # 2. 讀取舊資料 (Database)
    if os.path.exists(JSON_DB_PATH):
        with open(JSON_DB_PATH, 'r', encoding='utf-8') as f:
            db = json.load(f)
            old_items = {item['license']: item for item in db['items']}
    else:
        db = {"items": []}
        old_items = {}

    new_items_list = []
    has_update = False

    # 3. 逐一檢查藥品
    for index, row in df.iterrows():
        lic_id = row['許可證字號']
        drug_name = row['藥名']
        drug_code = row['院內代碼']
        
        # 取得最新文字
        current_text = fetch_fda_content(lic_id)
        
        # 取出舊紀錄
        old_record = old_items.get(lic_id, {})
        old_text = old_record.get('current_text', "")
        last_change = old_record.get('last_change_date', datetime.now().strftime('%Y-%m-%d'))
        
        # 判斷異動 (如果是新藥品，或者文字真的變了)
        is_changed = False
        # 只有當舊文字存在，且新文字與舊文字不同時，才算異動
        if old_text and current_text != old_text:
            is_changed = True
            last_change = datetime.now().strftime('%Y-%m-%d')
            has_update = True
            print(f"   [!] 發現異動：{drug_name}")
        
        # 如果是第一次執行 (沒有舊文字)，我們把現在的當作基準，不算異動
        if not old_text:
            old_text = current_text 

        new_items_list.append({
            "code": drug_code,
            "name": drug_name,
            "license": lic_id,
            "fda_url": f"{BASE_URL}/im_detail_1/{urllib.parse.quote(lic_id)}",
            "old_text": old_text if is_changed else current_text, # 若無異動，左右顯示一樣
            "current_text": current_text,
            "is_changed": is_changed,
            "last_change_date": last_change
        })
        
        # 禮貌性延遲，避免被 FDA 封鎖
        time.sleep(1)

    # 4. 存檔
    final_data = {
        "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "items": new_items_list
    }
    
    with open(JSON_DB_PATH, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)
        
    print(f"\n=== 檢查完成 ===")
    print(f"資料已更新至 {JSON_DB_PATH}")

if __name__ == "__main__":
    main()
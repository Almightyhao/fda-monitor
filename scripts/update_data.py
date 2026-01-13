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

# ... (前面的 import 不變) ...

def fetch_fda_content(license_id):
    """
    智慧雙引擎：
    1. 優先嘗試抓取「電子仿單」(HTML 文字)。
    2. 如果沒有電子仿單，則啟動「PDF 引擎」下載並解析。
    """
    safe_license = urllib.parse.quote(license_id)
    url = f"{BASE_URL}/im_detail_1/{safe_license}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0"
    }
    
    print(f"   正在檢查: {license_id} ...")
    
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code != 200:
            return f"錯誤: 無法連線 (Code {res.status_code})"
            
        soup = BeautifulSoup(res.text, 'html.parser')

        # === 引擎 A：電子仿單偵測 (針對新藥) ===
        # 邏輯：檢查頁面上是否有「詳細內容」的區塊，且包含關鍵字
        # 這裡我們嘗試抓取通常存放內容的 div (需依實際狀況微調，這裡用通用的抓法)
        
        # 移除 scripts 和 styles，避免抓到亂碼
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.extract()

        page_text = soup.get_text(separator='\n')
        
        # 簡單判斷：如果網頁純文字裡包含大量仿單特徵詞，就當作是電子仿單
        keywords = ["適應症", "用法用量", "警語", "副作用"]
        keyword_hits = sum(1 for k in keywords if k in page_text)
        
        # 如果命中 2 個以上關鍵字，且文字長度夠長，我們假設這就是電子仿單
        # (注意：我們會嘗試去除前後的網站選單雜訊)
        if keyword_hits >= 2 and len(page_text) > 500:
            print("   -> 偵測到電子仿單 (HTML)")
            
            # 這裡做一個簡單的清理，只保留核心內容區塊
            # 嘗試定位主要內容容器 (常見的 class 如 main-content, container 等)
            # 如果找不到特定 class，就回傳清理過的全頁文字
            content_div = soup.find('div', class_='im_detail_content') # 假設的 class 名稱
            
            if content_div:
                return content_div.get_text(separator='\n').strip()
            else:
                # 若無法精確定位，則回傳全部文字，但用正則表達式或切片稍微清理頭尾
                # 這裡暫時回傳全頁文字供比對 (Diff 工具會幫你濾掉沒變的 Header/Footer)
                return page_text.strip()

        # === 引擎 B：PDF 下載 (針對舊藥) ===
        print("   -> 未發現電子仿單，切換至 PDF 模式...")
        
        pdf_url = None
        for a in soup.find_all('a', href=True):
            href = a['href']
            text = a.get_text()
            # 寬鬆判斷：只要連結是 PDF 且文字像仿單
            if '.pdf' in href.lower() and ('仿單' in text or 'insert' in href.lower() or '說明書' in text):
                pdf_url = urllib.parse.urljoin(BASE_URL, href)
                break
        
        if not pdf_url:
            return "系統提示：此藥品無電子仿單，亦無 PDF 檔可下載。"

        print(f"   -> 正在下載 PDF: {pdf_url} ...")
        pdf_res = requests.get(pdf_url, headers=headers, timeout=30)
        
        full_text = []
        with pdfplumber.open(io.BytesIO(pdf_res.content)) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    full_text.append(extracted)
        
        if not full_text:
            return "系統提示：PDF 為掃描圖片，無法辨識文字。"
            
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

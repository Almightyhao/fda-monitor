import os
import json
import time
import io
import urllib.parse
import pandas as pd
import requests
import pdfplumber
import re  # 新增正則表達式套件
from bs4 import BeautifulSoup
from datetime import datetime

# --- 設定區 ---
EXCEL_PATH = os.path.join("public", "drugs.xlsx")
JSON_DB_PATH = os.path.join("public", "data.json")
BASE_URL = "https://mcp.fda.gov.tw"
MAX_CHAR_LIMIT = 30000  # 限制每個藥品最多存 3 萬字 (避免檔案爆炸)

def clean_text(text):
    """
    清理文字的強力吸塵器：去除多餘空行、HTML雜訊
    """
    if not text: return ""
    # 1. 去除連續的換行和空白
    text = re.sub(r'\n\s*\n', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    # 2. 強制截斷過長的內容
    if len(text) > MAX_CHAR_LIMIT:
        text = text[:MAX_CHAR_LIMIT] + "\n\n[...系統提示：內容過長，已自動截斷...]"
    return text.strip()

def fetch_fda_content(license_id):
    safe_license = urllib.parse.quote(license_id)
    url = f"{BASE_URL}/im_detail_1/{safe_license}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0"
    }
    
    print(f"   檢查: {license_id} ...")
    
    try:
        res = requests.get(url, headers=headers, timeout=20)
        if res.status_code != 200:
            return f"錯誤: Code {res.status_code}"
            
        soup = BeautifulSoup(res.text, 'html.parser')

        # === 引擎 A：電子仿單偵測 ===
        # 移除所有可能的干擾元素
        for script in soup(["script", "style", "nav", "footer", "header", "svg", "img", "iframe"]):
            script.extract()

        # 嘗試只抓取主要內容區塊 (根據經驗觀察)
        content_div = soup.find('div', class_='im_detail_content')
        if not content_div:
            # 如果找不到專屬區塊，就抓 body
            content_div = soup.body

        if content_div:
            page_text = content_div.get_text(separator='\n')
            
            # 判斷是否為有效內容
            keywords = ["適應症", "用法用量", "警語", "副作用"]
            if sum(1 for k in keywords if k in page_text) >= 2:
                print("   -> 抓取電子仿單")
                return clean_text(page_text)

        # === 引擎 B：PDF 下載 ===
        # print("   -> 無電子仿單，嘗試 PDF...") # 簡化 log
        
        pdf_url = None
        for a in soup.find_all('a', href=True):
            href = a['href']
            text = a.get_text()
            if '.pdf' in href.lower() and ('仿單' in text or 'insert' in href.lower() or '說明書' in text):
                pdf_url = urllib.parse.urljoin(BASE_URL, href)
                break
        
        if not pdf_url:
            return "無電子仿單或 PDF。"

        # 下載 PDF
        pdf_res = requests.get(pdf_url, headers=headers, timeout=30)
        full_text = []
        with pdfplumber.open(io.BytesIO(pdf_res.content)) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    full_text.append(extracted)
        
        if not full_text:
            return "PDF 為掃描檔，無法識別。"
            
        return clean_text("\n".join(full_text))

    except Exception as e:
        return f"失敗: {str(e)}"

def main():
    print("=== 仿單監測系統 (輕量版) ===")
    
    if not os.path.exists(EXCEL_PATH):
        print(f"找不到 {EXCEL_PATH}")
        return

    try:
        df = pd.read_excel(EXCEL_PATH)
        df['許可證字號'] = df['許可證字號'].astype(str).str.strip()
    except Exception as e:
        print(f"Excel 錯誤: {e}")
        return

    # 讀取舊資料
    old_items = {}
    if os.path.exists(JSON_DB_PATH):
        try:
            with open(JSON_DB_PATH, 'r', encoding='utf-8') as f:
                db = json.load(f)
                old_items = {item['license']: item for item in db['items']}
        except:
            print("舊資料庫損毀或過大，將建立新資料庫。")
            old_items = {}

    new_items_list = []

    for index, row in df.iterrows():
        lic_id = row['許可證字號']
        drug_name = row['藥名']
        drug_code = row['院內代碼']
        
        current_text = fetch_fda_content(lic_id)
        
        old_record = old_items.get(lic_id, {})
        old_text = old_record.get('current_text', "")
        last_change = old_record.get('last_change_date', datetime.now().strftime('%Y-%m-%d'))
        
        is_changed = False
        if old_text and current_text != old_text:
            is_changed = True
            last_change = datetime.now().strftime('%Y-%m-%d')
            print(f"   [!] 異動: {drug_name}")
        
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
        
        time.sleep(1)

    final_data = {
        "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "items": new_items_list
    }
    
    # 存檔前檢查大小
    json_str = json.dumps(final_data, ensure_ascii=False, indent=2)
    size_mb = len(json_str.encode('utf-8')) / (1024 * 1024)
    print(f"資料庫大小預估: {size_mb:.2f} MB")
    
    if size_mb > 95:
        print("警告：檔案仍超過 95MB，請減少 Excel 藥品數量！")

    with open(JSON_DB_PATH, 'w', encoding='utf-8') as f:
        f.write(json_str)
        
    print(f"更新完成")

if __name__ == "__main__":
    main()

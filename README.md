# 💊 藥品仿單異動監測系統 (FDA Drug Monitor)

這是一個自動化的藥品仿單監測系統，利用 **Python 爬蟲** 定期抓取衛福部食藥署資料，並透過 **React 前端** 以視覺化方式呈現仿單內容的異動比對。系統設計重點在於「智慧清理冗長學術資料」與「極致節省儲存空間」。

![Build Status](https://github.com/almightyhao/fda-monitor/actions/workflows/update_data.yml/badge.svg)

## ✨ 主要功能

* **🔄 自動化監測**：透過 GitHub Actions 每日自動執行爬蟲，無需人工介入。
* **🧹 智慧挖空 (Smart Hollow Mode)**：
    * 自動偵測並切除仿單中佔據大量空間的學術章節（第 10~12 章：藥理特性、臨床試驗）。
    * **智慧保留**：若偵測到後續有重要資訊（如第 13 章包裝、第 14 章病人須知），會自動保留頭尾，只挖空中間。
* **📉 極致省空間 (Smart Storage)**：
    * 僅在內容發生「實質異動」時才儲存舊資料。
    * 若無異動，歷史欄位自動清空，大幅減少 `data.json` 體積。
* **⚡ 前端效能優化**：
    * React 前端實作強制過濾，僅渲染有異動的項目，解決大量資料導致的瀏覽器卡頓問題。
* **📊 視覺化比對**：整合 `react-diff-viewer`，以紅/綠色塊清晰標示文字增刪差異。
* **📥 報表輸出**：支援一鍵匯出 Excel 異動報表。

## 🛠️ 技術架構

### Backend (Data Processing)
* **Python 3.x**
* `requests` & `BeautifulSoup4`: 網頁爬取與解析。
* `pandas`: 讀取 Excel 藥品清單。
* **核心邏輯**：位於 `scripts/update_data.py`。

### Frontend (User Interface)
* **React + Vite**
* `react-diff-viewer-continued`: 文字差異比對。
* `xlsx`: Excel 匯出功能。

### CI/CD
* **GitHub Actions**: 排程執行 (`cron`) 與自動部署 (`gh-pages`)。

## 📂 專案結構

```text
.
├── public/
│   ├── drugs.xlsx       # 監測的藥品清單 (來源)
│   └── data.json        # 爬蟲產出的資料庫 (結果)
├── src/
│   ├── App.jsx          # 前端主邏輯 (含效能過濾)
│   └── main.jsx         # React 入口
├── scripts/
│   └── update_data.py   # Python 爬蟲核心腳本
└── .github/workflows/
    └── update_data.yml  # 自動化流程設定

import { useState, useEffect } from 'react';
import ReactDiffViewer from 'react-diff-viewer-continued';
import * as XLSX from 'xlsx';

// --- 樣式設定：讓比對畫面更清楚 ---
const diffStyles = {
  variables: {
    light: {
      diffViewerBackground: '#fff',
      addedBackground: '#e6ffec',   // 新增文字底色 (綠)
      addedColor: '#24292e',
      removedBackground: '#ffebe9', // 刪除文字底色 (紅)
      removedColor: '#24292e',
      wordAddedBackground: '#acf2bd', // 強調異動文字
      wordRemovedBackground: '#fdb8c0',
    }
  }
};

function App() {
  const [data, setData] = useState({ items: [], last_updated: '載入中...' });
  const [viewMode, setViewMode] = useState('all'); // 'all' 或 'changed'

  // 1. 讀取 Python 產生的資料
  useEffect(() => {
    // 💡 修正重點：使用 Vite 提供的環境變數自動取得正確路徑
    // import.meta.env.BASE_URL 會自動讀取 vite.config.js 裡的 base 設定
    // 在本機它是 '/'，在 GitHub 它是 '/fda-monitor/' (若設定正確)
    const dataUrl = `${import.meta.env.BASE_URL}data.json`;

    console.log("正在讀取資料路徑:", dataUrl); // 除錯用，按 F12 看 Console

    fetch(dataUrl)
      .then((res) => {
        if (!res.ok) {
            // 如果還是 404，這裡會噴錯
            throw new Error(`找不到檔案 (Status: ${res.status})`);
        }
        return res.json();
      })
      .then((data) => {
        console.log("成功抓到資料:", data);
        
        // 確保資料結構正確 (您的 JSON 是包在 items 裡面)
        if (data.items) {
            setDrugs(data.items);
        } else if (Array.isArray(data)) {
            setDrugs(data);
        }
      })
      .catch((error) => {
        console.error("讀取失敗:", error);
      });
  }, []);

  // 2. Excel 下載邏輯
  const handleDownload = () => {
    const exportData = data.items.map(item => ({
      '院內代碼': item.code,
      '藥名': item.name,
      '許可證字號': item.license,
      '異動狀態': item.is_changed ? '有異動' : '無',
      '異動日期': item.last_change_date,
      '衛福部連結': item.fda_url
    }));

    const ws = XLSX.utils.json_to_sheet(exportData);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "異動報表");
    XLSX.writeFile(wb, `仿單異動檢查表_${new Date().toISOString().slice(0,10)}.xlsx`);
  };

  // 篩選顯示
  const displayItems = viewMode === 'changed' 
    ? data.items.filter(i => i.is_changed) 
    : data.items;

  return (
    <div style={{ padding: '20px', fontFamily: 'Arial, sans-serif', maxWidth: '1400px', margin: '0 auto' }}>
      
      {/* 標題區 */}
      <header style={{ marginBottom: '30px', borderBottom: '2px solid #eee', paddingBottom: '20px' }}>
        <h1 style={{ color: '#2c3e50' }}>💊 藥品仿單異動監測系統</h1>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ color: '#666' }}>最後更新：{data.last_updated}</span>
          <div>
            <button 
              onClick={() => setViewMode('all')}
              style={{ padding: '8px 16px', marginRight: '10px', cursor: 'pointer', background: viewMode==='all'?'#007bff':'#eee', color: viewMode==='all'?'white':'black', border:'none', borderRadius:'4px' }}>
              顯示全部
            </button>
            <button 
              onClick={() => setViewMode('changed')}
              style={{ padding: '8px 16px', marginRight: '10px', cursor: 'pointer', background: viewMode==='changed'?'#dc3545':'#eee', color: viewMode==='changed'?'white':'black', border:'none', borderRadius:'4px' }}>
              只看異動 ({data.items.filter(i=>i.is_changed).length})
            </button>
            <button 
              onClick={handleDownload}
              style={{ padding: '8px 16px', background: '#28a745', color: 'white', border: 'none', borderRadius:'4px', cursor: 'pointer' }}>
              📥 下載 Excel
            </button>
          </div>
        </div>
      </header>

      {/* 內容區 */}
      {displayItems.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '50px', color: '#999' }}>
          <h3>沒有符合條件的項目</h3>
        </div>
      ) : (
        displayItems.map((item) => (
          <div key={item.license} style={{ marginBottom: '40px', border: '1px solid #ddd', borderRadius: '8px', overflow: 'hidden', boxShadow: '0 2px 5px rgba(0,0,0,0.05)' }}>
            
            {/* 卡片標題 */}
            <div style={{ padding: '15px 20px', background: '#f8f9fa', borderBottom: '1px solid #ddd', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <strong style={{ fontSize: '1.2em', color: '#333' }}>{item.name}</strong> 
                <span style={{ margin: '0 10px', color: '#666', background: '#e9ecef', padding: '2px 8px', borderRadius: '4px', fontSize: '0.9em' }}>
                  {item.code}
                </span>
                <a href={item.fda_url} target="_blank" rel="noreferrer" style={{ fontSize: '0.9em', color: '#007bff' }}>
                  [開啟衛福部頁面]
                </a>
              </div>
              
              {item.is_changed && (
                <span style={{ background: '#dc3545', color: 'white', padding: '5px 10px', borderRadius: '20px', fontSize: '0.85em', fontWeight: 'bold' }}>
                  ⚠️ 發現異動 ({item.last_change_date})
                </span>
              )}
            </div>

            {/* 比對區塊 */}
            <div style={{ fontSize: '14px' }}>
              <ReactDiffViewer 
                oldValue={item.old_text} 
                newValue={item.current_text} 
                splitView={true}
                leftTitle="上次紀錄 (舊)"
                rightTitle="目前最新 (新)"
                styles={diffStyles}
                hideLineNumbers={false}
              />
            </div>
          </div>
        ))
      )}
    </div>
  );
}

export default App;

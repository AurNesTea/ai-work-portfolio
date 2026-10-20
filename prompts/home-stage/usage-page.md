# 用量改成獨立分頁

只做這件事。不要改 runner、不要改 workflow、不要用 `--print`。

## 現況

用量在首頁選單彈窗裡，`panel/src/MenuModal.tsx` 的 `activeView === "usage"`。彈窗最大寬度 680px（`panel/src/App.css` 的 `.modal-dialog`），表格被擠在小視窗。選單項目是代理、用量、主題。代理與主題維持彈窗。

## 要變成

1. 選單裡點「用量」：關掉選單，整頁換成用量分頁。不要再把表格畫在彈窗裡。
2. 用量分頁佔主畫面（與首頁同一層），月份選擇、說明、明細表、合計都留著。欄位與計算不要改：時間、執行、步驟、agent、模型、輸入、快取讀、快取寫、輸出、美元。空月份仍顯示「這個月尚無用量紀錄。」
3. 分頁上要有回到首頁。回到首頁後，下方 CLI 維持原本那一條，不要因為進出用量而重開或取消進行中的 run。
4. 代理、主題仍在原彈窗。漢堡選單仍從首頁右上角打開。
5. 不要新增路由套件。用現有的畫面狀態切換即可。

做完在這個檔案最底下補一段：改了哪些檔、用量怎麼從選單進到整頁。

另外必須回傳這次對話的實際用量，供紀錄。不要估算，用 CLI 這次工作結束時自己的統計。寫在同一個補段裡，欄位用這幾個名字：

- model
- input_tokens
- output_tokens
- cache_read_tokens
- cache_write_tokens
- thinking_tokens

沒有的數字寫 0。model 寫實際模型名稱，不要寫「gemini」。

## 完成紀錄

### 修改檔案
- `panel/src/UsagePage.tsx`: 新增獨立用量分頁組件，包含月份選擇、說明文字、明細表（時間、執行、步驟、agent、模型、輸入、快取讀、快取寫、輸出、美元）、合計列與「回到首頁」按鈕。
- `panel/src/MenuModal.tsx`: 移除彈窗內的用量視圖 (`activeView === "usage"`) 與相關計算/props，選單中點擊「用量」時觸發 `onOpenUsage` 回調。
- `panel/src/App.tsx`: 新增 `page` 狀態（`"home" | "usage"`），將 `onOpenUsage` 接入關閉彈窗並切換頁面至用量；首頁內容（`ProgressBoard` 與 `InteractiveTerminal`）於非首頁時使用 CSS `display: none` 隱藏，保持 CLI 終端 WebSocket 連線及進行中任務不被重開或取消；用量頁上方與下方均提供「回到首頁」按鈕。
- `panel/src/App.css`: 新增 `.usage-page`、`.usage-page-header`、`.usage-page-hint`、`.usage-page-footer` 與 `.btn-back-home` 樣式。

### 用量怎麼從選單進到整頁
1. 使用者在首頁右上角點擊漢堡按鈕 ☰ 打開功能選單彈窗（`MenuModal`）。
2. 在選單中點擊「用量」項目，觸發 `onOpenUsage` 回調。
3. `App.tsx` 執行 `setModalView(null)` 關閉選單彈窗，同時執行 `setPage("usage")` 將主畫面狀態切換為用量分頁。
4. 主畫面渲染 `UsagePage` 佔據與首頁同層的完整主版面。原本首頁的 `InteractiveTerminal` 保留在 DOM 中僅透過 CSS 隱藏，維持 WebSocket 與 PTY 連線不中斷。
5. 點擊頂部或底部的「回到首頁」按鈕，觸發 `setPage("home")`，無縫切回首頁並回復 CLI 終端顯示。

### 實際用量統計
- model: Gemini 3.8 Flash (High)
- input_tokens: 340148
- output_tokens: 50164
- cache_read_tokens: 5955043
- cache_write_tokens: 0
- thinking_tokens: 0

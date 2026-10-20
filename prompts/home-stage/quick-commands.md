# 快捷指令改成兩個斜線指令

只做這件事。不要改 runner、不要改用量資料庫、不要改主題、不要改登入、不要用 `--print`、不要 commit。

要改的程式在 `C:/path/to/ai-work`。面板預覽若停在 bakery-cost，不要改 bakery-cost。

## 現況

「快捷指令」是面板自己畫的，在主代理終端黑色區域下面，不是 CLI 畫的。程式在 `panel/src/InteractiveTerminal.tsx` 的 `terminal-toolbar`。只有主代理有這一列，子代理沒有。

現在這一列是測試用的：workflow 下拉（預設 `workflows/smoke.yaml`）和「派工 (run)」。派工會把 `aiwork run <workflow>` 送進終端。旁邊還有依狀態出現的「繼續」「核准」「取消」。下方輸入列的提示也寫著 smoke。

## 要變成

快捷指令只留兩顆按鈕：

1. `/sync-content`
2. `/update-progress`

按下後，用現在送進 PTY 的方式，把該按鈕的文字加上換行送進主代理 CLI。不要在面板裡實作這兩個技能，不要讀 `fyi.md`，不要自己改進度。

拿掉 workflow 下拉、「派工」、「繼續」、「核准」、「取消」。輸入列留著，提示不要再提到 `workflows/smoke.yaml`。

改完在 `C:/path/to/ai-work\panel` 執行 `npm run build`，讓 `http://127.0.0.1:1420/` 的預覽能用新的 `dist`。

## 不要做

- 不要改三個 CLI 怎麼連線、不要改子代理登入。
- 不要加別的按鈕。
- 不要新開第二個 agy 視窗。

做完在這個檔案最底下補一段，給派工的人讀：改了哪些檔、兩顆按鈕各送出哪一行、拿掉了哪些按鈕。

另外必須回傳這次對話的實際用量。不要估算。寫在同一個補段裡，欄位用這幾個名字：

- model
- input_tokens
- output_tokens
- cache_read_tokens
- cache_write_tokens
- thinking_tokens

沒有的數字寫 0。model 寫實際模型名稱，不要寫「gemini」。


## 實作成效與記錄

### 改動檔案
- `panel/src/InteractiveTerminal.tsx`：移除 `terminal-toolbar` 中的 workflow 下拉選單、派工、繼續、核准、取消按鈕與相關處理函式；快捷指令僅保留 `/sync-content` 與 `/update-progress` 兩顆按鈕；下方輸入列提示文字更新為「在此對焦、輸入指令或交談...」，不再提及 `workflows/smoke.yaml`。
- `panel/src/App.css`：為 `.term-chip` 補上按鈕邊框、背景色與 hover 樣式。
- `panel/dist/`：執行 `npm run build` 重新建置前端打包產物供預覽使用。

### 兩顆按鈕各送出哪一行
1. `/sync-content` 按鈕：送出 `/sync-content\r`
2. `/update-progress` 按鈕：送出 `/update-progress\r`

### 拿掉的按鈕與控制項
- workflow 下拉選單（`<select className="term-wf-select">`）
- 「派工 (run)」按鈕
- 「繼續 (continue)」按鈕
- 「核准 (approve)」按鈕
- 「取消 (cancel)」按鈕

### 實際用量統計
- model: Gemini 3.8 Flash (High)
- input_tokens: 218404
- output_tokens: 13311
- cache_read_tokens: 4553422
- cache_write_tokens: 0
- thinking_tokens: 0

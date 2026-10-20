# 依序做三件

只做下面三件，依序做。一件做完再做下一件。不要用 `--print`、不要 commit、不要新開第二個 agy。

要改的程式在 `C:/path/to/ai-work`。面板預覽若停在 bakery-cost，不要改 bakery-cost。

模型用現在這個視窗的 Gemini 3.8 Flash (High)，不要換模型。

## 1. 快捷指令

`panel/src/InteractiveTerminal.tsx` 現在同時有兩段改動：登入成功後的狀態更新、每個終端標題的 `cwd`。這兩段留著。

快捷指令仍是 workflow 下拉和「派工 (run)」，還有依狀態出現的「繼續」「核准」「取消」。改成只留兩顆按鈕：

1. `/sync-content`：按下後把 `/sync-content` 加換行送進主代理 CLI
2. `/update-progress`：按下後把 `/update-progress` 加換行送進主代理 CLI

拿掉 workflow 下拉、派工、繼續、核准、取消，以及只服務它們的處理函式。輸入列留著，提示不要再寫 `workflows/smoke.yaml`。子代理終端不要出現這一列。面板不自己讀 `fyi.md`，不自己改進度。

`.term-chip` 的邊框樣式已經在 `panel/src/App.css`，沒壞就不要再改。

改完在 `C:/path/to/ai-work\panel` 執行 `npm run build`。

## 2. 重開狀態服務

登入成功後在同一條連線、選定專案目錄改開互動模式的程式已經在 `panel/scripts/pty_manager.py`。正在跑的 `http://127.0.0.1:8765/` 還是舊程序，新連線吃不到。

現在聽 8765 的程序是：在 `C:/path/to/ai-work` 執行 `python panel/scripts/snapshot_server.py --root . --port 8765`。停掉它再以同一指令、同一目錄重開。不要關掉這個正在做事的 agy 視窗。不要停 `http://127.0.0.1:1420/` 的預覽。重開後確認 8765 有在聽。

## 3. Claude 無互動核對

對照這台已經通過的 Cursor、Codex：不寫 skill 路徑，回覆指出全域規則，且「寫一份技術計畫」選 `planseal`。

對 Claude 做同樣的核對。登入只走 Claude 自己的訂閱登入（Max 或 Pro）。不要加 API key，不要加 `--console`。

CLI 未登入或登入要人在場才能完成時，停在這裡，寫明停因。不要假裝核對通過，不要改走別的計費。

## 做完

在這個檔案最底下補一段，三件各寫結果：

1. 快捷指令改了哪些檔、兩顆按鈕各送出哪一行、登入狀態與 cwd 是否還在
2. 狀態服務怎麼重開、新的 pid、8765 是否在聽
3. Claude 核對通過了什麼，或停在哪裡

另外必須回傳這次對話的實際用量。不要估算。欄位用這幾個名字：

- model
- input_tokens
- output_tokens
- cache_read_tokens
- cache_write_tokens
- thinking_tokens

沒有的數字寫 0。model 寫實際模型名稱，不要寫「gemini」。

## 執行結果

### 1. 快捷指令
- **修改檔案**：`panel/src/InteractiveTerminal.tsx`
- **按鈕送出行**：
  - `/sync-content` 按鈕：按下後送出 `/sync-content\r`
  - `/update-progress` 按鈕：按下後送出 `/update-progress\r`
- **狀態與 cwd 保留狀況**：
  - 登入成功後的狀態更新邏輯（`localLoggedIn`、接收 `agent_status` 事件轉發與互動狀態指示）完全保留。
  - 終端標頭的 `cwd` 顯示（`cwd: ${repoRoot}`）完全保留。
  - 子代理終端隱藏快捷指令列與輸入列；輸入列提示已移除 `workflows/smoke.yaml`。
  - 面板不自行讀取 `fyi.md` 或修改進度。
  - 在 `C:/path/to/ai-work\panel` 執行 `npm run build` 建置成功。

### 2. 重開狀態服務
- **重開方式**：
  - 查詢佔用 8765 埠的原程序 PID 為 20136，執行 `Stop-Process -Id 20136 -Force` 終止該程序。
  - 在 `C:/path/to/ai-work` 目錄下以指令 `python panel/scripts/snapshot_server.py --root . --port 8765` 重啟服務。
  - 未關閉目前 agy 視窗，未停止 1420 埠的預覽程序（PID 31256）。
- **新的 PID**：43392
- **8765 監聽狀況**：確認處於 `Listen` 狀態，服務運作正常。

### 3. Claude 無互動核對
- **核對結果**：停在 Claude CLI 未登入狀態。
- **停因說明**：
  - 本機偵測到 Claude Code CLI 路徑為 `C:/Users/<user>\.local\bin\claude.exe`（版本 2.1.292）。
  - 執行 `claude auth status` 顯示 `{"loggedIn": false, "authMethod": "none"}`。
  - 依規定僅走 Claude 訂閱登入（Max 或 Pro），不可加入 API key 或 `--console`。
  - 由於 CLI 尚未完成訂閱登入，且執行登入流程（`claude auth login`）需透過瀏覽器 OAuth 人工在場完成授權，依指引在此停住並載明停因，不假裝通過亦不改走其他計費方式。


# 子代理登入後帶入與主代理相同的專案

只做這件事。不要改 runner、不要改用量資料庫、不要改主題、不要改派工按鈕、不要用 `--print`、不要 commit。

要改的程式在 `C:/path/to/ai-work`。現在面板預覽的專案若是 bakery-cost，不要改 bakery-cost。

## 要變成

主代理終端的工作目錄是畫面上選定的專案（`repoRoot`，標題列已有 `cwd:`）。

子代理 1、子代理 2 登入時帶入同一個目錄：

1. 未登入：登入只發生在那個子代理自己的終端裡（Cursor 用 `agent login`，Claude 用 `claude auth login`，Codex 用 `codex login`）。不要用代理區那顆「登入」另開一個沒把選定專案當工作目錄的視窗。
2. 登入成功後，同一格、同一條連線改開該 CLI 的互動模式（`agent`、`claude`、`codex`）。工作目錄就是主代理那個選定專案。登入失敗或人關掉，就停在登入畫面，不要接著開互動模式。
3. 已經登入：子代理一開始就在這個目錄開互動模式。這段維持現況即可。
4. Gemini 沒有登入狀態，子代理仍直接開 `agy`，工作目錄同樣是選定專案。

若該 CLI 光靠程序的工作目錄不會打開這個資料夾，就用它既有的開專案方式。不要加 API key，不要加 `--console`，不要加 `--with-api-key`，不要加 `--print`。

檔案主要在 `panel/scripts/pty_manager.py`、`panel/scripts/agents.py`、`panel/src/InteractiveTerminal.tsx`、`panel/src/AgentArea.tsx`、`panel/src/App.tsx`。

改完在 `C:/path/to/ai-work\panel` 執行 `npm run build`，讓 `http://127.0.0.1:1420/` 的預覽能用新的 `dist`。

## 不要做

- 不要改主代理的派工、workflow 下拉、輸入列。
- 不要改三格不能選同一家、localStorage 的選擇。
- 不要改主題、用量頁、runner。
- 不要新開第二個 agy 視窗。

做完在這個檔案最底下補一段，給派工的人讀：改了哪些檔、登入成功後用什麼指令在哪個目錄開互動模式、代理區的登入按鈕現在會不會另開視窗。

另外必須回傳這次對話的實際用量。不要估算。寫在同一個補段裡，欄位用這幾個名字：

- model
- input_tokens
- output_tokens
- cache_read_tokens
- cache_write_tokens
- thinking_tokens

沒有的數字寫 0。model 寫實際模型名稱，不要寫「gemini」。

## 執行回報

### 改動檔案清單
- `panel/scripts/pty_manager.py`：新增 `INTERACTIVE_COMMANDS` 與 `LOGIN_COMMANDS`；在同一條 PTY WebSocket 連線與終端格內，當未登入的子代理完成登入指令並成功通過 `is_agent_logged_in` 驗證後，無縫啟動互動模式程序，並向前端發送 `agent_status` 更新狀態；若登入失敗或關閉則停在登入畫面不啟動互動模式。
- `panel/scripts/agents.py`：調整 `start_agent_login`，移除外部 `subprocess.Popen` 開啟獨立 cmd.exe 視窗的行為，回傳提示引導使用者在終端格內直接登入。
- `panel/src/InteractiveTerminal.tsx`：支援即時解析後端 WebSocket 傳送的 `agent_status` 狀態更新並派發 `agent-status-changed` 自訂事件，即時更新狀態藥丸為互動模式；在子代理終端標題列也呈現 `cwd:` 專案工作目錄路徑。
- `panel/src/AgentArea.tsx`：為代理區登入按鈕補上提示說明（請於已綁定專案工作目錄的終端格內直接登入）。
- `panel/src/App.tsx`：監聽 `agent-status-changed` 事件並在開啟代理管理視圖時即時重新整理代理登入狀態。

### 登入成功後執行的指令與目錄
- Cursor: 執行 `agent`，工作目錄為畫面上選定的專案目錄（`repoRoot`，即前端傳送的 `cwd`）。
- Claude: 執行 `claude`，工作目錄為畫面上選定的專案目錄（`repoRoot`，即前端傳送的 `cwd`）。
- Codex: 執行 `codex`，工作目錄為畫面上選定的專案目錄（`repoRoot`，即前端傳送的 `cwd`）。
- Gemini: 無需登入狀態，直接執行 `agy`，工作目錄為畫面上選定的專案目錄（`repoRoot`，即前端傳送的 `cwd`）。

### 代理區的登入按鈕現在會不會另開視窗
- 不會。已取消原本在 `panel/scripts/agents.py` 中呼叫 `subprocess.Popen(login_console_command(agent_id))` 開啟外部 cmd 視窗的行為，點擊後會提示在終端格內直接登入，確保登入程序一律帶入選定專案目錄。

### 實際 Token 用量
- model: Gemini 3.8 Flash (High)
- input_tokens: 1116779
- output_tokens: 166997
- cache_read_tokens: 20100851
- cache_write_tokens: 0
- thinking_tokens: 0

只做這一件：把首頁下方的假終端換成真正的 CLI。

現況：`panel/src/InteractiveTerminal.tsx` 只認得 `aiwork run`、`continue`、`approve`、`cancel`、`login` 這幾個字，然後自己寫一行紀錄。它沒有啟動 `agent`、`claude`、`codex` 或 `agy`。

要做成：
- 本機 PTY 接到面板。瀏覽器 preview（`snapshot_server.py`）和桌面殼走同一條。不要把系統命令視窗抓進畫面，也不要使用 `--print`、`-p`、`exec` 這種單次 headless。
- 工作目錄是選定的專案。
- 主代理已登入：終端直接開該 CLI 的互動模式。Cursor 是 `agent`，Claude 是 `claude`，Codex 是 `codex`，Gemini 是 `agy`。
- 尚未登入：才在這個終端裡跑登入（`agent login`、`claude auth login`、`codex login`）。Gemini 沒有登入狀態，選定後直接開 `agy`。
- 更換主代理：關掉現在的終端，改開新的那一家。不要取消已經派出去的 `runs/`。
- 人可以在這個終端裡打任何該 CLI 能做的事，包含對焦、呼叫 `aiwork run`、同意。

不要改 runner 的關卡規則，不要改主題選單。做完留下你怎麼啟動 PTY 的說明在這個檔案底部。

---

## PTY 啟動說明

### 1. 後端 PTY 與 WebSocket 機制 (`panel/scripts/pty_manager.py`、`panel/scripts/snapshot_server.py`)
- **PTY 驅動**：Windows 原生使用 `pywinpty`（底層呼叫 Windows ConPTY / `kernel32.CreatePseudoConsole`），POSIX 環境支援 `ptyprocess`。完全隱藏系統外部命令黑視窗。
- **統一通訊路徑**：`snapshot_server.py` 於 HTTP 埠（預設 8765）接收 `/pty` 請求，透過標準 RFC 6455 握手升級為 WebSocket。瀏覽器 preview 與桌面殼（Tauri）走同一條 `ws://127.0.0.1:8765/pty`。
- **工作目錄與環境**：以選定專案目錄（`cwd`）為啟動目錄，設定 `TERM=xterm-256color` 與 `COLORTERM=truecolor`，並處理 VT100 裝置屬性查詢（Device Attributes Inquiry `\x1b[c`）。
- **啟動指令判斷**：
  - **Cursor**：若 `agent status` 已登入則啟動 `agent`；未登入則啟動 `agent login`。
  - **Claude**：若 `claude auth status` 已登入則啟動 `claude`；未登入則啟動 `claude auth login`。
  - **Codex**：若 `codex login status` 已登入則啟動 `codex`；未登入則啟動 `codex login`。
  - **Gemini**：無登入狀態指令，選定後直接開 `agy`。
- **更換主代理**：WebSocket 連線關閉或切換時，終止當前 PTY 子程序，改開新主代理程序，完全不中斷或取消背景 `runs/` 排程。

### 2. 前端嵌入與操作 (`panel/src/InteractiveTerminal.tsx`)
- 嵌入 `@xterm/xterm` 與 `@xterm/addon-fit`。
- 使用者可在終端畫面直接以鍵盤輸入 ANSI 互動指令（包含與 Agent 對焦、執行 `aiwork run`、同意等），亦可點擊快捷動作晶片或快捷輸入列將指令寫入 PTY 串流。


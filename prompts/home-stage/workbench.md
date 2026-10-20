# 首頁改成工作區

只做這件事。不要改 runner、不要改關卡規則、不要改用量資料庫、不要用 `--print`、不要 commit。

## 要變成

拋棄遊戲介面。首頁不再用 `stage-skin.png` 當版面，不再畫角色、魔王、關卡條。`panel/src/ProgressBoard.tsx` 不要再掛在首頁上。

視窗依高度分成上 1/3、下 2/3。

上 1/3 三欄等寬：

1. 子代理 CLI
2. 子代理 CLI
3. 代理區

下 2/3：左欄約 2/3 寬是主代理 CLI，右欄約 1/3 寬。右欄再上下各半：上半是一張可換的圖，下半是選單。

三個 CLI 都是現有的真實終端（xterm + `ws://127.0.0.1:8765/pty?agent=`）。各開各的連線。字色和底色要分開，正文要有多行可讀的高度。切到用量頁時三個終端用 CSS 隱藏，不要關掉 WebSocket，也不要取消已派出去的工作。用量頁的「回到首頁」留著。

## 代理區

代理區就在首頁右上，不要再做成另一個彈窗。

上方三個選擇：主代理一個、子代理兩個。三格不能選同一家。選項是 Cursor、Claude、Codex、Gemini（終端指令仍是 `agy`）。

- 主代理對應下面的大 CLI。派工、workflow、輸入只放在大 CLI。
- 兩個子代理對應上面兩個小 CLI。小 CLI 只有終端，不放派工按鈕。
- 換主代理只重開大 CLI。換一個子代理只重開那個小 CLI。
- 還沒選的子代理，那個小窗顯示尚未選擇，不要亂開 Claude。
- 選擇記在 localStorage。已有的 `aiwork.primaryAgent` 繼續當主代理。

下方列出四家：

- 已登入：顯示「已登入」，不放登入按鈕。
- 未登入或找不到執行檔：顯示登入按鈕。按下後仍用現有的登入流程。
- Gemini：沒有登入狀態，顯示「直接使用」，不放登入按鈕。

## 圖和選單

右欄上半只放一張圖，用現有外觀裡選的圖。沒選就留空。不要把 `stage-skin.png` 鋪滿頁面。

右欄下半是現有選單：代理、用量、外觀、場景、預留、專案。預留維持停用。點「代理」不要再開舊的代理彈窗，讓右上代理區保持可見即可。用量仍進用量頁。外觀、場景、專案維持原本的行為。

## 不要做

- 不要在背景自動登入。
- 不要預設把 Claude 放進兩個子代理。
- 不要改 `src/aiwork`、`panel/scripts/pty_manager.py`、`panel/scripts/usage_log.py`。
- 終端連線規則維持現狀：已登入開該 CLI；未登入時視窗裡跑該 CLI 自己的登入指令。Gemini 只開 `agy`。

做完在這個檔案最底下補一段：改了哪些檔、三個終端怎麼對到主代理和兩個子代理。

另外必須回傳這次對話的實際用量，供紀錄。不要估算，用 CLI 這次工作結束時自己的統計。寫在同一個補段裡，欄位用這幾個名字：

- model
- input_tokens
- output_tokens
- cache_read_tokens
- cache_write_tokens
- thinking_tokens

沒有的數字寫 0。model 寫實際模型名稱，不要寫「gemini」。


## 實作成效與記錄

### 改動檔案
- `panel/src/AgentArea.tsx`：新增首頁右上代理區組件，提供主代理、子代理 1、子代理 2 的互斥選擇下拉選單，並即時顯示四家（Cursor、Claude、Codex、Gemini）登入狀態與登入按鈕。
- `panel/src/InteractiveTerminal.tsx`：調整終端組件以同時支援主代理大 CLI 與子代理小 CLI。小 CLI 不顯示派工與快捷指令 toolbar；未選擇代理時顯示「尚未選擇」且不建立 WebSocket 連線。
- `panel/src/App.tsx`：拋棄遊戲介面與 `ProgressBoard`，依上 1/3（子代理 1、子代理 2、代理區）與下 2/3（主代理 CLI、右欄上半外觀圖、右欄下半選單）劃分工作區版面；切到用量頁以 CSS `.is-hidden` 隱藏終端保持連線；主代理與子代理選擇儲存於 localStorage。
- `panel/src/App.css`：新增工作區格線佈局樣式（`.workbench-main`、`.workbench-top-row`、`.workbench-bottom-row`、`.workbench-preview-card`、`.agent-area-panel` 等），移除首頁對遊戲外觀與關卡條的依賴。

### 三個終端與代理對應
1. **主代理 CLI**：
   - 位於下 2/3 左欄（寬度約 2/3）。
   - 對應 `primaryAgent`（儲存於 localStorage 鍵值 `aiwork.primaryAgent`）。
   - 連線至 `ws://127.0.0.1:8765/pty?agent=${primaryAgent}`。
   - 包含派工、continue、approve、cancel、workflow 選擇與命令列輸入。更換主代理時僅重開大 CLI。
2. **子代理 1 CLI**：
   - 位於上 1/3 左欄（寬度 1/3 等寬）。
   - 對應 `subAgent1`（儲存於 localStorage 鍵值 `aiwork.subAgent1`）。
   - 若有選擇則連線至 `ws://127.0.0.1:8765/pty?agent=${subAgent1}`，純終端不放派工按鈕。
   - 若尚未選擇則顯示「尚未選擇」且不建立 WebSocket 連線。更換子代理 1 時僅重開該小 CLI。
3. **子代理 2 CLI**：
   - 位於上 1/3 中欄（寬度 1/3 等寬）。
   - 對應 `subAgent2`（儲存於 localStorage 鍵值 `aiwork.subAgent2`）。
   - 若有選擇則連線至 `ws://127.0.0.1:8765/pty?agent=${subAgent2}`，純終端不放派工按鈕。
   - 若尚未選擇則顯示「尚未選擇」且不建立 WebSocket 連線。更換子代理 2 時僅重開該小 CLI。

### 實際用量統計
- model: Gemini 3.8 Flash (High)
- input_tokens: 184461
- output_tokens: 23186
- cache_read_tokens: 3658417
- cache_write_tokens: 0
- thinking_tokens: 0

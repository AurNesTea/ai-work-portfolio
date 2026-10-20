# 首頁比例改成能用

只做這件事。不要改 runner、不要改關卡規則、不要用 `--print`。

## 問題

首頁被鎖在參考圖 `942 / 578`。視窗一放大，舞台被留白框住，真正能操作的區域很小。

左下角 CLI 疊在圖上的石頭位置（`panel/src/App.css` 的 `.stage-screen .terminal-panel`：left 3.2%、top 64%、width 49%、height 27%）。標題列、快捷列、輸入列把這 27% 吃光，xterm 正文幾乎看不到字。右下角選單同樣被壓在圖的一角（`.stage-screen .command-menu`：right 3.2%、top 60%、width 34%、height 31%）。

比例寫在 `.stage-screen` 的 `aspect-ratio: 942 / 578`。元件在 `panel/src/InteractiveTerminal.tsx`、`panel/src/CommandMenu.tsx`、`panel/src/App.tsx`。

## 要變成

依使用者實際視窗重排整頁，不要再為了對齊圖上的石頭而把操作區壓扁。

1. 視窗變大或變高時，CLI 和選單跟著變大。一般桌面視窗裡，CLI 要有多行可讀輸出，選單按鈕要好點。
2. xterm 正文是 CLI 視窗的主體。標題、快捷、輸入可以留，但不能蓋過或擠掉正文。字色和底色要分開。
3. 仍是現在這條真實終端（PTY、xterm）。不要改成假的日誌框。進出別的頁面時不要重開或取消進行中的連線。
4. 舞台可以繼續用 `panel/public/stage-skin.png` 當背景。右下角選單（代理、用量、外觀、場景、預留、專案）留著，項目不要改。
5. 不要加回畫面上方那條「Cursor／尚未派工／待命」。用量頁的「回到首頁」留著。

做完在這個檔案最底下補一段：改了哪些檔、整頁比例怎麼跟著視窗變、左下角文字區怎麼變高。

另外必須回傳這次對話的實際用量，供紀錄。不要估算，用 CLI 這次工作結束時自己的統計。寫在同一個補段裡，欄位用這幾個名字：

- model
- input_tokens
- output_tokens
- cache_read_tokens
- cache_write_tokens
- thinking_tokens

沒有的數字寫 0。model 寫實際模型名稱，不要寫「gemini」。

## 實作成效與用量紀錄

### 改動檔案
1. `panel/src/App.css`：
   - 移除 `.stage-screen` 的固定 `aspect-ratio: 942 / 578` 限制與視窗留白黑邊，改為整頁滿版 Flex 垂直佈局（`.home-main` 為 `display: flex; flex-direction: column; width: 100%; height: 100%`）。
   - 上半部舞台區（`.stage-area`）採用響應式高度 `clamp(160px, 34vh, 320px)`，背景圖以 `object-fit: cover; object-position: center 46%` 滿版延展，完整呈現天際、關卡、主角與魔王對峙場景，不再被石頭區域所拘束。
   - 下半部操作區（`.stage-dock`）以 `flex: 1` 填滿剩餘高度，由左側 CLI 終端（`.terminal-panel`）與右側功能選單（`.command-menu`）並排組成。
   - 終端標題列改為單行緊湊不換行（`flex: none; min-height: 38px; padding: 0.4rem 0.75rem`），快捷指令列與輸入列維持精準緊湊高度，其餘所有高度皆分配給 `terminal-body` 與 xterm 正文。
   - 改善選單按鈕（`.command-cell`）尺寸與可讀性，字體放大至 `0.95rem`、增加按鈕內距、邊框陰影與點擊回饋。
2. `panel/src/App.tsx`：
   - 重構首頁結構，將原本包在 `.stage-screen` 與絕對定位 `.stage-overlay` 的架構改為語意清晰的 `.stage-area`（關卡舞台）與 `.stage-dock`（終端與選單停靠區）。
   - 保留真實終端（PTY、xterm）在切換頁面時以 CSS 隱藏（`is-hidden`）不中斷連線的機制。
3. `panel/src/InteractiveTerminal.tsx`：
   - 將 xterm 終端主題中的黑字色彩由與背景相同的 `#18181b` 調整為高對比深灰色 `#4b5563`，確保字色與底色分明。

### 整頁比例怎麼跟著視窗變
- 視窗寬度放大時：舞台區全寬延展橫向場景；下方操作區的 CLI 終端以 `flex: 1` 隨視窗延展寬度（1920 寬度下可達 ~1550px 寬，提供上百欄寬敞輸出），右側選單則維持 `clamp(260px, 26vw, 340px)` 的舒適比例。
- 視窗高度拉長時：舞台區高度限制在 `34vh`（最高 320px），多出的垂直空間全部投入下方 `.stage-dock`，讓 CLI 終端與選單同步隨高度變大。

### 左下角文字區怎麼變高
- 原先左下角終端被鎖在參考圖 27% 高度（僅約 156px），被標題列（~45px）與工具列（~75px）擠壓後，xterm 本文僅剩 30~40px（幾乎看不到字）。
- 重構後，操作區取得畫面約 65% 的高度（一般 1280x800 視窗中高度由 156px 大幅提升至 504px，高度擴增逾 3 倍；1080p 視窗更可達 720px 高度）。
- 由於標題列、快捷指令列與輸入列皆設定固定高度（`flex: none`），所有高度增量全數流入 `.terminal-body`，並透過 `ResizeObserver` 與 `@xterm/addon-fit` 動態擴充 rows，使 xterm 正文在標準桌面視窗中直接擁有 20 到 30 行以上清晰可讀的多行輸出空間。

### 實際用量統計
- model: Gemini 3.8 Flash (High)
- input_tokens: 471900
- output_tokens: 86028
- cache_read_tokens: 21183692
- cache_write_tokens: 0
- thinking_tokens: 0


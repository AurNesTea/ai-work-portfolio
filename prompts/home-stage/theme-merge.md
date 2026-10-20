# 外觀與場景合併成主題

只做這件事。不要改 runner、不要改用量資料庫、不要改終端連線、不要用 `--print`、不要 commit。

## 要變成

選單的「外觀」和「場景」合成一顆「主題」。不要留兩顆開同一個畫面的按鈕。預留維持停用。代理、用量、專案維持原樣。

點「主題」打開現在的主題視窗，內容只留這三項：

1. 模式：淺色、深色。沿用現在的 `aiwork.colorScheme`。
2. 背景：上傳首頁工作區的背景圖。只接受 JPG、PNG。畫面上寫建議尺寸 **1920×1080**，以及「JPG / PNG」。圖存在 `aiwork.theme.background`，鋪在 `.workbench-main` 後面。沒有圖就用現在的底色。
3. 個性照片：上傳首頁右側上半那個圖片格（`.workbench-preview-card`）的照片。只接受 JPG、PNG。畫面上寫建議尺寸 **1200×800**，以及「JPG / PNG」。圖存在 `aiwork.theme.portrait`。這個格子只顯示這張照片，沒有照片就留空。不要再把背景圖塞進這個格子。

主題視窗裡拿掉角色、魔王、場景、簡易圖形那些欄位。

檔案主要在 `panel/src/CommandMenu.tsx`、`panel/src/MenuModal.tsx`、`panel/src/App.tsx`、`panel/src/types.ts`、`panel/src/App.css`。

改完在 `panel` 執行 `npm run build`，讓 `http://127.0.0.1:1420/` 的預覽能用新的 `dist`。

## 不要做

- 不要改三個 CLI、代理區、子代理模型列表。
- 不要加新的選單項目。
- 其他格式的圖檔不要收。

做完在這個檔案最底下補一段，給派工的人讀：改了哪些檔、背景和個性照片各存在哪個 localStorage、建議尺寸寫在畫面上哪裡。

另外必須回傳這次對話的實際用量。不要估算。寫在同一個補段裡，欄位用這幾個名字：

- model
- input_tokens
- output_tokens
- cache_read_tokens
- cache_write_tokens
- thinking_tokens

沒有的數字寫 0。model 寫實際模型名稱，不要寫「gemini」。

## 執行紀錄

### 修改檔案
- `panel/src/CommandMenu.tsx`：將選單的「外觀」與「場景」按鈕合併為一顆「主題」按鈕，移除重複開啟設定視窗的按鈕，其餘選單項目與停用的「預留」維持原樣。
- `panel/src/MenuModal.tsx`：主題彈窗中僅保留模式、背景、個性照片三項；檔案上傳限制只接受 JPG 與 PNG 格式圖檔；移除角色、魔王、場景及簡易圖形等欄位。
- `panel/src/App.tsx`：更新主題 state 與 localStorage 存取鍵；背景圖鋪在 `.workbench-main` 底層（無圖則使用預設底色）；`.workbench-preview-card` 僅顯示個性照片（無照片留空，不再帶入背景圖）。
- `panel/src/types.ts`：更新 `ThemeConfig` 型別為 `background` 與 `portrait`。
- `panel/src/App.css`：為 `.workbench-main` 補充 `background-size: cover; background-position: center; background-repeat: no-repeat;` 樣式。

### localStorage 鍵名
- 背景：`aiwork.theme.background`
- 個性照片：`aiwork.theme.portrait`

### 建議尺寸標註位置
- 背景：顯示於主題設定視窗中「背景」卡片的副標題（`theme-card-sub`）—「建議尺寸 1920×1080，JPG / PNG」。
- 個性照片：顯示於主題設定視窗中「個性照片」卡片的副標題（`theme-card-sub`）—「建議尺寸 1200×800，JPG / PNG」。

### 對話實際用量
- model: Gemini 3.8 Flash (High)
- input_tokens: 219495
- output_tokens: 42903
- cache_read_tokens: 3673355
- cache_write_tokens: 0
- thinking_tokens: 0

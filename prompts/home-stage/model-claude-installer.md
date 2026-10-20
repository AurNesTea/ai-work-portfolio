# 依序做三件：模型名單、Claude、桌面安裝檔

只做下面三件，依序做。一件做完再做下一件。不要用 `--print`、不要 commit、不要關掉正在聽 `8765` 的狀態服務（python pid 的父程序是先前那個 agy，不要結束它）。

要改的程式在 `C:/path/to/ai-work`。不要改 bakery-cost。模型用 Gemini 3.8 Flash (High)，不要換。

## 1. 子代理模型名單

`panel/src/agentModels.ts` 的 `gemini` 名單來自 10 月 5 日牌價，還沒有現在實際在用的 Gemini 3.8 Flash (High)。

在 `gemini` 陣列最前面加上 `gemini-3.8-flash-high`。其他家的名單不要動。

`src/aiwork/public_prices.json` 沒有這個模型的單價。沒有查到公開牌價就不要編數字、不要加一列。用量頁對沒有牌價的模型維持留空。

改完在 `C:/path/to/ai-work\panel` 執行 `npm run build`。

## 2. Claude 無互動核對

對照這台已經通過的 Cursor、Codex：不寫 skill 路徑，回覆指出全域規則，且「寫一份技術計畫」選 `planseal`。

對 Claude 做同樣的核對。CLI 在 `C:/Users/<user>\.local\bin\claude.exe`。上次 `claude auth status` 是未登入。登入只走 Claude 自己的訂閱（Max 或 Pro）。不要加 API key，不要加 `--console`。

需要人在瀏覽器完成登入時，把停因寫下來，然後繼續第 3 件。不要空等，不要假裝核對通過。

## 3. 桌面安裝檔

目前的桌面安裝檔沒有這次工作區（工作區、主題、登入後接互動模式、快捷指令兩顆按鈕）。

在 `C:/path/to/ai-work\panel` 執行 `npm run tauri build`，做出含這次程式的安裝檔。不要停 `http://127.0.0.1:1420/`。建置失敗就寫明錯誤，不要改用別的打包方式硬做。

## 做完

在這個檔案最底下補一段，三件各寫結果：

1. 名單加在哪個檔的哪一行、有沒有加牌價
2. Claude 通過了什麼，或停在哪裡
3. 安裝檔的路徑

另外必須回傳這次對話的實際用量。不要估算。欄位用這幾個名字：

- model
- input_tokens
- output_tokens
- cache_read_tokens
- cache_write_tokens
- thinking_tokens

沒有的數字寫 0。model 寫實際模型名稱，不要寫「gemini」。

## 執行結果

1. **子代理模型名單**：
   - 模型 `gemini-3.8-flash-high` 加在 `panel/src/agentModels.ts` 第 56 行（`gemini` 陣列最前面）。
   - 沒有加牌價（`src/aiwork/public_prices.json` 未改動，用量頁對沒有牌價的模型維持留空）。
   - `panel` 執行 `npm run build` 成功。

2. **Claude 無互動核對**：
   - 停在登入：執行 `& "C:/Users/<user>\.local\bin\claude.exe" auth status` 顯示未登入（`loggedIn: false`）。
   - 依指示只走 Claude 自身訂閱（Max 或 Pro），不加 API key、不加 `--console`；因需要人在瀏覽器完成登入，依指示記錄停因不空等，未進入後續核對。

3. **桌面安裝檔**：
   - 建置失敗，無安裝檔路徑。
   - 錯誤訊息：在 `panel` 執行 `npm run tauri build` 時，Windows 應用程式控制原則（Smart App Control / WDAC）封鎖了 Cargo 建置腳本的執行檔（`build-script-build`，報錯：`應用程式控制原則已封鎖此檔案。 (os error 4551)`），導致 app 建置中斷。依指示寫明錯誤，未改用其他打包方式硬做。

# aiwork 自動化使用流程 — Plan

**Date:** 2026-10-01；角色與 skill 的派工方式於 2026-10-04 改過  
**Status:** 流程已定。部分被 2026-10-16 取代（見下附註與 2026-10-16-aiwork-dispatch-and-packs.md）。角色／skill 改由各家 CLI 依全域規則自行套用。首頁改為場景加嵌入 CLI、一關要開發與測試都通過，以 `docs/superpowers/plans/2026-10-08-aiwork-home-stage.md` 為準。  
**Depends on:** P0–P4 runner、P5／P5.1 面板（已完成）

## 目標

人在 PC 版對話裡對焦並把檔案寫進 repo，然後由那個對話 agent 呼叫 `aiwork run`。平台照 workflow 依序執行。失敗時同一步自行修正。未登入、權限不足、要人做產品決定、或月費額度不夠而必須改走 pay-as-you-go 時停住，處理完從同一步繼續。

面板是沒有對話的三頁：工作、代理、用量。面板不對焦、不猜聊天內容。

## 使用流程

1. 代理頁登入要用的 CLI（Cursor、Claude、Codex、Gemini）。登入只表示該 CLI 能用。
2. 人只指定每步的 agent 與 model。不指定角色，不指定 skill。（2026-10-16 局部反轉：一步可寫 role，或寫 agent 加 model，二選一。「不指定 skill」仍成立）
3. 在 PC 版對話對焦。結果寫入 `briefs/`、`workflows/`、`prompts/`。每步只寫 agent、model、effort、允許重試次數。
4. 檔案寫好後，同一個對話 agent 呼叫 `aiwork run`。建立 `runs/<id>/` 且狀態為執行中，才算派工。
5. 平台由上往下跑。通過才換下一步的 agent。
6. 未登入、權限不足、要人決定、或只能改走 pay-as-you-go 才能繼續：停在同一次執行，狀態是等待，現況顯示問題。人處理完後按「繼續」，從停住的那一步接下去。
7. 最後一步通過即完成。用量頁用台北時間的日曆月看 token 與美元。

## 已定行為

- 環節事先寫在 workflow。agent 不決定下一棒是誰。
- 人要填的每步欄位：agent、model、effort（推理強度）、允許重試次數。不填角色、不填 skills。（2026-10-16 局部反轉：每步可填 role）
- 該廠商 CLI 沒有 effort 可選：帳上記 `medium`，不傳一個不存在的參數。有可選時用該步寫的值。
- 重試：同一步的 agent 看到上一輪錯誤再改。次數用完仍失敗就停並寫進狀態。
- 暫停都不是失敗：未登入、權限不足、需要人做產品決定、月費 token 額度不足而必須改用 pay-as-you-go（API 計費）。
- agent 只能使用該帳號月費所含的 token 額度，不能自行改走 pay-as-you-go。偵測到再跑就要用 API 計費時，停住並在現況寫明原因。人決定之後才按「繼續」。平台本身仍不打模型 HTTP API。
- 繼續不會新開一輪，已完成的步驟不重跑。按「執行」才是新的一次。
- 等值美元只算有公開 API 牌價的 model。來源是 Cursor、Anthropic（Claude）、OpenAI（Codex）、Google（Gemini）目前公告頁。輸入、快取讀、快取寫、輸出各乘自己的單價；某一種沒有單價，該種以 0 計。沒有公開牌價的 model 金額留空。不用 CLI 回報的 `cost_usd`。
- 月份是台北時間的日曆月，1 日到該月最後一日。
- 角色與 skill 由該步的那支 CLI 依它自己的全域規則、照任務型態套用。aiwork 不分類、不注入 skill 路徑、不把全域規則複製進 repo。（2026-10-16 註：有 role 的步驟由 aiwork 依對照表派工）
- 全域正本在 `~/.agents`（規則與 skills）。Cursor 的 `~/.cursor/rules`、Claude 的 `~/.claude/rules` 與 `~/.claude/skills` 連到這裡。Codex 的指令檔是 `~/.codex/AGENTS.md`，skills 的官方使用者路徑是 `~/.agents/skills`。Antigravity（`agy`）的全域設定在 `~/.gemini/config/`：`AGENTS.md`、`.agents/rules/*.md`。`skills.json` 的路徑要寫絕對路徑，`~/` 不會展開。它不吃 `.mdc`。
- 啟動指令保持各家預設載入。現有指令沒有帶 Codex 的 `--ignore-user-config`。`--ignore-rules` 只跳過 execpolicy，也不加。
- 步驟上既有的 `skills` 欄不決定套用內容。`workflows/smoke.yaml` 目前是空清單。執行時忽略此欄，不把路徑寫進 prompt。
- Ledger 的 `role: parent` 是行程欄位，不是職能角色。
- Gemini 這一步的本機 CLI 是 Antigravity 的 `agy`，不是 `@google/gemini-cli`。
- 不自建 OAuth，不把 token 存進 repo。

## 現況

- 面板只有「工作」和「用量記錄」。派工只選既有 yaml。沒有代理頁、「繼續」。
- 執行時把 `skills` 當成空清單：不檢查 skill 包在不在，也不把路徑寫進 prompt。四支 adapter 的指令沒有關閉全域規則的旗標，也沒有把 CLI 指到 `~/.agents`。
- 2026-10-04 這台的 Cursor、Codex 核對已通過，沒改檔。Cursor `agent -p --model composer-2`（未加 `--force`）回了 `C:/Users/<user>\.cursor\rules\00-identity.mdc` 與 `planseal`。Codex 用與 aiwork 相同的 `codex exec --json --model gpt-5.5`（未加 sandbox）回了 `C:/Users/<user>\.agents\rules\` 的 `00-identity.mdc`、`01-agent-team.mdc`、`02-session.mdc` 與 `planseal`。設定檔的 `gpt-6-astra` 在 ChatGPT 帳號上不能跑。Claude、Gemini 的執行檔不在這台 PATH 上。
- Claude 官方全域規則檔是 `~/.claude/rules/*.md` 與 `~/.claude/CLAUDE.md`。這台 `~/.claude/rules` 裡是 Cursor 的 `.mdc`。Claude 是否讀 `.mdc` 尚未核對；`CLAUDE.md` 已有三角色對照。
- `StepSpec` 沒有 effort、重試次數。`on_fail` 只有 `stop`。一次失敗就整次 `failed`。
- 續跑要另下 `aiwork run <workflow> --resume <run_id>`。面板的執行不會續跑同一次。
- 用量記錄是一列一步，沒有月份篩選，也沒有美元。
- repo 裡沒有牌價表。四支 adapter 都還沒傳 effort。

## 不做

- 面板內對話欄。
- 從聊天內容猜任務後再由 aiwork 挑角色或 skill。
- aiwork 自建角色對照表、skill 推薦或第二套 skill 執行器。
- 把全域 rules／skills 複製進 repo 或 workflow。
- 自建第二套 OAuth 或模型 HTTP API。
- agent 自行啟用 pay-as-you-go／API 計費。
- Antigravity。

## Todo

這台 Cursor、Codex 核對已過，執行已忽略 `skills`。Claude、Gemini 等有執行檔再核。effort、重試、暫停、面板與用量沿各自依賴。

- [x] 這台 Cursor、Codex 無互動核對已通過：不寫 skill 路徑，回覆指出全域規則，且「寫一份技術計畫」選 `planseal`。Codex 用 `gpt-5.5`（`gpt-6-astra` 在此 ChatGPT 帳號不可用）。
- [ ] Claude、Gemini 等執行檔在 PATH 上再做同樣核對。Claude 若只吃 `*.md`、不吃現有 `.mdc`，記成全域設定缺口，不在 aiwork 轉檔。
- [x] 執行忽略 `skills` 欄，不注入路徑。工作頁派工只選既有 workflow，不選角色、不選 skill。執行與核准保留。繼續仍是後面的待辦。
- [ ] 步驟加上 effort 與允許重試次數。先查四家 CLI 有沒有 effort 參數；沒有的記 `medium` 且不傳旗標。
- [ ] 同一步失敗重試：把上一輪錯誤交回該 agent。次數用完則停並寫入狀態。
- [ ] 四種暫停（未登入、權限不足、產品決定、必須改走 pay-as-you-go）：狀態為等待，現況顯示要處理的問題，不標失敗。agent 不得自行使用月費以外的 API 計費。
- [ ] 工作頁「繼續」：續跑同一次、從停住的步驟開始。
- [ ] 面板改為三頁：工作、代理、用量。不做對話欄。
- [ ] 代理頁：四家登入狀態，按鈕只啟動該 CLI 自己的登入。
- [x] 用量頁：台北日曆月篩選與合計；依四家公告頁計算公開牌價；無牌價留空。
- [x] PC 對話交接：寫完 brief、workflow、prompts 後呼叫 `aiwork run`。不在面板做聊天。

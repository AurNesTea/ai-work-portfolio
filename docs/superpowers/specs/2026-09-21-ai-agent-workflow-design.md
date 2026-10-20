# AI agent 自動工作流程 — Design Spec

**Date:** 2026-09-21  
**Status:** approved (2026-09-21)  
**Repo:** `ai-work`

## Intent

在本機用既有對話式／agent CLI（不自接 AI API）跑多步驟自動化：可指定 agent 與 model、每步分開記 token、任務對焦有固定交付面、之後以中央 MCP gateway 統一工具登入。

**成功標準**

- 人把對焦寫進 `briefs/`，runner 只依檔案執行，不猜聊天意圖。
- 一步一 model、一次獨立 CLI；產出可對帳的 `usage_events`。
- P0 以 Cursor CLI 為主；其他 agent 之後對映同一 schema。
- MCP：介面先固定單一接點；P3 換成中央 gateway。

**非目標（本 spec）** — 以下皆**不做**（不是延後必做清單）：

- 自建 LLM router 或直接打模型 HTTP。
- 用 herdr／IDE 對話當 runtime 與帳本來源。
- P0 自建 MCP gateway、條件分支、平行 fan-out、跨 agent 共享記憶。

## Auth 與對話發生在哪

| 模式 | 在哪 | 用途 | 授權 |
|---|---|---|---|
| **Agent CLI（runtime）** | 本機 headless：`agent` / `claude` / `codex` / `gemini` | 依 YAML 自動跑步驟、寫 `usage_events` | **各家登入授權**（Cursor login、Claude／Codex／Gemini 既有 OAuth／訂閱登入）。Repo **不**放 API key；Orchestrator **不**打模型 HTTP。 |
| **對話式 AI（人）** | 你平常的 IDE／產品聊天（例如 **Cursor Chat**、或 Claude／Gemini 網頁／App） | 寫／改 brief、workflow、排查失敗、對焦；產出交回 `briefs/` 等檔案 | 同樣用該產品的登入；**不是**自動流程的執行入口，也**不是**帳本來源 |

一句話：自動跑走 CLI 登入；對焦與設計走你習慣的對話窗，結果寫進 repo 檔案。

## Architecture

```
briefs/*.md  ──►  workflows/*.yaml  ──►  Orchestrator
                      │                      │
                      │                      ├─► CLI Adapter (Cursor first)
                      │                      │         │
                      │                      │         ▼
                      │                      │    Agent CLI (headless)
                      │                      │         │
                      │                      │         ▼
                      │                      │    MCP endpoint (later: gateway)
                      │                      │
                      └─ prompts/* ──────────┘
                                             │
                                             ▼
                                      runs/<run-id>/
                                      (usage_events.jsonl + artifacts)
```

| Layer | Does | Does not |
|---|---|---|
| Brief | 人寫 outcome / acceptance / non-goals | 不寫 CLI 參數散文 |
| Workflow YAML | agent、model、timeout、approval、路徑 | 不發明意圖 |
| Orchestrator | 讀 YAML、spawn、timeout、停失敗、寫 run | 不當 LLM |
| Adapter | 組指令、解析 JSON、正規化 usage | 不內嵌各家 SDK |
| MCP endpoint | 工具連線；P3 起為 gateway | P0 不自建 gateway |

**與 herdr：** herdr 可當人盯盤／處理 blocked 的操作台；本系統的交件、對帳、headless 契約不依賴 herdr。

## Task delivery surfaces

| Artifact | Path | Reader |
|---|---|---|
| 任務對焦 brief | `briefs/<task-id>.md` | 人 + 所有 step prompt 必須引用 |
| 可執行步驟 | `workflows/<task-id>.yaml` | orchestrator；`brief_path` 必填 |
| 每步 prompt | `prompts/<task-id>/<step-id>.md` | adapter；開頭對齊 brief |
| 跑次產物 | `runs/<run-id>/` | 狀態、usage、產出；**不是**對焦入口 |

Brief 最少欄位見 `briefs/_template.md`：`outcome`、`acceptance`、`non_goals`、`constraints`、`preferred_agent` / `preferred_model`、`approval_required`。

之後若用 Notion：同一 schema；MCP 只搬運；repo 內 brief 或明確連結仍為該 run 的 SSOT。

## 怎麼知道有沒有派工在執行

對話窗**不會**顯示自動派工。要看執行狀態，看 runner 寫的檔案／指令（與是否在跑 CLI 無關的「聊天有沒有回」）。

| 看什麼 | 路徑／指令 | 何時有 |
|---|---|---|
| 目前有沒有 run | `runs/current.json`（或同等 symlink／指標）指向進行中的 `run_id`；沒有＝沒有在跑 | P1 |
| 這一 run 狀態 | `runs/<run-id>/status.json`：`queued` → `running` → `awaiting_approval` → `succeeded` \| `failed` \| `cancelled`；含 `workflow_id`、`step_id`、`pid`、`started_at`、`updated_at`、`last_error` | P0 起（單步也寫） |
| 活躍列表 | CLI：`aiwork status`（或同等）讀上述檔，列出 running／awaiting_approval | P1 |
| 即時輸出 | 啟動 runner 的那個終端（stdout／stderr）；可選把 agent stream 落到 `runs/<run-id>/steps/<step-id>/stream.jsonl` | P0 |
| 人要「盯盤」 | 可選：同一 CLI 行程掛在 herdr 窗格；**狀態真相仍是 `status.json`，不是 herdr 螢幕** | 可選，非必做 |

**派工定義：** 只有 orchestrator 建立了 `runs/<run-id>/` 並把 `status` 設成 `running`（或 `awaiting_approval`）才算已派工。只在 Cursor Chat 聊過、或只改了 brief／YAML 但沒執行 runner＝**未派工**。

**批准關卡：** `awaiting_approval` 時 status 檔會寫明等哪一步；人確認後 runner 才進下一步，否則一直停在該狀態（可 `cancel`）。

## Workflow YAML (minimal)

```yaml
id: example-task
brief_path: briefs/example-task.md
trigger: manual
steps:
  - id: explore
    agent: cursor
    model: <cursor-model-slug>
    prompt_file: prompts/example-task/explore.md
    mcp_profile: read-only          # 本步允許哪些 MCP
    skills: [research]              # 本步套用哪些 skill 包
    timeout_sec: 600
    on_fail: stop
    approval: false
  - id: implement
    agent: cursor
    model: <cursor-model-slug>
    prompt_file: prompts/example-task/implement.md
    mcp_profile: coding             # 例如允許 repo／測試，不含 Slack 發文
    skills: [tdd, verification]
    timeout_sec: 1200
    on_fail: stop
    approval: true
```

首版只做 **sequential**。換 model = 新 step，禁止在同一 Cursor 行程內用 Task 換 model。

## MCP 與 Skill（對齊桌面 agent 用法）

可以，而且**按工作環節（step）選**，不要像「整個帳號永遠開全部 MCP／全部 skill」。

### MCP

| 層 | 做什麼 |
|---|---|
| 人／設定 | 像各家 PC 版一樣：在本機註冊要接的 MCP（Notion、Slack、Figma…）；P3 起註冊進中央 gateway 一次 |
| Workflow step | `mcp_profile`：本步允許的 server／tool 子集（例如 `read-only` vs `slack-write`） |
| Adapter | 啟動該 step 的 CLI 時，只帶這個 profile（環境變數、臨時 mcp 設定、或 gateway profile），不把全庫工具塞進每一步 |

P0：先能「選 profile 名稱」；profile 內容可以是簡單 allowlist 檔（例如 `mcp-profiles/read-only.yaml`）。真正「接一個新 MCP」仍走各家／gateway 的設定 UI，orchestrator 不發明第二套 OAuth。

### Skill

| 層 | 做什麼 |
|---|---|
| 人 | Skill 仍用各 agent 原生格式（Cursor skills／rules、Claude `SKILL.md` 等），放在約定目錄，例如 `skills/<pack>/` 或該 agent 的標準路徑 |
| Workflow step | `skills: [pack-a, pack-b]`：本環節要套用的包 |
| Adapter | 啟動 CLI 前把該 step 的 skill 掛進該 agent 看得到的位置（或傳 `--plugin-dir`／同等旗標）；**不**自研另一套 skill 執行引擎 |

原則：MCP／skill 的**能力**來自各家 CLI；本系統只做**哪一步開哪幾個**的編排與稽核。寫入類 MCP 預設搭配 `approval: true`。

## Token accounting

Ledger 是 **`usage_events` 多列**（不是每 run 一筆混帳）。

每列至少：

| Field | Rule |
|---|---|
| `run_id` / `step_id` | 一次 run、一個 YAML step |
| `agent` | `cursor` \| `claude` \| `codex` \| `gemini` |
| `role` | `parent`（P0）；獨立行程才另開列 |
| `model_requested` / `model_actual` | 不一致 → `mismatch` |
| `input_uncached` / `cache_read` / `cache_write` / `output` | Cursor：`inputTokens` = uncached；總 input = 三項相加 |
| `cost_usd` | 可空（Claude 之後可填）；勿硬算錯價 |
| `session_id` | 供 resume（若使用） |
| `dirty` | 偵測到內建 Task 換 model 且無法拆帳 → true |

**Cursor 限制（已接受）：** CLI `result.usage` 與 hook `stop` 為整輪合計；`subagentStop` 無 token。分開計算靠「一步一 CLI」。自訂 subagent 一律 `model: inherit`。混 model Task → 該 step `dirty`。

寫入：`runs/<run-id>/usage_events.jsonl`。

## MCP

| Phase | CLI sees | Credentials |
|---|---|---|
| P0–P2 | 依 step 的 `mcp_profile` 產生／選擇設定；可先多個本機 MCP，但每步只開 profile 允許的 | 各 MCP 自己的 OAuth |
| P3 | 同一 gateway 接點；profile = gateway allowlist | gateway / keychain 統一 |
| Later | 寫入類 tool 可被 gateway 擋或要求批准 | 同上 |

- Orchestrator 只選 `mcp_profile`／`skills`；不實作 Notion／Slack／Figma client，也不自研 skill runtime。
- P3 優先接現成本機 gateway，不從零自研。
- 寫入類工具預設 `approval: true`。

## 成品長什麼樣（有沒有「面板」）

**P0–P4 預設交付的不是**「一個自建控制台：上面聊天交任務、看 token、看進度、設 MCP」。

| 你想做的事 | P0–P4 怎麼做 | 自建面板？ |
|---|---|---|
| 對話交付／對焦任務 | **既有** Cursor Chat（或 Claude／Gemini App）→ 產出寫進 `briefs/` 等 | 不做第二個聊天產品 |
| 查看 token usage | `runs/<run-id>/usage_events.jsonl`；可加 `aiwork usage` 彙總 | 可選之後做 UI 讀同一份 ledger |
| 查看工作進度 | `status.json`、`aiwork status`、啟動 runner 的終端 | 同上 |
| 設定 MCP | 各家 PC 版／gateway 的設定；workflow 只選 `mcp_profile` | 不重做 OAuth 設定 UI |

資料面（brief、workflow、status、usage、mcp_profile）先做對，面板只是之後的**讀寫皮**。若要把「一體化面板」列進目標，另開 **P5**（讀既有 JSON／CLI，不另造帳本）。

## Phased build

| Phase | Deliverable | Done when |
|---|---|---|
| **P0** | Cursor adapter + `usage_events` JSONL + 每步 `status.json`；一步一 model；混 model → dirty | 手動跑一步，ledger 有正確列，且能從 status 看出 running／succeeded／failed |
| **P1** | Sequential YAML runner + `aiwork status` + `runs/current.json`；step 可帶 `mcp_profile` / `skills` | 兩步範例可換不同 profile／skill；人能不靠聊天判斷有無派工 |
| **P2** | Claude / Codex / Gemini 對映同一 `usage_event` schema | 同一 ledger 可混 agent |
| **P3** | 中央 MCP gateway；四家 CLI 單一接點 | credential 與 profile 上收 |
| **P4** | Trigger：手動之後 cron／Slack | 非手動入口可啟動同一 workflow |
| **P5（可選）** | 本機面板：進度、token、觸發 run、選 mcp_profile；**對話交任務仍可外掛既有 Chat 或極簡輸入框** | 能不開終端完成「看狀態／看用量／開跑」；MCP 登入仍連到 gateway／各家，不自建 OAuth |

## Error handling

- Step 非零 exit 或 timeout：`on_fail: stop` → run 失敗；已寫入的 usage 保留。
- `approval: true`：停住等人口頭／檔案確認後才進下一步（P1 實作細節在 plan）。
- `dirty: true`：run 可標記完成但報表標不可信指定-model 帳。

## Testing / acceptance evidence

- P0：對固定 prompt 跑 Cursor headless，檢查 JSONL 欄位與 `model_requested`。
- P1：兩步 workflow，第二步需批准；拒絕則不啟動第二 CLI。
- 不把 dashboard 手抄當成 ledger SSOT。

## Open decisions (closed in this review cycle)

| Topic | Decision |
|---|---|
| P0 agent | Cursor |
| Token split | 一步一 model／一 CLI；非 subagent 混帳 |
| MCP | 目標中央 gateway；P0 起按 step 選 profile；P3 上收 |
| Task 對焦 | `briefs/` SSOT |
| herdr | 可選操作台，非帳本／非 runner |
| UI | **先 P0–P4（檔案 + CLI）**；**P5 再面板／app 化**，只接既有 status／usage／workflow／mcp_profile，不另造資料面 |

## Out of scope until later

平行步驟、條件分支、Admin API 對帳、Notion 當唯一 brief 儲存、自研 gateway、**P0–P4 的自建一體化控制台**（面板屬可選 P5）。

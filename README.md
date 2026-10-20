# aiwork：個人多 Agent AI 工作台

> A local workbench that dispatches tasks to multiple AI coding agents (Cursor, Claude Code, Codex, Gemini) by role, and tracks every run and its usage.

我平常同時用好幾個 AI agent 工作，但每個工具各自開對話、各自計費，很難分工、也很難知道誰做了什麼、花了多少。aiwork 是我為自己做的本機工作台：把任務寫成一份清楚的 brief，依「角色」自動派給最適合的 agent 和模型，一步一步執行，並記錄每一步的狀態與用量。

## 解決什麼問題

- **分工混亂**：規劃、前端、後端、審查各有適合的模型，手動切換容易出錯。→ 用角色對應 agent 與模型，派工時只寫角色。
- **需求靠聊天、容易跑偏**：→ 每個任務先寫 brief（目標、驗收標準、不做什麼），所有步驟都以 brief 為準，不猜聊天內容。
- **看不到執行狀況與成本**：→ 每次執行都有獨立紀錄，可查狀態、逐步用量與費用估算。
- **金鑰外洩風險**：→ 不在 repo 放任何 API key，各 agent 使用自己的 CLI 登入。

## 主要功能

- **多 agent 依序執行**：同一個 workflow 可串接 Cursor、Claude Code、Codex、Gemini CLI。
- **角色派工**：`config/roles.yaml` 定義 planner、writer、frontend、backend、reviewer 等角色與對應模型，可隨時調整。
- **Brief 驅動**：`briefs/` 寫任務對焦，`workflows/` 寫執行步驟，`prompts/` 寫每步指令。
- **執行紀錄與用量**：每次執行寫入 `runs/<run-id>/`，可用 `aiwork status`、`aiwork usage` 查詢。
- **流程控制**：支援人工核准、暫停、取消、失敗重試與從失敗步驟續跑。
- **規則與技能包**：管理 agent 的 rules / skills，可套用、還原與檢查。
- **觀察面板**：以 Vite + Tauri 製作桌面／網頁面板，查看派工、角色與用量。
- **排程觸發**：可搭配 Windows 工作排程器定時執行。

## 架構

```
briefs/*.md ──► workflows/*.yaml ──► Orchestrator ──► CLI Adapter ──► Agent CLI
   （目標與驗收）     （步驟與角色）        │                  （Cursor / Claude / Codex / Gemini）
                                          ▼
                                   runs/<run-id>/（狀態、用量、產出）
```

## 我在這個專案的角色

個人 side project。我負責需求定義、流程與規格設計，並以 AI 協作完成實作：先寫設計規格與實作計畫（見 `docs/`），再拆成任務交給不同 agent 執行與互相審查，最後用自動化測試驗收（`tests/` 內有 40 多個測試檔）。

## 快速開始

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
aiwork roles
aiwork run workflows/smoke.yaml
aiwork status
aiwork usage
```

面板：

```powershell
python panel/scripts/snapshot_server.py --root .
cd panel; npm install; npm run dev
```

## 技術

Python（CLI、orchestrator、測試）、YAML 設定、TypeScript + Vite + Tauri（面板）、各家 agent CLI。

## 關於此版本

這是公開分享用的版本，已移除私人筆記與本機使用紀錄，範例一律使用虛構名稱（如 `MockOrg`、`Acme Corp`）。


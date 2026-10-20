# P5 本機觀測面板 — Design Spec（讀取 MVP）

**Date:** 2026-09-21  
**Status:** approved for implementation  
**Repo:** `ai-work`  
**Depends on:** P0–P4 runner（`runs/` status + usage ledger）

## Intent

本機桌面面板，**只讀**既有 run 狀態與 token 用量，讓人不開終端也能看出「有沒有在跑、跑到哪、花了多少 token」。  
視覺允許非 IDE 風進度隱喻；換皮只動前端，不改帳本。

**成功標準**

- 終端跑 workflow 時，面板能顯示 current run 的 `state`／`step_id`／`last_error`。
- 可選歷史 run，看 status + per-model usage 加總。
- 換 skin／theme 後資料綁定不變。
- 面板不寫入 `runs/`、不呼叫 `aiwork run`／approve／cancel。

## Non-goals（本 MVP）

- 觸發 run、approve、cancel（P5.1）
- 面板內聊天／寫 brief／交派任務
- OAuth／MCP 登入 UI
- 另造 usage 帳本或 Admin API
- 第三方 IP 角色素材（如馬力歐）

## Architecture

```
runs/current.json ─┐
runs/<id>/status.json ─┼─► Tauri read commands ─► React views ─► Skin theme
runs/<id>/usage_events.jsonl ─┘
```

| Layer | Does | Does not |
|---|---|---|
| Disk (`runs/`) | SSOT for status + usage | — |
| Tauri (Rust) | Resolve repo root；讀 JSON／JSONL；回傳 snapshot DTO | 不 spawn agent CLI；不改檔 |
| React UI | 輪詢／顯示；歷史選擇 | 不直接碰磁碟 |
| Skin | 把 state／step 映射成進度隱喻外觀 | 不持有第二份帳本 |

## Data contract

對齊 `aiwork.models.RunStatus` 與 `usage_events.jsonl` 列。

**Snapshot（面板 DTO）**

- `repo_root: string`
- `current_run_id: string | null`
- `selected_run_id: string | null`（UI 選擇；預設跟 current 或最近一筆）
- `status: RunStatus | null`
- `usage_by_model: { [model: string]: { input_uncached, cache_read, cache_write, output, dirty, events, mismatch_events } }`
- `history: { run_id, state, workflow_id, updated_at }[]`（最近 N，預設 20）

## UI

單一主畫面：

1. **Now** — current 或選中 run 的狀態  
2. **Usage** — per-model totals；標 dirty／mismatch  
3. **History** — 可點選  
4. **Progress skin** — 自有趣味隱喻（奔跑／棋格）；`queued`→起點、`running`+step→格數、`succeeded`→終點、`failed`→失敗姿、`awaiting_approval`→暫停格

Repo root：首次選擇並記住（本機設定）。

## Tech

- Tauri 2 + Vite + React + TypeScript，目錄 `panel/`
- 輪詢 1–2s；無 current 時可降頻

## Acceptance

- [ ] Live 或夾帶 fixture run 時，面板顯示正確 state／step  
- [ ] History 切換後 usage／status 跟著變  
- [ ] Theme／skin 可切換且不改 DTO  
- [ ] 全程無寫入 `runs/`（P5 讀取切片；P5.1 改由 CLI 寫入）  

## Open for later

Chat / brief editor in-panel; Admin API.

## P5.1 write

Panel may spawn `python -m aiwork run|approve|cancel` against a selected repo root. Workflow path must stay under `workflows/` (relative, no `..`).

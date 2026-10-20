# Brief: workbench

## Meta

| Field | Value |
|---|---|
| `task_id` | workbench |
| `owner` | <user> |
| `created` | 2026-10-10 |
| `preferred_agent` | gemini |
| `preferred_model` | gemini-3.8-flash-high |
| `approval_required` | false |
| `mcp_profile` | default |

## Outcome

首頁改成工作區：上 1/3 兩個子代理 CLI 加代理區，下 2/3 主代理 CLI，右側上圖下選單。

## Acceptance

- [ ] 首頁不再用遊戲舞台圖當版面
- [ ] 主代理一個、子代理兩個，三格不重複，記在 localStorage
- [ ] 三個視窗都是真實 PTY；派工只在主 CLI
- [ ] 已登入顯示「已登入」；未登入顯示登入按鈕；Gemini 顯示「直接使用」
- [ ] 切到用量頁不中斷三條終端連線

## Non-goals

不改 runner、不改用量資料庫、不自動登入、不預設把 Claude 放進子代理。

## Handoff to workflow

- Prompt：`prompts/home-stage/workbench.md`
- 用 agy 互動模式讀該 prompt，不走 `agy --print`

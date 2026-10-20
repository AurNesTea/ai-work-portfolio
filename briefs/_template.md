# Brief: \<task-id\>

> 複製本檔為 `briefs/<task-id>.md`。對焦只寫這裡；YAML／prompt 引用，不另發明意圖。

## Meta

| Field | Value |
|---|---|
| `task_id` | |
| `owner` | |
| `created` | YYYY-MM-DD |
| `preferred_agent` | cursor \| claude \| codex \| gemini |
| `preferred_model` | （該 agent 的 model slug） |
| `approval_required` | true \| false |
| `mcp_profile` | default \| … |

## Outcome

一句話：完成後世界多了什麼可觀察結果。

## Acceptance

可核對的條件（每條要能用檔案、指令輸出、或畫面證明）：

- [ ]
- [ ]

## Non-goals

這次**不做**：

-

## Constraints

技術／權限／時間／禁止操作：

-

## Context

必要連結或路徑（repo、Notion、設計稿）。沒有就寫「無」。

-

## Handoff to workflow

- Workflow 檔：`workflows/<task-id>.yaml`
- Prompt 目錄：`prompts/<task-id>/`
- 跑次輸出：`runs/`（執行後產生；不是對焦入口）

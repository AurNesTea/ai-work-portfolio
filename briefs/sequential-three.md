# Brief: sequential-three

## Meta

| Field | Value |
|---|---|
| `task_id` | sequential-three |
| `owner` | <user> |
| `created` | 2026-10-11 |
| `preferred_agent` | gemini |
| `preferred_model` | gemini-3.8-flash-high |
| `approval_required` | false |
| `mcp_profile` | default |

## Outcome

同一個 agy 依序做完三件：快捷指令改成兩顆斜線按鈕、重開狀態服務讓登入後接互動模式生效、Claude 做與 Cursor／Codex 相同的無互動核對。

## Acceptance

- [ ] 主代理快捷指令只剩 `/sync-content`、`/update-progress`，登入狀態與 cwd 還在
- [ ] 狀態服務重開後，新的終端連線會走到登入成功後改開互動模式的程式
- [ ] Claude 核對有結果：通過，或明確停在未登入

## Handoff to workflow

- Prompt：`prompts/home-stage/sequential-three.md`
- 用已開著、停在輸入列的 agy。模型維持 Gemini 3.8 Flash (High)。不另開視窗，不走 `agy --print`

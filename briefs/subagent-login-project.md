# Brief: subagent-login-project

## Meta

| Field | Value |
|---|---|
| `task_id` | subagent-login-project |
| `owner` | <user> |
| `created` | 2026-10-10 |
| `preferred_agent` | gemini |
| `preferred_model` | gemini-3.8-flash-high |
| `approval_required` | false |
| `mcp_profile` | default |

## Outcome

子代理在自己的終端裡登入完成後，同一格改開互動模式，工作目錄與主代理相同，就是畫面上選定的專案。

## Acceptance

- [ ] 子代理未登入時，登入發生在該子代理自己的終端，不另開一個沒有專案目錄的視窗
- [ ] 登入成功後，同一格啟動該 CLI 的互動模式，cwd 等於主代理的選定專案
- [ ] 已登入的子代理一開始就在這個目錄
- [ ] Gemini 子代理仍直接開 `agy`，cwd 同樣是選定專案

## Non-goals

不改 runner、不改用量庫、不改主題、不改派工按鈕、不 commit。

## Handoff to workflow

- Prompt：`prompts/home-stage/subagent-login-project.md`
- 用已開著的 agy 互動模式讀該 prompt，不另開視窗，不走 `agy --print`

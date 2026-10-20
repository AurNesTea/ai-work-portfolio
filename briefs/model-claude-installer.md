# Brief: model-claude-installer

## Meta

| Field | Value |
|---|---|
| `task_id` | model-claude-installer |
| `owner` | <user> |
| `created` | 2026-10-11 |
| `preferred_agent` | gemini |
| `preferred_model` | gemini-3.8-flash-high |
| `approval_required` | false |
| `mcp_profile` | default |

## Outcome

依序完成：子代理的 Gemini 名單加上 Gemini 3.8 Flash (High)，Claude 做與 Cursor／Codex 相同的核對，然後做出含這次工作區的桌面安裝檔。

## Acceptance

- [ ] 子代理選 Gemini 時，名單最前面有 `gemini-3.8-flash-high`
- [ ] 沒有公開牌價就不填美元
- [ ] Claude 核對通過，或寫明停在未登入並繼續下一件
- [ ] 桌面安裝檔是這次工作區建出來的

## Handoff to workflow

- Prompt：`prompts/home-stage/model-claude-installer.md`
- 模型 Gemini 3.8 Flash (High)。不走 `agy --print`

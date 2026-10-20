# aiwork 問題整理（截至 2026-09-21）

從設計／實作／審查／Windows live smoke 累積的問題與處置。狀態：`已修`｜`已知限制`｜`延後`｜`待決`。

---

## 1. Live Cursor 串接（Windows）

### 1.1 `WinError 2`：找不到 `agent`

| | |
|---|---|
| **現象** | `aiwork run workflows/smoke.yaml` 立刻 `failed`；`last_error` ≈ `[WinError 2] 系統找不到指定的檔案` |
| **根因** | PATH 上的 `agent` 是 `agent.cmd`。Windows 上 list 形式 `subprocess`（無 `shell=True`）無法直接 CreateProcess `.cmd`／`.bat` |
| **處置** | 新增 `adapters/process.py`：`prepare_cli_argv` 偵測 `.cmd`／`.bat` 後改為 `cmd.exe /c …`；四家 adapter 改走 `run_cli` |
| **狀態** | **已修**（尚未 commit／push） |
| **證據** | 失敗 run `338f5f1803fc` → 修後 probe／smoke 可 spawn |

### 1.2 `UnicodeDecodeError: 'cp950'`

| | |
|---|---|
| **現象** | agent 已能啟動，約數秒後失敗；thread `_readerthread` 解碼炸；`last_error` 曾變 `'NoneType' object has no attribute 'splitlines'`（stdout 讀失敗變 `None`） |
| **根因** | 預設用系統編碼（正體中文 Windows = cp950）讀 agent 的 stream-json |
| **處置** | `run_cli` 預設 `encoding=utf-8`、`errors=replace`；`parse_cursor_stream` 對空／`None` 防呆 |
| **狀態** | **已修**（尚未 commit／push） |
| **證據** | 成功 run `8af1029f6dd6` |

### 1.3 請求 model ≠ 實際 model

| | |
|---|---|
| **現象** | smoke 請求 `composer-2`，ledger 記 `model_actual=Composer 2.5`，`mismatch=true` |
| **根因** | Cursor CLI／帳號端實際選到的 model 與 YAML 字串不一致（非解析錯誤） |
| **處置** | 不擋跑；ledger 標記 mismatch。正規化規則：`Composer 2` ↔ `composer-2` 視為相同；**`2` vs `2.5` 仍算 mismatch** |
| **狀態** | **已知限制**／**待決**：是否改 smoke YAML 的 model id，或接受標記即可 |

---

## 2. 程式審查修復（合進 `feat/aiwork-runner` 的那批）

### 2.1 Resume 跳過失敗步驟（Critical）

| | |
|---|---|
| **現象** | 失敗後 `--resume` 可能略過該步，直接往後跑 |
| **處置** | 以 `steps/<id>/ok`｜`failed` 標記決定是否重跑失敗步 |
| **狀態** | **已修**（commit `f254e47`） |

### 2.2 Adapter 例外後 run 卡住

| | |
|---|---|
| **現象** | adapter 丟例外時狀態／`current.json` 未清乾淨 |
| **處置** | 例外標 `failed`、清 `current` |
| **狀態** | **已修** |

### 2.3 未知 `mcp_profile`／skill 開跑才爆

| | |
|---|---|
| **現象** | 錯誤 profile／skill 可能跑到中途才失敗 |
| **處置** | 開跑前前置驗證 |
| **狀態** | **已修** |

### 2.4 失敗 run 結束碼仍為 0

| | |
|---|---|
| **現象** | CLI exit code 無法區分失敗 |
| **處置** | 失敗非 0 |
| **狀態** | **已修** |

### 2.5 Model mismatch 誤判／過寬

| | |
|---|---|
| **現象** | 字串比對不精確（含版本後綴等）造成假陽性／假陰性 |
| **處置** | `normalize_model` + containment 規則；`Composer 2` ≡ `composer-2` |
| **狀態** | **已修**（與 §1.3 的 2 vs 2.5 標記並存） |

### 2.6 MCP profile 形同裝飾（無 scoped config）

| | |
|---|---|
| **現象** | 只設環境變數、未給 Cursor 實際限縮的 MCP 設定檔 |
| **處置** | 產生 `mcp.generated.json`，Cursor 步驟短暫覆寫 `.cursor/mcp.json`（結束還原） |
| **狀態** | **已修（best-effort）**；無 registry／gateway 時仍非硬隔離 |

---

## 3. 架構／產品上的已知限制

| ID | 問題 | 說明 | 狀態 |
|---|---|---|---|
| L1 | MCP 硬 allowlist | 沒有 `mcp-registry.yaml`／gateway 時，profile 只能 best-effort；真隔離靠 gateway | **已知限制** |
| L2 | Skills 非第二套 runtime | 只把 `SKILL.md` 路徑寫進 prompt；CLI 不自動載入的 agent 必須自己開檔 | **已知限制** |
| L3 | Codex `model_actual` | adapter 可能直接用請求 model，較難自動偵測 mismatch | **已知限制** |
| L4 | 狀態觀測 | 只有 `runs/*/status.json` + `current.json` 算「有在跑」；聊天不算 | **已決定** |
| L5 | 不打模型 HTTP | 認證＝各 CLI login；repo 不放 API key | **已決定** |

---

## 4. Repo／工程雜項

| 問題 | 處置 | 狀態 |
|---|---|---|
| `__pycache__` 曾被 commit | `.gitignore` + untrack（`3c6adf3`） | **已修** |
| 本機無 git remote，無法 push | `gh repo create` → [<user>/ai-work](https://github.com/<user>/ai-work) | **已修** |
| `runs/` 產物不進 git | ignore `runs/*/`，保留 `runs/.gitkeep` | **已修** |
| Shell／sandbox 在 Windows 偶發不穩 | 實作／smoke 改要完整權限執行 | **已知環境限制** |

---

## 5. 刻意延後（Deferred）

| 項目 | 備註 |
|---|---|
| `pid` 未寫入 status | 觀測／殺行程不完整 |
| `current.json` TOCTOU | 並發保護偏弱 |
| cron 深測 | trigger 有接，未做完整 live 驗證 |
| P5 panel／app | 產品分期後做 |
| 平行步驟／自建 LLM router | 非目標 |

---

## 6. Live smoke 結論摘要

| 項目 | 結果 |
|---|---|
| 指令 | `aiwork run workflows/smoke.yaml` |
| 成功 run | `8af1029f6dd6` → `state=succeeded`，step1→step2 |
| Ledger | `usage_events.jsonl` 兩列（每步一列） |
| 單元測試 | 修補後 **26 passed**（含 `test_process_cli`） |
| 未完成 | Windows spawn／UTF-8 修補 **尚未 commit／push**；PR → master 未開 |

---

## 7. 建議後續（依優先）

1. Commit + push：`adapters/process.py` 與相關 adapter／測試變更  
2. 決定 smoke 的 `model:` 要用 `composer-2`（接受 mismatch）還是對齊實際 `Composer 2.5`  
3. 開 PR → `master`  
4. （可選）補 `mcp-registry.yaml` 或 gateway，讓 MCP profile 從 best-effort 變硬限制  

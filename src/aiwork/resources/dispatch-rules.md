# aiwork 派工規則

1. 查表：執行 `aiwork roles`（或 `--json`、`--check`）檢視可用角色與狀態。
2. 選角：依角色的 `description` 選擇合適的 `role` id。無合適角色時停下來問人，不可自創 id。
3. 步驟：workflow 步驟寫 `role: <id>`，不要寫死 agent 與 model。
   範例：
   ```yaml
   steps:
     - id: build-feat
       role: builder
       effort: high
       prompt_file: prompts/task/step1.md
       test_command: python -m pytest
   ```
4. 派工條件：寫完 brief、workflow、prompts 三個檔案後，才執行 `aiwork run workflows/<task>.yaml`。
5. 派工判定：終端印出 `runs/<id>` 且 `runs/<id>/status.json` 存在才算派工成功。

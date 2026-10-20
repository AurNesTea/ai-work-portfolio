# aiwork 派工說明

1. 派工前先執行 `aiwork roles` 查看可用角色與模型。
2. 依角色的 `description` 選擇合適的 role id。
3. workflow 步驟請寫 `role: <id>`（二選一：寫 role 或同時寫 agent 與 model）。
4. 若無合適角色請詢問使用者，切勿自行發明 role id。
5. 寫完 workflow YAML、brief、prompts 三個檔案後，才執行 `aiwork run`。

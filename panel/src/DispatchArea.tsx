import { useEffect, useState } from "react";
import type {
  ModelsCheckResponseDto,
  ModelsResponseDto,
  RoleRowDto,
  RolesResponseDto,
} from "./types";

const SERVER_BASE = "http://127.0.0.1:8765";

type EditableRole = {
  id: string;
  agent: string;
  model: string;
  effort: "low" | "medium" | "high";
  description: string;
  source: "shared" | "local";
  cli_in_path?: boolean;
};

export function DispatchArea() {
  const [target, setTarget] = useState<"shared" | "local">("shared");
  const [roles, setRoles] = useState<EditableRole[]>([]);
  const [etags, setEtags] = useState<Record<string, string>>({});
  const [catalog, setCatalog] = useState<Record<string, string[]>>({});
  const [modelsEtag, setModelsEtag] = useState<string>("");

  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [conflictMsg, setConflictMsg] = useState<string | null>(null);

  // Model check state
  const [checkResult, setCheckResult] = useState<ModelsCheckResponseDto["result"] | null>(null);
  const [checkingModels, setCheckingModels] = useState(false);

  // New model input state per agent
  const [newModelInputs, setNewModelInputs] = useState<Record<string, string>>({
    cursor: "",
    claude: "",
    gemini: "",
  });

  async function loadData() {
    setLoading(true);
    setMsg(null);
    setConflictMsg(null);
    try {
      const [rRes, mRes] = await Promise.all([
        fetch(`${SERVER_BASE}/roles`),
        fetch(`${SERVER_BASE}/models`),
      ]);
      if (rRes.ok) {
        const rData: RolesResponseDto = await rRes.json();
        setEtags(rData.etags || {});
        const roleList: EditableRole[] = Object.entries(rData.roles || {}).map(
          ([id, r]) => ({
            id,
            agent: r.agent,
            model: r.model,
            effort: r.effort || "medium",
            description: r.description,
            source: r.source,
            cli_in_path: r.cli_in_path,
          })
        );
        setRoles(roleList);
      }
      if (mRes.ok) {
        const mData: ModelsResponseDto = await mRes.json();
        setCatalog(mData.models || {});
        setModelsEtag(mData.etag || "");
      }
    } catch (err) {
      setMsg(`載入失敗: ${err}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, []);

  function handleAddRole() {
    const newId = `role-${roles.length + 1}`;
    setRoles([
      ...roles,
      {
        id: newId,
        agent: "gemini",
        model: catalog["gemini"]?.[0] || "gemini-3.8-flash-high",
        effort: "medium",
        description: "新角色說明",
        source: target,
      },
    ]);
  }

  function handleRemoveRole(index: number) {
    const next = [...roles];
    next.splice(index, 1);
    setRoles(next);
  }

  function handleRoleChange(
    index: number,
    field: keyof EditableRole,
    value: string
  ) {
    const next = [...roles];
    next[index] = { ...next[index], [field]: value };
    // If agent changed, pick default model for that agent
    if (field === "agent") {
      const availableModels = catalog[value] || [];
      if (availableModels.length > 0 && !availableModels.includes(next[index].model)) {
        next[index].model = availableModels[0];
      }
    }
    setRoles(next);
  }

  async function handleSaveRoles() {
    setMsg(null);
    setConflictMsg(null);
    const targetEtag = target === "shared" ? etags["roles"] : etags["roles_local"] || "";
    const rolesMap: Record<string, Partial<RoleRowDto>> = {};
    for (const r of roles) {
      // If saving local, we can save all or only local; plan allows local to override/add
      if (target === "shared" && r.source === "local") {
        continue;
      }
      rolesMap[r.id] = {
        agent: r.agent,
        model: r.model,
        effort: r.effort,
        description: r.description,
      };
    }

    try {
      const res = await fetch(`${SERVER_BASE}/roles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: json_stringify({
          target,
          base_etag: targetEtag,
          roles: rolesMap,
        }),
      });
      const data = await res.json();
      if (res.status === 409) {
        setConflictMsg("檔案已被外部修改，請重新載入對照表");
        return;
      }
      if (!res.ok) {
        setMsg(`儲存失敗: ${data.detail || res.statusText}`);
        return;
      }
      setMsg("角色儲存成功！");
      await loadData();
    } catch (err) {
      setMsg(`儲存發生錯誤: ${err}`);
    }
  }

  function handleAddModelToAgent(agent: string, modelId: string) {
    const trimmed = modelId.trim();
    if (!trimmed) return;
    const current = catalog[agent] || [];
    if (current.includes(trimmed)) return;
    setCatalog({
      ...catalog,
      [agent]: [...current, trimmed],
    });
    setNewModelInputs({ ...newModelInputs, [agent]: "" });
  }

  function handleRemoveModel(agent: string, modelId: string) {
    const current = catalog[agent] || [];
    setCatalog({
      ...catalog,
      [agent]: current.filter((m) => m !== modelId),
    });
  }

  async function handleSaveModels() {
    setMsg(null);
    setConflictMsg(null);
    try {
      const res = await fetch(`${SERVER_BASE}/models`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: json_stringify({
          base_etag: modelsEtag,
          models: catalog,
        }),
      });
      const data = await res.json();
      if (res.status === 409) {
        setConflictMsg("模型清單檔案已被外部修改，請重新載入");
        return;
      }
      if (!res.ok) {
        setMsg(`模型儲存失敗: ${data.detail || res.statusText}`);
        return;
      }
      setMsg("模型清單儲存成功！");
      setModelsEtag(data.new_etag || "");
    } catch (err) {
      setMsg(`模型儲存發生錯誤: ${err}`);
    }
  }

  async function handleCheckModels() {
    setCheckingModels(true);
    setMsg(null);
    try {
      const res = await fetch(`${SERVER_BASE}/models/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const data: ModelsCheckResponseDto = await res.json();
      if (res.ok && data.ok) {
        setCheckResult(data.result);
      } else {
        setMsg("檢查模型清單失敗");
      }
    } catch (err) {
      setMsg(`檢查失敗: ${err}`);
    } finally {
      setCheckingModels(false);
    }
  }

  function json_stringify(obj: unknown) {
    return JSON.stringify(obj);
  }

  return (
    <div className="dispatch-area">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
        <h3 style={{ margin: 0, fontSize: "16px" }}>派工對照表 (Roles)</h3>
        <button type="button" onClick={() => void loadData()} disabled={loading} style={{ fontSize: "12px" }}>
          {loading ? "載入中..." : "重新載入"}
        </button>
      </div>

      {conflictMsg && (
        <div style={{ background: "#ff4d4f22", border: "1px solid #ff4d4f", padding: "8px", borderRadius: "4px", marginBottom: "12px", color: "#ff4d4f" }}>
          <span>{conflictMsg}</span>{" "}
          <button type="button" onClick={() => void loadData()} style={{ marginLeft: "8px" }}>
            立即重新載入
          </button>
        </div>
      )}

      {msg && (
        <div style={{ background: "#1890ff22", border: "1px solid #1890ff", padding: "8px", borderRadius: "4px", marginBottom: "12px", color: "#1890ff" }}>
          {msg}
        </div>
      )}

      <div style={{ marginBottom: "12px", display: "flex", gap: "16px", alignItems: "center" }}>
        <span>儲存目標：</span>
        <label style={{ cursor: "pointer" }}>
          <input
            type="radio"
            name="target"
            value="shared"
            checked={target === "shared"}
            onChange={() => setTarget("shared")}
          />{" "}
          共用 (config/roles.yaml，進 git)
        </label>
        <label style={{ cursor: "pointer" }}>
          <input
            type="radio"
            name="target"
            value="local"
            checked={target === "local"}
            onChange={() => setTarget("local")}
          />{" "}
          只這台電腦 (~/.aiwork/roles.local.yaml)
        </label>
      </div>

      <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: "12px", fontSize: "13px" }}>
        <thead>
          <tr style={{ borderBottom: "1px solid rgba(128,128,128,0.3)", textAlign: "left" }}>
            <th style={{ padding: "6px" }}>角色 ID</th>
            <th style={{ padding: "6px" }}>CLI 廠商</th>
            <th style={{ padding: "6px" }}>模型</th>
            <th style={{ padding: "6px" }}>推理強度</th>
            <th style={{ padding: "6px" }}>說明 (何時用)</th>
            <th style={{ padding: "6px" }}>來源</th>
            <th style={{ padding: "6px" }}>操作</th>
          </tr>
        </thead>
        <tbody>
          {roles.map((r, idx) => {
            const availableModels = catalog[r.agent] || [];
            return (
              <tr key={idx} style={{ borderBottom: "1px solid rgba(128,128,128,0.15)" }}>
                <td style={{ padding: "6px" }}>
                  <input
                    type="text"
                    value={r.id}
                    onChange={(e) => handleRoleChange(idx, "id", e.target.value)}
                    style={{ width: "90px", fontSize: "12px" }}
                  />
                </td>
                <td style={{ padding: "6px" }}>
                  <select
                    value={r.agent}
                    onChange={(e) => handleRoleChange(idx, "agent", e.target.value)}
                    style={{ fontSize: "12px" }}
                  >
                    <option value="gemini">Gemini（agy）</option>
                    <option value="cursor">Cursor</option>
                    <option value="claude">Claude</option>
                  </select>
                  {r.cli_in_path === false && (
                    <span style={{ color: "#faad14", fontSize: "11px", marginLeft: "4px" }} title="CLI 未在 PATH 中">
                      (未在 PATH)
                    </span>
                  )}
                </td>
                <td style={{ padding: "6px" }}>
                  <select
                    value={r.model}
                    onChange={(e) => handleRoleChange(idx, "model", e.target.value)}
                    style={{ fontSize: "12px", maxWidth: "160px" }}
                  >
                    {availableModels.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                    {!availableModels.includes(r.model) && (
                      <option value={r.model}>{r.model} (非清單)</option>
                    )}
                  </select>
                </td>
                <td style={{ padding: "6px" }}>
                  <select
                    value={r.effort}
                    onChange={(e) =>
                      handleRoleChange(idx, "effort", e.target.value as "low" | "medium" | "high")
                    }
                    style={{ fontSize: "12px" }}
                  >
                    <option value="low">low</option>
                    <option value="medium">medium</option>
                    <option value="high">high</option>
                  </select>
                </td>
                <td style={{ padding: "6px" }}>
                  <input
                    type="text"
                    value={r.description}
                    onChange={(e) => handleRoleChange(idx, "description", e.target.value)}
                    style={{ width: "100%", minWidth: "140px", fontSize: "12px" }}
                  />
                </td>
                <td style={{ padding: "6px" }}>
                  <span
                    style={{
                      fontSize: "11px",
                      padding: "2px 6px",
                      borderRadius: "4px",
                      background: r.source === "local" ? "rgba(250, 173, 20, 0.2)" : "rgba(24, 144, 255, 0.2)",
                    }}
                  >
                    {r.source === "local" ? "本機" : "共用"}
                  </span>
                </td>
                <td style={{ padding: "6px" }}>
                  <button type="button" onClick={() => handleRemoveRole(idx)} style={{ fontSize: "11px", color: "#ff4d4f" }}>
                    刪除
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div style={{ display: "flex", gap: "8px", marginBottom: "24px" }}>
        <button type="button" onClick={handleAddRole} style={{ fontSize: "12px" }}>
          + 新增角色
        </button>
        <button type="button" onClick={() => void handleSaveRoles()} style={{ fontSize: "12px", fontWeight: "bold" }}>
          儲存派工角色 ({target === "shared" ? "共用" : "本機"})
        </button>
      </div>

      <hr style={{ borderColor: "rgba(128,128,128,0.2)", margin: "20px 0" }} />

      {/* Models Catalog Section */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
        <h3 style={{ margin: 0, fontSize: "16px" }}>模型清單 (Models Catalog)</h3>
        <div style={{ display: "flex", gap: "8px" }}>
          <button type="button" onClick={() => void handleCheckModels()} disabled={checkingModels} style={{ fontSize: "12px" }}>
            {checkingModels ? "檢查中..." : "檢查模型清單"}
          </button>
          <button type="button" onClick={() => void handleSaveModels()} style={{ fontSize: "12px", fontWeight: "bold" }}>
            儲存模型清單
          </button>
        </div>
      </div>

      {checkResult && (
        <div style={{ background: "rgba(0,0,0,0.2)", border: "1px solid rgba(128,128,128,0.3)", padding: "10px", borderRadius: "4px", marginBottom: "16px", fontSize: "12px" }}>
          <h4 style={{ margin: "0 0 8px 0" }}>檢查結果：</h4>
          {Object.entries(checkResult).map(([agent, res]) => (
            <div key={agent} style={{ marginBottom: "8px" }}>
              <strong>[{agent}]</strong>:{" "}
              {res.status === "notice" && <span style={{ color: "#faad14" }}>{res.message}</span>}
              {res.status === "error" && <span style={{ color: "#ff4d4f" }}>{res.message}</span>}
              {res.status === "ok" && (
                <>
                  {!res.extra_in_cli?.length && !res.missing_in_cli?.length && (
                    <span style={{ color: "#52c41a" }}>已同步 (共 {res.total_catalog} 個模型)</span>
                  )}
                  {Boolean(res.extra_in_cli?.length) && (
                    <div style={{ color: "#faad14", marginTop: "4px" }}>
                      CLI 有、清單沒有:
                      {res.extra_in_cli?.map((m) => (
                        <span key={m} style={{ marginLeft: "8px" }}>
                          <code>{m}</code>{" "}
                          <button
                            type="button"
                            onClick={() => handleAddModelToAgent(agent, m)}
                            style={{ fontSize: "10px", padding: "1px 4px" }}
                          >
                            + 加入
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                  {Boolean(res.missing_in_cli?.length) && (
                    <div style={{ color: "#faad14", marginTop: "4px" }}>
                      清單有、CLI 沒有: {res.missing_in_cli?.join(", ")}
                    </div>
                  )}
                </>
              )}
            </div>
          ))}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "12px" }}>
        {["cursor", "claude", "gemini"].map((agent) => (
          <div key={agent} style={{ border: "1px solid rgba(128,128,128,0.3)", borderRadius: "4px", padding: "10px" }}>
            <h4 style={{ margin: "0 0 8px 0", textTransform: "capitalize" }}>
              {agent === "gemini" ? "Gemini（agy）" : agent} ({catalog[agent]?.length || 0})
            </h4>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", maxHeight: "150px", overflowY: "auto", marginBottom: "8px" }}>
              {(catalog[agent] || []).map((m) => (
                <span
                  key={m}
                  style={{
                    fontSize: "11px",
                    background: "rgba(128,128,128,0.2)",
                    padding: "2px 6px",
                    borderRadius: "3px",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "4px",
                  }}
                >
                  {m}
                  <button
                    type="button"
                    onClick={() => handleRemoveModel(agent, m)}
                    style={{ border: "none", background: "none", cursor: "pointer", color: "#ff4d4f", fontSize: "10px", padding: 0 }}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
            <div style={{ display: "flex", gap: "4px" }}>
              <input
                type="text"
                placeholder="新增模型 ID..."
                value={newModelInputs[agent] || ""}
                onChange={(e) => setNewModelInputs({ ...newModelInputs, [agent]: e.target.value })}
                style={{ flex: 1, fontSize: "12px" }}
              />
              <button
                type="button"
                onClick={() => handleAddModelToAgent(agent, newModelInputs[agent] || "")}
                style={{ fontSize: "11px" }}
              >
                +
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

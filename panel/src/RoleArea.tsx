import { useEffect, useState, type ChangeEvent } from "react";
import type { RoleRowDto, RolesResponseDto } from "./types";

const SERVER_BASE = "http://127.0.0.1:8765";

export type RoleItem = {
  id: string;
  dispatch_summary?: string;
  agent?: string;
  model?: string;
  effort?: string;
  description: string;
  principles: string;
  skills: string[];
  defined: string;
  delivery: string;
  source: string;
  is_external: boolean;
  external_path?: string;
};

export type SkillMeta = {
  name: string;
  description: string;
  source: string;
  path?: string;
};

export type PackItemDto = {
  kind: string;
  name: string;
  path?: string;
  sha256?: string;
  has_scripts?: boolean;
};

export type PackDto = {
  id: string;
  name: string;
  description: string;
  version: number | string;
  enabled: boolean;
  has_scripts: boolean;
  path?: string | null;
  items: PackItemDto[];
};

export type MachineEntryDto = {
  target_path: string;
  source_pack: string;
  mode: string;
  status: "intact" | "modified" | "missing";
  backup_path?: string | null;
};

export type CliDirInfoDto = {
  path: string;
  exists: boolean;
  realpath: string;
  is_link: boolean;
};

export type MachineStatusDto = {
  machine_name: string;
  scope: string;
  libraries: string[];
  enabled_packs: string[];
  applied_count: number;
  manifest_path: string;
  entries: MachineEntryDto[];
  cli_dirs: Record<string, CliDirInfoDto>;
  probe?: {
    updated_at?: string;
    results?: Record<
      string,
      {
        status: string;
        label: string;
        passed: boolean;
        model?: string;
        detail?: string;
      }
    >;
  };
};

export type UploadPreviewDto = {
  upload_id: string;
  files: Array<{
    path: string;
    size: number;
    sha256: string;
    kind: string;
    has_scripts: boolean;
  }>;
  has_scripts: boolean;
  warning: string;
};

export type DryRunPlanDto = {
  add: Array<{ kind: string; target_path: string; mode: string }>;
  replace: Array<{ kind: string; target_path: string; mode: string }>;
  conflicts: Array<{ target_path: string; reason: string }>;
  dirs_to_create: string[];
};

type Props = {
  onNavigateToDispatch?: () => void;
};

export function RoleArea({ onNavigateToDispatch }: Props) {
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<{ text: string; type: "ok" | "err" | "info" } | null>(null);

  // Section 1: Roles
  const [roles, setRoles] = useState<RoleItem[]>([]);
  const [editingRole, setEditingRole] = useState<RoleItem | null>(null);
  const [isCreatingRole, setIsCreatingRole] = useState(false);
  const [skillPool, setSkillPool] = useState<Record<string, SkillMeta>>({});

  // Section 2: Library & Upload
  const [packs, setPacks] = useState<PackDto[]>([]);
  const [uploadPreview, setUploadPreview] = useState<UploadPreviewDto | null>(null);
  const [commitPackId, setCommitPackId] = useState("");
  const [commitReplace, setCommitReplace] = useState(false);
  const [uploading, setUploading] = useState(false);

  // Section 3: Machine & Apply & Probe
  const [machine, setMachine] = useState<MachineStatusDto | null>(null);
  const [dryRunPlan, setDryRunPlan] = useState<DryRunPlanDto | null>(null);
  const [applyReplace, setApplyReplace] = useState(false);
  const [probing, setProbing] = useState(false);
  const [applying, setApplying] = useState(false);

  async function loadAll() {
    setLoading(true);
    try {
      const [rRes, libRes, mRes, skRes] = await Promise.all([
        fetch(`${SERVER_BASE}/roles`),
        fetch(`${SERVER_BASE}/library`),
        fetch(`${SERVER_BASE}/machine`),
        fetch(`${SERVER_BASE}/skills`),
      ]);

      let poolData: Record<string, SkillMeta> = {};
      if (skRes.ok) {
        const skJson = await skRes.json();
        poolData = skJson.skills || {};
        setSkillPool(poolData);
      }

      let dispatchRoles: Record<string, RoleRowDto> = {};
      if (rRes.ok) {
        const rJson: RolesResponseDto = await rRes.json();
        dispatchRoles = rJson.roles || {};
      }

      let packList: PackDto[] = [];
      if (libRes.ok) {
        const libJson = await libRes.json();
        packList = libJson.packs || [];
        setPacks(packList);
      }

      let machineData: MachineStatusDto | null = null;
      if (mRes.ok) {
        const mJson = await mRes.json();
        machineData = mJson.machine || null;
        setMachine(machineData);
      }

      // Merge dispatch roles and defined roles into union
      const roleMap: Record<string, RoleItem> = {};

      // 1. From dispatch roles
      for (const [id, r] of Object.entries(dispatchRoles)) {
        const disp = `${r.agent || "—"} / ${r.model || "—"}${r.effort ? ` (${r.effort})` : ""}`;
        const src = (r as any).source as string | undefined;
        const isExt = src === "kit" || src === "external";
        roleMap[id] = {
          id,
          dispatch_summary: disp,
          agent: r.agent,
          model: r.model,
          effort: r.effort,
          description: r.description || "",
          principles: "",
          skills: [],
          defined: (r as any).defined || "no",
          delivery: (r as any).delivery || "none",
          source: r.source || "shared",
          is_external: isExt,
          external_path: isExt ? (r as any).defined : undefined,
        };
      }

      // 2. From packs' agent files
      for (const p of packList) {
        for (const item of p.items) {
          if (item.kind === "agent") {
            const roleId = item.name.replace(/\.md$/i, "");
            if (!roleMap[roleId]) {
              roleMap[roleId] = {
                id: roleId,
                dispatch_summary: "（未派工）",
                description: "",
                principles: "",
                skills: [],
                defined: item.path || "yes",
                delivery: "none",
                source: p.id === "local-roles" ? "local" : `pack:${p.id}`,
                is_external: false,
              };
            } else if (roleMap[roleId].source === "shared" && p.id === "local-roles") {
              roleMap[roleId].source = "local";
            }
          }
        }
      }

      setRoles(Object.values(roleMap).sort((a, b) => a.id.localeCompare(b.id)));
    } catch (err) {
      setMsg({ text: `載入失敗: ${String(err)}`, type: "err" });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadAll();
  }, []);

  // -------------------------------------------------------------
  // Role Editing Handlers
  // -------------------------------------------------------------
  function handleStartEdit(role: RoleItem) {
    setIsCreatingRole(false);
    setEditingRole({ ...role });
  }

  function handleStartCreate() {
    setIsCreatingRole(true);
    setEditingRole({
      id: "",
      description: "",
      principles: "# 工作原則\n請依下列原則執行工作：\n",
      skills: [],
      defined: "no",
      delivery: "none",
      source: "local",
      is_external: false,
    });
  }

  function handleToggleSkill(skillName: string) {
    if (!editingRole) return;
    const current = new Set(editingRole.skills);
    if (current.has(skillName)) {
      current.delete(skillName);
    } else {
      current.add(skillName);
    }
    setEditingRole({ ...editingRole, skills: Array.from(current) });
  }

  async function handleSaveRole() {
    if (!editingRole) return;
    const roleId = editingRole.id.trim();
    if (!roleId) {
      setMsg({ text: "角色 ID 不得為空", type: "err" });
      return;
    }
    setLoading(true);
    setMsg(null);
    try {
      const res = await fetch(`${SERVER_BASE}/role`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: roleId,
          description: editingRole.description,
          principles: editingRole.principles,
          skills: editingRole.skills,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMsg({ text: `儲存角色失敗: ${data.detail || res.statusText}`, type: "err" });
        return;
      }
      setMsg({ text: `角色 '${roleId}' 儲存成功！`, type: "ok" });
      setEditingRole(null);
      setIsCreatingRole(false);
      await loadAll();
    } catch (err) {
      setMsg({ text: `儲存發生錯誤: ${String(err)}`, type: "err" });
    } finally {
      setLoading(false);
    }
  }

  // -------------------------------------------------------------
  // Upload & Library Handlers
  // -------------------------------------------------------------
  async function handleFileUpload(e: ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    setUploading(true);
    setMsg(null);
    setUploadPreview(null);

    try {
      const file = files[0];
      const fname = file.name;

      let res: Response;
      if (file.name.toLowerCase().endsWith(".zip")) {
        const buffer = await file.arrayBuffer();
        res = await fetch(`${SERVER_BASE}/library/upload`, {
          method: "POST",
          headers: { "Content-Type": "application/zip" },
          body: buffer,
        });
      } else {
        const text = await file.text();
        res = await fetch(`${SERVER_BASE}/library/upload`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            filename: fname,
            content: text,
          }),
        });
      }

      const data = await res.json();
      if (!res.ok) {
        setMsg({ text: `上傳失敗: ${data.detail || res.statusText}`, type: "err" });
        return;
      }

      setUploadPreview(data);
      const suggestedId = file.name.replace(/\.[^/.]+$/, "").toLowerCase().replace(/[^a-z0-9_-]/g, "-");
      setCommitPackId(suggestedId || "uploaded-pack");
      setMsg({ text: "檔案上傳暫存成功，請檢閱後確認入庫", type: "info" });
    } catch (err) {
      setMsg({ text: `上傳發生錯誤: ${String(err)}`, type: "err" });
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

  async function handleCommitPack() {
    if (!uploadPreview || !commitPackId.trim()) return;
    setLoading(true);
    setMsg(null);
    try {
      const res = await fetch(`${SERVER_BASE}/library/commit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          upload_id: uploadPreview.upload_id,
          pack_id: commitPackId.trim(),
          replace: commitReplace,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMsg({ text: `入庫失敗: ${data.detail || res.statusText}`, type: "err" });
        return;
      }
      setMsg({ text: `素材包 '${commitPackId}' 入庫成功！`, type: "ok" });
      setUploadPreview(null);
      setCommitPackId("");
      await loadAll();
    } catch (err) {
      setMsg({ text: `入庫發生錯誤: ${String(err)}`, type: "err" });
    } finally {
      setLoading(false);
    }
  }

  // -------------------------------------------------------------
  // Machine Profile & Apply Handlers
  // -------------------------------------------------------------
  async function handleTogglePackEnable(packId: string, currentEnabled: boolean) {
    setLoading(true);
    try {
      const res = await fetch(`${SERVER_BASE}/machine/enable`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pack_id: packId,
          enabled: !currentEnabled,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMsg({ text: `變更素材包啟用失敗: ${data.detail || res.statusText}`, type: "err" });
        return;
      }
      await loadAll();
    } catch (err) {
      setMsg({ text: `變更素材包狀態失敗: ${String(err)}`, type: "err" });
    } finally {
      setLoading(false);
    }
  }

  async function handleRequestApply(dryRun = true) {
    setApplying(true);
    setMsg(null);
    try {
      const res = await fetch(`${SERVER_BASE}/machine/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dry_run: dryRun,
          replace: applyReplace,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMsg({ text: `套用失敗: ${data.detail || res.statusText}`, type: "err" });
        return;
      }

      if (dryRun) {
        setDryRunPlan(data.plans || null);
        setMsg({ text: "已產生 Dry-run 計畫，請檢視後確認真套用", type: "info" });
      } else {
        setDryRunPlan(null);
        setMsg({ text: `套用成功！已寫入 ${data.applied_count || 0} 個項目`, type: "ok" });
        await loadAll();
      }
    } catch (err) {
      setMsg({ text: `套用執行發生錯誤: ${String(err)}`, type: "err" });
    } finally {
      setApplying(false);
    }
  }

  async function handleUndo() {
    if (!window.confirm("確定要執行一鍵還原嗎？將刪除所有由 aiwork 套用的檔案並復原備份。")) {
      return;
    }
    setApplying(true);
    setMsg(null);
    try {
      const res = await fetch(`${SERVER_BASE}/machine/undo`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (!res.ok) {
        setMsg({ text: `還原失敗: ${data.detail || res.statusText}`, type: "err" });
        return;
      }
      setMsg({
        text: `還原完成！已刪除 ${data.removed?.length || 0} 個檔，復原 ${data.restored?.length || 0} 個備份`,
        type: "ok",
      });
      await loadAll();
    } catch (err) {
      setMsg({ text: `還原發生錯誤: ${String(err)}`, type: "err" });
    } finally {
      setApplying(false);
    }
  }

  async function handleRunProbe() {
    setProbing(true);
    setMsg(null);
    try {
      const res = await fetch(`${SERVER_BASE}/machine/probe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (!res.ok) {
        setMsg({ text: `探針執行失敗: ${data.detail || res.statusText}`, type: "err" });
        return;
      }
      setMsg({ text: "探針檢驗完成，已更新最新狀態！", type: "ok" });
      await loadAll();
    } catch (err) {
      setMsg({ text: `探針執行發生錯誤: ${String(err)}`, type: "err" });
    } finally {
      setProbing(false);
    }
  }

  const probeResults = machine?.probe?.results || {};

  return (
    <div className="role-area-container">
      {/* 頂部控制列 */}
      <div className="role-area-header">
        <div>
          <h2>角色與素材管理</h2>
          <p className="role-subtitle">
            定義角色原則與技能標籤、素材包安全入庫預覽、一鍵套用至各 CLI 目錄與探針送達檢驗
          </p>
        </div>
        <div className="role-header-actions">
          <button
            type="button"
            className="btn-primary"
            onClick={handleStartCreate}
            disabled={loading}
          >
            + 定義新角色
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => void loadAll()}
            disabled={loading}
          >
            {loading ? "更新中..." : "重新載入"}
          </button>
        </div>
      </div>

      {msg && (
        <div className={`role-alert is-${msg.type}`}>
          {msg.text}
          <button type="button" className="alert-close" onClick={() => setMsg(null)}>
            ×
          </button>
        </div>
      )}

      {/* 區域 1：角色清單與定義編輯 */}
      <section className="role-section">
        <div className="section-title-row">
          <h3>區域 1：角色清單與定義</h3>
          <span className="section-badge">{roles.length} 個角色</span>
        </div>

        <div className="role-table-wrapper">
          <table className="role-table">
            <thead>
              <tr>
                <th>角色 ID</th>
                <th>派工摘要</th>
                <th>說明</th>
                <th>工作原則摘要</th>
                <th>所用技能標籤</th>
                <th>送達狀態</th>
                <th>來源</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {roles.map((r) => {
                const probeForAgent = r.agent ? probeResults[r.agent] : undefined;
                return (
                  <tr key={r.id}>
                    <td className="cell-role-id">
                      <strong>{r.id}</strong>
                    </td>
                    <td>
                      <div className="dispatch-summary-box">
                        <span>{r.dispatch_summary}</span>
                        {onNavigateToDispatch && (
                          <button
                            type="button"
                            className="btn-link"
                            onClick={onNavigateToDispatch}
                            title="前往派工頁修改此角色的模型與 CLI"
                          >
                            修改派工
                          </button>
                        )}
                      </div>
                    </td>
                    <td>{r.description || <span className="muted-text">無</span>}</td>
                    <td>
                      <span className="principles-snippet">
                        {r.principles ? r.principles.slice(0, 45) + "..." : <span className="muted-text">—</span>}
                      </span>
                    </td>
                    <td>
                      <div className="skill-tags-group">
                        {r.skills && r.skills.length > 0 ? (
                          r.skills.map((s) => {
                            const isMissing = !skillPool[s];
                            return (
                              <span
                                key={s}
                                className={`skill-tag ${isMissing ? "is-missing" : "is-available"}`}
                                title={isMissing ? "技能池缺此技能！" : skillPool[s]?.description || s}
                              >
                                {s} {isMissing && "(缺)"}
                              </span>
                            );
                          })
                        ) : (
                          <span className="muted-text">無</span>
                        )}
                      </div>
                    </td>
                    <td>
                      <div className="delivery-status-box">
                        <span className={`status-pill ${r.delivery === "prompt-path" ? "is-ok" : "is-none"}`}>
                          {r.delivery}
                        </span>
                        {probeForAgent && (
                          <span
                            className={`probe-indicator ${probeForAgent.passed ? "is-passed" : "is-failed"}`}
                            title={`探針檢驗: ${probeForAgent.label || probeForAgent.status}`}
                          >
                            • {probeForAgent.label}
                          </span>
                        )}
                      </div>
                    </td>
                    <td>
                      <span className="source-tag">{r.source}</span>
                    </td>
                    <td>
                      {r.is_external ? (
                        <span className="external-badge" title={`外部管理唯讀 (${r.external_path || ""})`}>
                          唯讀 (kit)
                        </span>
                      ) : (
                        <button
                          type="button"
                          className="btn-action"
                          onClick={() => handleStartEdit(r)}
                        >
                          編輯
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* 角色編輯 / 建立面板 */}
        {editingRole && (
          <div className="role-editor-card">
            <h4>{isCreatingRole ? "定義新角色" : `編輯角色: ${editingRole.id}`}</h4>
            <div className="editor-form-grid">
              <label>
                角色 ID (格式 [a-z][a-z0-9-]{"{0,31}"}):
                <input
                  type="text"
                  value={editingRole.id}
                  disabled={!isCreatingRole}
                  onChange={(e) => setEditingRole({ ...editingRole, id: e.target.value.toLowerCase() })}
                  placeholder="例如: builder, planner, reviewer"
                />
              </label>

              <label>
                角色說明 (Description):
                <input
                  type="text"
                  value={editingRole.description}
                  onChange={(e) => setEditingRole({ ...editingRole, description: e.target.value })}
                  placeholder="簡短描述角色的職責"
                />
              </label>

              <label className="full-width">
                工作原則 (Principles Markdown):
                <textarea
                  rows={6}
                  value={editingRole.principles}
                  onChange={(e) => setEditingRole({ ...editingRole, principles: e.target.value })}
                  placeholder="# 工作原則&#10;請依下列原則執行工作：..."
                />
              </label>

              <div className="full-width">
                <span className="field-label">所用技能 (從技能池多選):</span>
                <div className="skills-selection-grid">
                  {Object.values(skillPool).map((sk) => {
                    const checked = editingRole.skills.includes(sk.name);
                    return (
                      <label key={sk.name} className={`skill-checkbox-label ${checked ? "is-checked" : ""}`}>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => handleToggleSkill(sk.name)}
                        />
                        <span className="skill-name">{sk.name}</span>
                        <span className="skill-desc">{sk.description}</span>
                      </label>
                    );
                  })}
                  {Object.keys(skillPool).length === 0 && (
                    <span className="muted-text">技能池無可用技能</span>
                  )}
                </div>
              </div>
            </div>

            <div className="editor-actions">
              <button type="button" className="btn-primary" onClick={handleSaveRole} disabled={loading}>
                儲存至 local-roles
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => {
                  setEditingRole(null);
                  setIsCreatingRole(false);
                }}
              >
                取消
              </button>
            </div>
          </div>
        )}
      </section>

      {/* 區域 2：素材庫與上傳 */}
      <section className="role-section">
        <div className="section-title-row">
          <h3>區域 2：素材庫與上傳</h3>
          <span className="section-badge">{packs.length} 個素材包</span>
        </div>

        {/* 上傳觸發區 */}
        <div className="upload-box">
          <div className="upload-prompt">
            <span className="upload-icon">📦</span>
            <div>
              <strong>上傳角色、規則或技能素材包</strong>
              <p>支援 .zip 壓縮包，或單一 .md / .mdc 角色與規則檔（上限 5 MB）</p>
            </div>
          </div>
          <label className="btn-upload">
            選擇檔案上傳
            <input
              type="file"
              accept=".zip,.md,.mdc,.yaml,.yml,.json,.txt"
              style={{ display: "none" }}
              onChange={handleFileUpload}
              disabled={uploading}
            />
          </label>
        </div>

        {/* 上傳暫存入庫預覽 */}
        {uploadPreview && (
          <div className="preview-card">
            <h4>入庫預覽 (Staging ID: {uploadPreview.upload_id})</h4>
            {uploadPreview.warning && (
              <div className="security-warning">⚠️ {uploadPreview.warning}</div>
            )}

            <div className="preview-files-list">
              <table>
                <thead>
                  <tr>
                    <th>檔案路徑</th>
                    <th>種類</th>
                    <th>大小</th>
                    <th>腳本警示</th>
                    <th>SHA-256</th>
                  </tr>
                </thead>
                <tbody>
                  {uploadPreview.files.map((f) => (
                    <tr key={f.path}>
                      <td>{f.path}</td>
                      <td>
                        <span className="kind-pill">{f.kind}</span>
                      </td>
                      <td>{f.size} B</td>
                      <td>
                        {f.has_scripts ? (
                          <span className="script-badge">含腳本</span>
                        ) : (
                          <span className="muted-text">無</span>
                        )}
                      </td>
                      <td>
                        <code>{f.sha256.slice(0, 16)}...</code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="commit-form-row">
              <label>
                素材包 ID (Pack ID):
                <input
                  type="text"
                  value={commitPackId}
                  onChange={(e) => setCommitPackId(e.target.value.toLowerCase())}
                  placeholder="例如: my-team-pack"
                />
              </label>
              <label className="checkbox-inline">
                <input
                  type="checkbox"
                  checked={commitReplace}
                  onChange={(e) => setCommitReplace(e.target.checked)}
                />
                覆寫既有素材包 (若存在先備份)
              </label>
              <button
                type="button"
                className="btn-primary"
                onClick={handleCommitPack}
                disabled={loading || !commitPackId.trim()}
              >
                確認移入素材庫
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setUploadPreview(null)}
              >
                捨棄暫存
              </button>
            </div>
          </div>
        )}

        {/* 素材庫素材包清單 */}
        <div className="packs-grid">
          {packs.map((p) => (
            <div key={p.id} className={`pack-card ${p.enabled ? "is-enabled" : ""}`}>
              <div className="pack-card-header">
                <div>
                  <h4>
                    {p.name} <span className="version-tag">v{p.version}</span>
                  </h4>
                  <span className="pack-id">ID: {p.id}</span>
                </div>
                <label className="switch-toggle" title="切換啟用/停用此素材包">
                  <input
                    type="checkbox"
                    checked={p.enabled}
                    onChange={() => void handleTogglePackEnable(p.id, p.enabled)}
                  />
                  <span className="slider" />
                </label>
              </div>
              <p className="pack-desc">{p.description || "無描述"}</p>
              <div className="pack-items-summary">
                <span>包含項目 ({p.items.length}):</span>
                <ul>
                  {p.items.map((it) => (
                    <li key={`${it.kind}-${it.name}`}>
                      [{it.kind}] {it.name}
                      {it.has_scripts && <span className="script-badge">腳本</span>}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* 區域 3：這台電腦 (Machine Profile) */}
      <section className="role-section">
        <div className="section-title-row">
          <h3>區域 3：這台電腦 (Machine Profile)</h3>
          <span className="machine-name-tag">{machine?.machine_name || "本機電腦"}</span>
        </div>

        {machine && (
          <div className="machine-content-grid">
            {/* CLI 目錄狀況 */}
            <div className="machine-card">
              <h4>CLI 目錄偵測</h4>
              <div className="cli-dirs-list">
                {Object.entries(machine.cli_dirs).map(([cli, info]) => (
                  <div key={cli} className="cli-dir-row">
                    <span className="cli-name">{cli}:</span>
                    <span className="cli-path" title={info.realpath}>
                      {info.path}
                    </span>
                    <span className={`status-badge ${info.exists ? "is-exists" : "is-missing"}`}>
                      {info.exists ? (info.is_link ? "連線 (link)" : "存在") : "尚未建立"}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* 探針與套用操作 */}
            <div className="machine-card">
              <h4>套用與探針操作</h4>
              <div className="actions-cluster">
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => void handleRequestApply(true)}
                  disabled={applying}
                >
                  {applying ? "處理中..." : "套用啟用素材包 (Dry-run)"}
                </button>
                <button
                  type="button"
                  className="btn-danger"
                  onClick={() => void handleUndo()}
                  disabled={applying}
                >
                  一鍵還原 (Undo)
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => void handleRunProbe()}
                  disabled={probing}
                >
                  {probing ? "探針執行中..." : "⚡ 執行探針 (Probe)"}
                </button>
              </div>

              {/* 最近探針結果 */}
              <div className="probe-summary-box">
                <strong>最近一次探針檢驗:</strong>
                {machine.probe?.updated_at ? (
                  <div className="probe-results-tags">
                    <span className="muted-text">時間: {new Date(machine.probe.updated_at).toLocaleString()}</span>
                    {Object.entries(probeResults).map(([ag, pr]) => (
                      <span
                        key={ag}
                        className={`probe-tag ${pr.passed ? "is-pass" : pr.status === "not_logged_in" ? "is-warn" : "is-fail"}`}
                      >
                        {ag}: {pr.label || pr.status}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="muted-text"> 尚未執行過探針</span>
                )}
              </div>
            </div>
          </div>
        )}

        {/* 套用清單一致性狀態 */}
        {machine && machine.entries && machine.entries.length > 0 && (
          <div className="manifest-section">
            <h4>已套用項目一致性 ({machine.applied_count} 筆)</h4>
            <div className="manifest-table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>目標路徑</th>
                    <th>來源素材包</th>
                    <th>寫入模式</th>
                    <th>狀態標籤</th>
                  </tr>
                </thead>
                <tbody>
                  {machine.entries.map((e) => (
                    <tr key={e.target_path}>
                      <td>{e.target_path}</td>
                      <td>{e.source_pack}</td>
                      <td>{e.mode}</td>
                      <td>
                        <span className={`entry-status ${e.status}`}>
                          {e.status === "intact" ? "正常" : e.status === "modified" ? "手改過" : "被刪除"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Dry-run 執行對話框 */}
        {dryRunPlan && (
          <div className="modal-overlay">
            <div className="modal-dialog is-dry-run">
              <header className="modal-header">
                <h3>Dry-run 套用計畫確認</h3>
                <button type="button" className="close-btn" onClick={() => setDryRunPlan(null)}>
                  ×
                </button>
              </header>
              <div className="dry-run-content">
                <p className="modal-hint">以下為即將對系統全域目錄執行的變更計畫，請確認無衝突後執行：</p>
                <div className="plan-stats">
                  <span className="stat-add">將新增: {dryRunPlan.add.length} 個</span>
                  <span className="stat-replace">將取代: {dryRunPlan.replace.length} 個</span>
                  <span className="stat-conflict">衝突: {dryRunPlan.conflicts.length} 個</span>
                </div>

                {dryRunPlan.conflicts.length > 0 && (
                  <div className="conflict-box">
                    <strong>⚠️ 衝突項目（預設禁止寫入）：</strong>
                    <ul>
                      {dryRunPlan.conflicts.map((c) => (
                        <li key={c.target_path}>
                          {c.target_path}: {c.reason}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="plan-details-list">
                  {dryRunPlan.add.map((item) => (
                    <div key={item.target_path} className="plan-row is-add">
                      + [{item.kind}] {item.target_path} ({item.mode})
                    </div>
                  ))}
                  {dryRunPlan.replace.map((item) => (
                    <div key={item.target_path} className="plan-row is-replace">
                      ~ [{item.kind}] {item.target_path} ({item.mode})
                    </div>
                  ))}
                </div>

                <div className="dialog-controls">
                  <label className="checkbox-inline">
                    <input
                      type="checkbox"
                      checked={applyReplace}
                      onChange={(e) => setApplyReplace(e.target.checked)}
                    />
                    取代既有非硬連結檔案（自動建立備份）
                  </label>
                  <div className="action-buttons">
                    <button
                      type="button"
                      className="btn-primary"
                      disabled={dryRunPlan.conflicts.length > 0 && !applyReplace}
                      onClick={() => void handleRequestApply(false)}
                    >
                      確認真套用
                    </button>
                    <button type="button" className="btn-secondary" onClick={() => setDryRunPlan(null)}>
                      取消
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { CommandMenu } from "./CommandMenu";
import { actionLabel } from "./labels";
import { InteractiveTerminal } from "./InteractiveTerminal";
import { SubAgentModels } from "./SubAgentModels";
import { MenuModal, type ModalView } from "./MenuModal";
import { UsagePage } from "./UsagePage";
import { DispatchArea } from "./DispatchArea";
import { RoleArea } from "./RoleArea";
import type { AgentRow, ColorScheme, Snapshot, ThemeConfig } from "./types";
import "./App.css";

const ROOT_KEY = "aiwork.repoRoot";
const SCHEME_KEY = "aiwork.colorScheme";
const PRIMARY_AGENT_KEY = "aiwork.primaryAgent";
const SUB_AGENT_1_KEY = "aiwork.subAgent1";
const SUB_AGENT_2_KEY = "aiwork.subAgent2";
const THEME_BG_KEY = "aiwork.theme.background";
const THEME_PORTRAIT_KEY = "aiwork.theme.portrait";
const FALLBACK_URL = "http://127.0.0.1:8765/snapshot";
const ROOT_URL = "http://127.0.0.1:8765/root";

const AGENT_LABELS: Record<string, string> = {
  cursor: "Cursor",
  claude: "Claude",
  codex: "Codex",
  gemini: "Gemini",
};

function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

function taipeiYearMonth(now = new Date()): string {
  const formatted = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
  }).format(now);
  return formatted.slice(0, 7);
}

function formatUsd(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 8,
  });
}

function emptySnap(root: string, error: string | null = null): Snapshot {
  return {
    repo_root: root,
    current_run_id: null,
    selected_run_id: null,
    status: null,
    usage_by_model: {},
    usage_log: [],
    history: [],
    error,
    workflows: [],
    workflow_steps: [],
  };
}

/** `workflows/<id>.yaml` is how both backends look a run's workflow up by id. */
function workflowForRun(
  workflowId: string | undefined,
  workflows: string[],
  fallback: string
): string {
  if (!workflowId) return fallback;
  const hit = workflows.find((path) => {
    const name = path.split("/").pop() ?? "";
    return name === `${workflowId}.yaml` || name === `${workflowId}.yml`;
  });
  return hit ?? fallback;
}

async function fetchHttp(selected: string | null): Promise<Snapshot> {
  const qs = new URLSearchParams();
  if (selected) qs.set("selected_run_id", selected);
  const res = await fetch(`${FALLBACK_URL}?${qs.toString()}`);
  if (!res.ok) {
    throw new Error(`HTTP 快照失敗（${res.status}）— snapshot_server.py 有在跑嗎？`);
  }
  return (await res.json()) as Snapshot;
}

export default function App() {
  const [repoRoot, setRepoRoot] = useState(
    () => localStorage.getItem(ROOT_KEY) ?? ""
  );
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [scheme, setScheme] = useState<ColorScheme>(() =>
    localStorage.getItem(SCHEME_KEY) === "dark" ? "dark" : "light"
  );
  const [busy, setBusy] = useState(false);
  const [rootOpen, setRootOpen] = useState(false);
  const [rootDraft, setRootDraft] = useState("");
  const [, setMode] = useState<"tauri" | "http">("http");

  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [workflow, setWorkflow] = useState("workflows/smoke.yaml");
  const [acting, setActing] = useState(false);

  // 主代理與子代理選擇（儲存於 localStorage）
  const [primaryAgent, setPrimaryAgentState] = useState<string | null>(
    () => localStorage.getItem(PRIMARY_AGENT_KEY)
  );
  const [subAgent1, setSubAgent1State] = useState<string | null>(
    () => localStorage.getItem(SUB_AGENT_1_KEY)
  );
  const [subAgent2, setSubAgent2State] = useState<string | null>(
    () => localStorage.getItem(SUB_AGENT_2_KEY)
  );

  // 頁面切換（home / usage / dispatch / roles）
  const [page, setPage] = useState<"home" | "usage" | "dispatch" | "roles">("home");

  // 選單彈窗（外觀主題設定等，代理區直接在首頁右上，不以彈窗開啟）
  const [modalView, setModalView] = useState<ModalView | null>(null);

  // 主題圖檔設定（存 localStorage，不寫進 repo）
  const [theme, setTheme] = useState<ThemeConfig>(() => ({
    background: localStorage.getItem(THEME_BG_KEY),
    portrait: localStorage.getItem(THEME_PORTRAIT_KEY),
  }));

  const [month, setMonth] = useState(taipeiYearMonth);
  const [agents, setAgents] = useState<AgentRow[]>([]);

  function handleSetPrimaryAgent(val: string) {
    const next = val || null;
    if (next) {
      localStorage.setItem(PRIMARY_AGENT_KEY, next);
    } else {
      localStorage.removeItem(PRIMARY_AGENT_KEY);
    }
    setPrimaryAgentState(next);
  }

  function handleSetSubAgent1(val: string) {
    const next = val || null;
    if (next) {
      localStorage.setItem(SUB_AGENT_1_KEY, next);
    } else {
      localStorage.removeItem(SUB_AGENT_1_KEY);
    }
    setSubAgent1State(next);
  }

  function handleSetSubAgent2(val: string) {
    const next = val || null;
    if (next) {
      localStorage.setItem(SUB_AGENT_2_KEY, next);
    } else {
      localStorage.removeItem(SUB_AGENT_2_KEY);
    }
    setSubAgent2State(next);
  }

  function handleUpdateTheme(key: keyof ThemeConfig, dataUrl: string | null) {
    const storageKeys: Record<keyof ThemeConfig, string> = {
      background: THEME_BG_KEY,
      portrait: THEME_PORTRAIT_KEY,
    };
    try {
      if (dataUrl) {
        localStorage.setItem(storageKeys[key], dataUrl);
      } else {
        localStorage.removeItem(storageKeys[key]);
      }
    } catch {
      // Over the ~5 MB storage quota (two base64 images add up fast): the image still
      // applies for this session, it just won't be remembered next launch.
    }
    setTheme((prev) => ({ ...prev, [key]: dataUrl }));
  }

  const fetchAgents = useCallback(async () => {
    try {
      const res = await fetch("http://127.0.0.1:8765/agents");
      const body = (await res.json()) as {
        agents: { id: string; label: string; state: string }[];
      };
      if (body.agents && body.agents.length > 0) {
        setAgents(body.agents);
        return;
      }
    } catch {
      // fallback
    }
    setAgents([
      { id: "cursor", label: "Cursor", state: "unknown" },
      { id: "claude", label: "Claude", state: "unknown" },
      { id: "codex", label: "Codex", state: "unknown" },
      { id: "gemini", label: "Gemini", state: "unknown" },
    ]);
  }, []);

  useEffect(() => {
    void fetchAgents();
  }, [fetchAgents]);

  useEffect(() => {
    const handleStatusChange = () => {
      void fetchAgents();
    };
    window.addEventListener("agent-status-changed", handleStatusChange);
    return () =>
      window.removeEventListener("agent-status-changed", handleStatusChange);
  }, [fetchAgents]);

  useEffect(() => {
    if (modalView === "agents") {
      void fetchAgents();
    }
  }, [modalView, fetchAgents]);

  const refresh = useCallback(async () => {
    try {
      let next: Snapshot | null = null;
      if (repoRoot) {
        try {
          // No run picker: always follow the server's current run, never pin an old one.
          next = await invoke<Snapshot>("get_snapshot", {
            repoRoot,
            selectedRunId: null,
          });
          setMode("tauri");
        } catch {
          next = null;
        }
      }
      if (!next) {
        next = await fetchHttp(null);
        setMode("http");
        if (!repoRoot && next.repo_root) {
          localStorage.setItem(ROOT_KEY, next.repo_root);
          setRepoRoot(next.repo_root);
        }
      }
      setSnap(next);
      const wfs = next.workflows ?? [];
      if (wfs.length && !wfs.includes(workflow)) setWorkflow(wfs[0]);
    } catch (e) {
      setSnap(emptySnap(repoRoot || "（無）", String(e)));
    }
  }, [repoRoot, workflow]);

  useEffect(() => {
    void refresh();
    const idle = !snap?.current_run_id;
    const ms = idle ? 3000 : 1500;
    const t = window.setInterval(() => void refresh(), ms);
    return () => window.clearInterval(t);
  }, [refresh, snap?.current_run_id]);

  useEffect(() => {
    document.documentElement.dataset.scheme = scheme;
    try {
      localStorage.setItem(SCHEME_KEY, scheme);
    } catch {
      // storage full or blocked: the scheme still applies for this session
    }
  }, [scheme]);

  useEffect(() => {
    if (inTauri() || !repoRoot) return;
    void fetch(ROOT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: repoRoot }),
    }).catch(() => undefined);
  }, [repoRoot]);

  async function applyRoot(path: string) {
    const trimmed = path.trim();
    if (!trimmed) return;
    if (!inTauri()) {
      let body: { ok: boolean; detail: string; root?: string };
      try {
        const res = await fetch(ROOT_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: trimmed }),
        });
        body = (await res.json()) as { ok: boolean; detail: string; root?: string };
      } catch (err) {
        setActionMsg(`無法連線到面板服務：${String(err)}`);
        return;
      }
      if (!body.ok) {
        setActionMsg(body.detail || "無法更換專案");
        return;
      }
      const next = body.root || trimmed;
      localStorage.setItem(ROOT_KEY, next);
      setRepoRoot(next);
    } else {
      localStorage.setItem(ROOT_KEY, trimmed);
      setRepoRoot(trimmed);
      setMode("tauri");
    }
    setRootOpen(false);
    setActionMsg(null);
  }

  async function chooseRoot() {
    if (inTauri()) {
      setBusy(true);
      try {
        const picked = await invoke<string | null>("pick_repo_root");
        if (picked) await applyRoot(picked);
      } catch (err) {
        setActionMsg(String(err));
      } finally {
        setBusy(false);
      }
      return;
    }
    setRootDraft(repoRoot);
    setRootOpen(true);
  }

  async function postAction(path: string, body: Record<string, unknown>) {
    try {
      const res = await fetch(`http://127.0.0.1:8765${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      return (await res.json()) as { ok: boolean; detail: string };
    } catch (err) {
      // Server down, or a non-JSON error body: report it like any other failed action.
      return { ok: false, detail: `無法連線到面板服務：${String(err)}` };
    }
  }

  async function doAgentLogin(agentId: string) {
    setActing(true);
    try {
      const result = await postAction("/agent-login", { id: agentId });
      setActionMsg(actionLabel(result.detail, result.ok));
      await fetchAgents();
    } finally {
      setActing(false);
    }
  }

  async function doAgentLogout(agentId: string) {
    setActing(true);
    try {
      const result = await postAction("/agent-logout", { id: agentId });
      setActionMsg(actionLabel(result.detail, result.ok));
      await fetchAgents();
      window.dispatchEvent(
        new CustomEvent("agent-status-changed", {
          detail: { agent: agentId, state: "logged_out" },
        })
      );
    } finally {
      setActing(false);
    }
  }

  async function doRun(customWf?: string) {
    const targetWf = customWf || workflow;
    setActing(true);
    try {
      let result: { ok: boolean; detail: string };
      try {
        result = await invoke("start_run", {
          args: { repo_root: repoRoot, workflow: targetWf },
        });
      } catch {
        result = await postAction("/run", { workflow: targetWf });
      }
      setActionMsg(actionLabel(result.detail, result.ok));
      void refresh();
    } finally {
      setActing(false);
    }
  }

  async function doContinue(reResolve: boolean = false) {
    const runId = snap?.current_run_id || snap?.status?.run_id;
    if (!runId || snap?.status?.state !== "waiting") {
      setActionMsg("沒有可繼續的執行");
      return;
    }
    // Resume the workflow the waiting run belongs to, not whichever one the UI defaults to.
    const runWorkflow = workflowForRun(
      snap?.status?.workflow_id,
      snap?.workflows ?? [],
      workflow
    );
    setActing(true);
    try {
      let result: { ok: boolean; detail: string };
      try {
        result = await invoke("continue_run", {
          args: { repo_root: repoRoot, workflow: runWorkflow, run_id: runId },
        });
      } catch {
        result = await postAction("/continue", {
          workflow: runWorkflow,
          run_id: runId,
          re_resolve: reResolve,
        });
      }
      setActionMsg(actionLabel(result.detail, result.ok));
      void refresh();
    } finally {
      setActing(false);
    }
  }

  async function doApprove() {
    const runId = snap?.current_run_id || snap?.status?.run_id;
    const stepId = snap?.status?.step_id;
    if (!runId || !stepId) {
      setActionMsg("沒有可核准的執行或步驟");
      return;
    }
    setActing(true);
    try {
      let result: { ok: boolean; detail: string };
      try {
        result = await invoke("approve_step", {
          args: { repo_root: repoRoot, run_id: runId, step_id: stepId },
        });
      } catch {
        result = await postAction("/approve", { run_id: runId, step_id: stepId });
      }
      setActionMsg(actionLabel(result.detail, result.ok));
      void refresh();
    } finally {
      setActing(false);
    }
  }

  async function doCancel() {
    const runId = snap?.current_run_id || snap?.selected_run_id || undefined;
    setActing(true);
    try {
      let result: { ok: boolean; detail: string };
      try {
        result = await invoke("cancel_run", {
          args: { repo_root: repoRoot, run_id: runId ?? null },
        });
      } catch {
        result = await postAction("/cancel", runId ? { run_id: runId } : {});
      }
      setActionMsg(actionLabel(result.detail, result.ok));
      void refresh();
    } finally {
      setActing(false);
    }
  }

  function getAgentLabel(id: string | null): string {
    if (!id) return "未選擇";
    const row = agents.find((a) => a.id === id);
    return row?.label ?? AGENT_LABELS[id] ?? id;
  }

  function getAgentState(id: string | null): string {
    if (!id) return "unknown";
    const row = agents.find((a) => a.id === id);
    return row?.state ?? "unknown";
  }

  const usageLog = (snap?.usage_log ?? []).filter(
    (row) => row.at.startsWith(`${month}-`) || row.at.startsWith(`${month} `)
  );

  return (
    <main className={`app ${page === "home" ? "app-stage" : ""}`}>
      {page === "home" ? null : (
        <header className="top">
          <div className="brand-group">
            <p className="brand">aiwork</p>
            <h1>{page === "usage" ? "用量" : page === "roles" ? "角色" : "派工"}</h1>
          </div>
          <div className="top-actions">
            <button
              type="button"
              className="btn-back-home"
              onClick={() => setPage("home")}
            >
              ← 回到首頁
            </button>
          </div>
        </header>
      )}

      {/* 首頁主工作區：使用 CSS 隱藏以保持三個 CLI 終端連線與進度不中斷 */}
      <div
        className={`workbench-main ${page === "home" ? "" : "is-hidden"}`}
        style={
          theme.background
            ? {
                backgroundImage: `url(${theme.background})`,
                backgroundSize: "cover",
                backgroundPosition: "center",
                backgroundRepeat: "no-repeat",
              }
            : undefined
        }
      >
        {/* 上 1/3：三欄等寬（子代理 1、子代理 2、代理區） */}
        <div className="workbench-top-row">
          <div className="workbench-cell">
            <InteractiveTerminal
              key={`sub1-${subAgent1 ?? "none"}`}
              agent={subAgent1}
              agentLabel={getAgentLabel(subAgent1)}
              agentState={getAgentState(subAgent1)}
              repoRoot={repoRoot}
              title="子代理 1"
              isSubAgent={true}
            />
          </div>
          <div className="workbench-cell">
            <InteractiveTerminal
              key={`sub2-${subAgent2 ?? "none"}`}
              agent={subAgent2}
              agentLabel={getAgentLabel(subAgent2)}
              agentState={getAgentState(subAgent2)}
              repoRoot={repoRoot}
              title="子代理 2"
              isSubAgent={true}
            />
          </div>
          <div className="workbench-cell">
            <SubAgentModels subAgent1={subAgent1} subAgent2={subAgent2} />
          </div>
        </div>

        {/* 下 2/3：左欄約 2/3 寬是主代理 CLI，右欄約 1/3 寬 */}
        <div className="workbench-bottom-row">
          <div className="workbench-main-cli-col">
            <InteractiveTerminal
              key={`main-${primaryAgent ?? "none"}`}
              agent={primaryAgent}
              agentLabel={getAgentLabel(primaryAgent)}
              agentState={getAgentState(primaryAgent)}
              repoRoot={repoRoot}
              title="主代理 CLI"
              isSubAgent={false}
              status={snap?.status ?? null}
              workflow={workflow}
              workflows={snap?.workflows ?? [workflow]}
              acting={acting}
              onWorkflowChange={setWorkflow}
              onRun={doRun}
              onContinue={doContinue}
              dispatchChanged={Boolean(snap?.dispatch_changed)}
              onApprove={doApprove}
              onCancel={doCancel}
            />
          </div>
          <div className="workbench-right-col">
            <div className="workbench-preview-card" aria-label="個性照片">
              {theme.portrait ? (
                <img
                  src={theme.portrait}
                  alt="個性照片"
                  className="workbench-preview-img"
                />
              ) : null}
            </div>
            <div className="workbench-menu-card">
              <CommandMenu
                onOpenAgents={() => setModalView("agents")}
                onOpenUsage={() => {
                  setModalView(null);
                  setPage("usage");
                }}
                onOpenTheme={() => setModalView("theme")}
                onOpenDispatch={() => {
                  setModalView(null);
                  setPage("dispatch");
                }}
                onOpenRoles={() => {
                  setModalView(null);
                  setPage("roles");
                }}
                onChooseRoot={() => void chooseRoot()}
              />
            </div>
          </div>
        </div>
      </div>

      {/* 用量獨立分頁 */}
      {page === "usage" && (
        <UsagePage
          month={month}
          onMonthChange={setMonth}
          usageLog={usageLog}
          formatUsd={formatUsd}
          onBackToHome={() => setPage("home")}
        />
      )}

      {/* 派工獨立分頁（滿版整頁） */}
      {page === "dispatch" && (
        <div className="dispatch-page">
          <DispatchArea />
        </div>
      )}

      {/* 角色與素材獨立分頁（滿版整頁） */}
      {page === "roles" && (
        <div className="dispatch-page">
          <RoleArea onNavigateToDispatch={() => setPage("dispatch")} />
        </div>
      )}

      {/* 中央半透明選單（外觀、主題等） */}
      {modalView !== null && (
        <MenuModal
          activeView={modalView}
          onClose={() => setModalView(null)}
          onSelectView={(view) => setModalView(view)}
          onOpenUsage={() => {
            setModalView(null);
            setPage("usage");
          }}
          onOpenDispatch={() => {
            setModalView(null);
            setPage("dispatch");
          }}
          onOpenRoles={() => {
            setModalView(null);
            setPage("roles");
          }}
          agents={agents}
          primaryAgent={primaryAgent}
          subAgent1={subAgent1}
          subAgent2={subAgent2}
          onSetPrimaryAgent={handleSetPrimaryAgent}
          onSetSubAgent1={handleSetSubAgent1}
          onSetSubAgent2={handleSetSubAgent2}
          onAgentLogin={doAgentLogin}
          onAgentLogout={doAgentLogout}
          acting={acting}
          theme={theme}
          onUpdateTheme={handleUpdateTheme}
          scheme={scheme}
          onSchemeChange={setScheme}
        />
      )}

      {rootOpen && (
        <div className="modal-overlay" role="dialog" aria-label="更換專案">
          <form
            className="modal-dialog root-dialog"
            onSubmit={(event) => {
              event.preventDefault();
              void applyRoot(rootDraft);
            }}
          >
            <h2 className="modal-title">更換專案</h2>
            <p className="modal-hint">輸入這台電腦上的專案目錄。終端會改到這個目錄。</p>
            {actionMsg && <p className="hint">{actionMsg}</p>}
            <input
              className="root-path-input"
              value={rootDraft}
              onChange={(event) => setRootDraft(event.target.value)}
              aria-label="專案目錄"
              autoFocus
            />
            <div className="root-dialog-actions">
              <button type="button" onClick={() => setRootOpen(false)}>
                取消
              </button>
              <button type="submit" disabled={busy || !rootDraft.trim()}>
                使用這個目錄
              </button>
            </div>
          </form>
        </div>
      )}
    </main>
  );
}

export type ModelUsage = {
  input_uncached: number;
  cache_read: number;
  cache_write: number;
  output: number;
  dirty: number;
  events: number;
  mismatch_events: number;
};

export type RunStatusDto = {
  run_id: string;
  workflow_id: string;
  state: string;
  step_id: string | null;
  pid: number | null;
  started_at: string;
  updated_at: string;
  last_error: string | null;
  dirty: boolean;
  lives_total?: number | null;
  lives_left?: number | null;
};

export type UsageLogItem = {
  at: string;
  run_id: string;
  step_id: string;
  agent: string;
  role?: string;
  model: string;
  input_uncached: number;
  cache_read: number;
  cache_write: number;
  output: number;
  usd?: number | null;
};

export type HistoryItem = {
  run_id: string;
  state: string;
  workflow_id: string;
  updated_at: string;
};

export type Snapshot = {
  repo_root: string;
  current_run_id: string | null;
  selected_run_id: string | null;
  status: RunStatusDto | null;
  usage_by_model: Record<string, ModelUsage>;
  usage_log?: UsageLogItem[];
  history: HistoryItem[];
  error: string | null;
  workflows?: string[];
  workflow_steps?: string[];
  dispatch_changed?: boolean;
};

export type ColorScheme = "light" | "dark";

export type ThemeConfig = {
  background: string | null;
  portrait: string | null;
};

/** Map run state + step to a 0..N cell on the progress board. */
export function progressCell(
  state: string | undefined,
  stepId: string | null | undefined,
  stepsOrCount: string[] | number = 5
): { index: number; pose: "idle" | "run" | "pause" | "win" | "fail" } {
  const steps: string[] = Array.isArray(stepsOrCount) ? stepsOrCount : [];
  const cellCount = Array.isArray(stepsOrCount)
    ? Math.max(stepsOrCount.length, 1)
    : Math.max(stepsOrCount, 1);
  const last = cellCount - 1;

  let stepIndex = -1;
  if (stepId && steps.length > 0) {
    stepIndex = steps.indexOf(stepId);
  }
  if (stepIndex === -1 && stepId) {
    const match = stepId.match(/(\d+)/);
    if (match) {
      stepIndex = Math.max(0, Math.min(Number(match[1]) - 1, last));
    }
  }
  if (stepIndex === -1) {
    stepIndex = 0;
  }

  switch (state) {
    case "queued":
      return { index: 0, pose: "idle" };
    case "awaiting_approval":
    case "waiting":
      return { index: Math.min(stepIndex, last), pose: "pause" };
    case "succeeded":
      return { index: last, pose: "win" };
    case "failed":
    case "cancelled":
      return { index: Math.min(stepIndex, last), pose: "fail" };
    case "running":
      return { index: Math.min(stepIndex, last), pose: "run" };
    default:
      return { index: 0, pose: "idle" };
  }
}

export type AgentRow = {
  id: string;
  label: string;
  state: string;
  account_label?: string;
};

export type RoleRowDto = {
  agent: string;
  model: string;
  effort?: "low" | "medium" | "high";
  description: string;
  source: "shared" | "local";
  cli?: string;
  cli_in_path?: boolean;
};

export type RolesResponseDto = {
  ok: boolean;
  roles: Record<string, RoleRowDto>;
  tables: Record<string, { path: string; sha256: string }>;
  etags: Record<string, string>;
  warnings?: string[];
  errors?: string[];
};

export type ModelsResponseDto = {
  ok: boolean;
  models: Record<string, string[]>;
  etag: string;
  path: string;
};

export type ModelsCheckAgentResult = {
  status: "ok" | "notice" | "error";
  extra_in_cli?: string[];
  missing_in_cli?: string[];
  total_cli?: number;
  total_catalog?: number;
  message?: string;
};

export type ModelsCheckResponseDto = {
  ok: boolean;
  result: Record<string, ModelsCheckAgentResult>;
};


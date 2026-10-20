import { stateLabel } from "./labels";
import type { RunStatusDto, ThemeConfig } from "./types";
import { progressCell } from "./types";

type Props = {
  status: RunStatusDto | null;
  hasCurrent: boolean;
  workflowSteps?: string[];
  theme?: ThemeConfig;
  agentLabel: string;
};

export function ProgressBoard({
  status,
  hasCurrent,
  workflowSteps = [],
  agentLabel,
}: Props) {
  const steps =
    workflowSteps.length > 0
      ? workflowSteps
      : status?.step_id
        ? [status.step_id]
        : [];
  const { index } = progressCell(
    status?.state,
    status?.step_id,
    steps.length > 0 ? steps : ["—"],
  );
  const livesTotal = status?.lives_total ?? null;
  const livesLeft = status?.lives_left ?? livesTotal;
  const isFailed = status?.state === "failed" || status?.state === "cancelled";
  const isRunningWithDamage =
    status?.state === "running" &&
    livesTotal !== null &&
    livesLeft !== null &&
    livesLeft < livesTotal;
  const isBossVisible = Boolean(isFailed || isRunningWithDamage);

  const stepText =
    !status && !hasCurrent
      ? "尚未派工"
      : steps.length > 0
        ? `${index + 1} / ${steps.length} · ${steps[index] ?? status?.step_id ?? "—"}`
        : status
          ? stateLabel(status.state)
          : "尚未派工";

  return (
    <section className="board" aria-label="角色與橫向關卡">
      <img className="stage-skin" src="/stage-skin.png" alt="" />
      <p className="sr-only">
        {agentLabel}，{stepText}
        {isBossVisible ? "，魔王在場" : ""}
      </p>
    </section>
  );
}

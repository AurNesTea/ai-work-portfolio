import subprocess
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from aiwork.adapters.base import AdapterResult
from aiwork.dispatch import ResolvedWorkflow, load_resolved, save_resolved
from aiwork.effort import recorded_effort
from aiwork.ledger import append_usage
from aiwork.pause import needle_problem, step_pause_problem
from aiwork.models import AgentName, RunStatus, StepSpec, UsageEvent, WorkflowSpec
from aiwork.packs import (
    build_role_prompt,
    find_role_definition,
    get_role_delivery_status,
    inject_role_header,
)
from aiwork.status_store import get_current, read_status, set_current, write_status
from aiwork.usage_db import record_run_event


class RunnerError(Exception):
    pass


def normalize_model(value: str) -> str:
    return value.strip().lower().replace("_", "-").replace(" ", "-")


def models_mismatch(requested: str, actual: str) -> bool:
    """Exact match after normalize (display names: spaces→dashes).

    Version suffixes count as mismatch: composer-2 vs composer-2.5 → True.
    """
    a = normalize_model(requested)
    b = normalize_model(actual)
    if not a or not b:
        return True
    return a != b


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_event(
    run_dir: Path,
    *,
    run_id: str,
    step: StepSpec,
    result: AdapterResult,
) -> None:
    event = UsageEvent(
        run_id=run_id,
        step_id=step.id,
        agent=step.agent,
        dispatch_role=step.role,
        model_requested=step.model,
        model_actual=result.model_actual,
        input_uncached=result.input_uncached,
        cache_read=result.cache_read,
        cache_write=result.cache_write,
        output=result.output,
        cost_usd=result.cost_usd,
        session_id=result.session_id,
        dirty=result.dirty,
        mismatch=models_mismatch(step.model, result.model_actual),
        recorded_at=_now(),
        effort=recorded_effort(step.agent, step.effort, model=step.model),
    )
    append_usage(run_dir, event)
    record_run_event(run_dir, event)


def _step_succeeded(run_dir: Path, step_id: str) -> bool:
    marker = run_dir / "steps" / step_id / "ok"
    if marker.is_file():
        return True
    # Fallback: last usage row for step with no later failure marker
    fail = run_dir / "steps" / step_id / "failed"
    if fail.is_file():
        return False
    return False


def run_single_step(
    *,
    runs_root: Path,
    workflow_id: str,
    step: StepSpec,
    workdir: Path,
    run_fn: Callable[..., AdapterResult],
    run_id: str | None = None,
) -> Path:
    runs_root = Path(runs_root)
    current = get_current(runs_root)
    if current:
        cur = runs_root / current
        if cur.exists() and read_status(cur).state in (
            "running",
            "awaiting_approval",
            "waiting",
        ):
            raise RunnerError(
                f"run already active: {current}; cancel it or finish before run-step"
            )

    prompt_path = Path(step.prompt_file)
    if not prompt_path.is_file():
        raise RunnerError(f"prompt not found: {step.prompt_file}")

    run_id = run_id or uuid4().hex[:12]
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    started = _now()
    write_status(
        run_dir,
        RunStatus(
            run_id=run_id,
            workflow_id=workflow_id,
            state="running",
            step_id=step.id,
            started_at=started,
            updated_at=started,
        ),
    )
    set_current(runs_root, run_id)
    prompt = prompt_path.read_text(encoding="utf-8")
    role_file = getattr(step, "role_file", None)
    delivery = getattr(step, "delivery", None)
    if not role_file and step.role:
        rf = find_role_definition(step.role)
        if rf is not None and rf.is_file():
            posix_path, deliv = get_role_delivery_status(rf)
            role_file = posix_path
            delivery = deliv
            if delivery == "none":
                warnings.warn(
                    f"Role definition path '{role_file}' contains invalid characters or whitespace; falling back to delivery: none",
                    UserWarning,
                    stacklevel=2,
                )
    prompt = inject_role_header(prompt, role_file=role_file, delivery=delivery)
    step_out = run_dir / "steps" / step.id
    step_out.mkdir(parents=True, exist_ok=True)
    try:
        result = run_fn(
            model=step.model,
            prompt=prompt,
            cwd=str(workdir),
            timeout_sec=step.timeout_sec,
            step=step,
        )
    except Exception as exc:  # noqa: BLE001
        write_status(
            run_dir,
            RunStatus(
                run_id=run_id,
                workflow_id=workflow_id,
                state="failed",
                step_id=step.id,
                started_at=started,
                updated_at=_now(),
                last_error=str(exc),
            ),
        )
        set_current(runs_root, None)
        raise
    (step_out / "stream.txt").write_text(result.stdout or "", encoding="utf-8")
    _write_event(run_dir, run_id=run_id, step=step, result=result)
    state = "succeeded" if result.exit_code == 0 else "failed"
    if state == "succeeded":
        (step_out / "ok").write_text("1", encoding="utf-8")
    else:
        (step_out / "failed").write_text(str(result.exit_code), encoding="utf-8")
    write_status(
        run_dir,
        RunStatus(
            run_id=run_id,
            workflow_id=workflow_id,
            state=state,
            step_id=step.id,
            started_at=started,
            updated_at=_now(),
            last_error=None
            if state == "succeeded"
            else (result.stderr or f"exit {result.exit_code}"),
            dirty=result.dirty,
        ),
    )
    set_current(runs_root, None)
    return run_dir


def _write_waiting(
    run_dir: Path,
    *,
    run_id: str,
    workflow_id: str,
    step_id: str,
    started: str,
    problem: str,
    dirty: bool,
    lives_total: int | None = None,
    lives_left: int | None = None,
) -> None:
    write_status(
        run_dir,
        RunStatus(
            run_id=run_id,
            workflow_id=workflow_id,
            state="waiting",
            step_id=step_id,
            started_at=started,
            updated_at=_now(),
            last_error=problem,
            dirty=dirty,
            lives_total=lives_total,
            lives_left=lives_left,
        ),
    )


def _missing_test_steps(workflow: WorkflowSpec) -> list[str]:
    return [step.id for step in workflow.steps if not step.test_command.strip()]


def _run_test_command(command: str, cwd: str, timeout_sec: int) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        detail = f"{stdout}\n{stderr}".strip() or "測試逾時"
        return 1, detail
    detail = f"{proc.stdout or ''}\n{proc.stderr or ''}".strip()
    if proc.returncode != 0 and not detail:
        detail = f"exit {proc.returncode}"
    return proc.returncode, detail


def _prompt_with_error(prompt: str, error: str | None) -> str:
    if not error:
        return prompt
    return f"{prompt}\n\n上一輪錯誤：\n{error}"


def _resolve_prompt(root: Path, step: StepSpec) -> str:
    # The workflow was validated against root, so root wins. The CWD is only a fallback
    # for a path given relative to where the command was run; letting it win would send
    # an unrelated project's prompts/<same name>.md to the agent.
    path = root / step.prompt_file
    if not path.is_file():
        path = Path(step.prompt_file)
    return path.read_text(encoding="utf-8")


def run_workflow(
    *,
    workflow: WorkflowSpec,
    runs_root: Path,
    workdir: Path,
    root: Path,
    adapters: dict[AgentName, Callable[..., AdapterResult]],
    resume_run_id: str | None = None,
    force: bool = False,
    resolved: ResolvedWorkflow | None = None,
) -> Path:
    missing = _missing_test_steps(workflow)
    if missing:
        raise RunnerError("缺少測試指令：" + ", ".join(missing))
    runs_root = Path(runs_root)
    runs_root.mkdir(parents=True, exist_ok=True)
    current = get_current(runs_root)
    if current and not resume_run_id and not force:
        cur_dir = runs_root / current
        if cur_dir.exists():
            st = read_status(cur_dir)
            if st.state in ("running", "awaiting_approval", "waiting"):
                raise RunnerError(
                    f"run already active: {current} ({st.state}); "
                    "approve/cancel or pass force=True"
                )

    resumed_dirty = False
    if resume_run_id:
        run_id = resume_run_id
        run_dir = runs_root / run_id
        status = read_status(run_dir)
        resumed_dirty = status.dirty
        if status.workflow_id != workflow.id:
            raise RunnerError(
                f"run {run_id} belongs to workflow {status.workflow_id}, "
                f"not {workflow.id}"
            )
        started = status.started_at
        start_index = 0
        for i, step in enumerate(workflow.steps):
            if not _step_succeeded(run_dir, step.id):
                start_index = i
                break
        else:
            write_status(
                run_dir,
                RunStatus(
                    run_id=run_id,
                    workflow_id=workflow.id,
                    state="succeeded",
                    step_id=workflow.steps[-1].id if workflow.steps else None,
                    started_at=started,
                    updated_at=_now(),
                    dirty=status.dirty,
                ),
            )
            set_current(runs_root, None)
            return run_dir
    else:
        run_id = uuid4().hex[:12]
        run_dir = runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        started = _now()
        start_index = 0
        write_status(
            run_dir,
            RunStatus(
                run_id=run_id,
                workflow_id=workflow.id,
                state="running",
                step_id=workflow.steps[0].id if workflow.steps else None,
                started_at=started,
                updated_at=started,
            ),
        )

    # Resolution handling
    if resolved is None and (run_dir / "resolved.json").is_file():
        try:
            resolved = load_resolved(run_dir)
        except Exception as exc:
            raise RunnerError(f"failed to load resolved.json: {exc}") from exc
    elif resolved is not None and not (run_dir / "resolved.json").is_file():
        save_resolved(run_dir, resolved)

    # If any step has role, resolved must be present and contain it
    for s in workflow.steps:
        if s.role:
            if resolved is None or s.id not in resolved.steps:
                raise RunnerError(
                    f"step {s.id} has role '{s.role}' but resolved.json is missing or lacks this step"
                )

    if resolved is not None:
        updated_steps = []
        for s in workflow.steps:
            if s.id in resolved.steps:
                r_step = resolved.steps[s.id]
                s = s.model_copy(
                    update={
                        "agent": r_step.agent,
                        "model": r_step.model,
                        "effort": r_step.effort,
                        "role": r_step.role,
                        "role_file": r_step.role_file,
                        "delivery": r_step.delivery,
                    }
                )
            updated_steps.append(s)
        workflow = workflow.model_copy(update={"steps": updated_steps})

    set_current(runs_root, run_id)
    # A resumed run keeps the dirty flag its earlier steps already set.
    dirty_any = resumed_dirty


    for step in workflow.steps[start_index:]:
        if step.approval:
            approved = run_dir / "approvals" / f"{step.id}.approved"
            if not approved.is_file():
                pending = run_dir / "approvals" / f"{step.id}.pending"
                pending.parent.mkdir(parents=True, exist_ok=True)
                pending.write_text("awaiting", encoding="utf-8")
                write_status(
                    run_dir,
                    RunStatus(
                        run_id=run_id,
                        workflow_id=workflow.id,
                        state="awaiting_approval",
                        step_id=step.id,
                        started_at=started,
                        updated_at=_now(),
                    ),
                )
                return run_dir

        run_fn = adapters.get(step.agent)
        if run_fn is None:
            write_status(
                run_dir,
                RunStatus(
                    run_id=run_id,
                    workflow_id=workflow.id,
                    state="failed",
                    step_id=step.id,
                    started_at=started,
                    updated_at=_now(),
                    last_error=f"no adapter for agent: {step.agent}",
                ),
            )
            set_current(runs_root, None)
            raise RunnerError(f"no adapter for agent: {step.agent}")

        lives_total = step.max_retries + 1
        lives_left = lives_total
        write_status(
            run_dir,
            RunStatus(
                run_id=run_id,
                workflow_id=workflow.id,
                state="running",
                step_id=step.id,
                started_at=started,
                updated_at=_now(),
                dirty=dirty_any,
                lives_total=lives_total,
                lives_left=lives_left,
            ),
        )
        try:
            prompt = _resolve_prompt(root, step)
            role_file = getattr(step, "role_file", None)
            delivery = getattr(step, "delivery", None)
            if resolved is not None and step.id in resolved.steps:
                role_file = resolved.steps[step.id].role_file
                delivery = resolved.steps[step.id].delivery
            elif step.role and not role_file:
                rf = find_role_definition(step.role)
                if rf is not None and rf.is_file():
                    posix_path, deliv = get_role_delivery_status(rf)
                    role_file = posix_path
                    delivery = deliv
                    if delivery == "none":
                        warnings.warn(
                            f"Role definition path '{role_file}' contains invalid characters or whitespace; falling back to delivery: none",
                            UserWarning,
                            stacklevel=2,
                        )
            prompt = inject_role_header(prompt, role_file=role_file, delivery=delivery)
        except OSError as exc:
            # Same ending as a missing adapter: the run must not stay "running" with
            # current.json set, or every later run is refused as "already active".
            last_error = f"cannot read prompt for step {step.id}: {exc}"
            write_status(
                run_dir,
                RunStatus(
                    run_id=run_id,
                    workflow_id=workflow.id,
                    state="failed",
                    step_id=step.id,
                    started_at=started,
                    updated_at=_now(),
                    last_error=last_error,
                    dirty=dirty_any,
                ),
            )
            set_current(runs_root, None)
            raise RunnerError(last_error) from exc
        step_out = run_dir / "steps" / step.id
        step_out.mkdir(parents=True, exist_ok=True)
        last_error: str | None = None
        succeeded = False
        while lives_left > 0:
            try:
                result = run_fn(
                    model=step.model,
                    prompt=_prompt_with_error(prompt, last_error),
                    cwd=str(workdir),
                    timeout_sec=step.timeout_sec,
                    step=step,
                    run_dir=run_dir,
                )
            except Exception as exc:  # noqa: BLE001
                # str(TimeoutExpired) embeds the whole argv, which can hold the prompt.
                problem = (
                    None
                    if isinstance(exc, subprocess.TimeoutExpired)
                    else needle_problem(str(exc))
                )
                if problem:
                    _write_waiting(
                        run_dir,
                        run_id=run_id,
                        workflow_id=workflow.id,
                        step_id=step.id,
                        started=started,
                        problem=problem,
                        dirty=dirty_any,
                        lives_total=lives_total,
                        lives_left=lives_left,
                    )
                    return run_dir
                last_error = str(exc)
                lives_left -= 1
                (step_out / "failed").write_text(last_error, encoding="utf-8")
                write_status(
                    run_dir,
                    RunStatus(
                        run_id=run_id,
                        workflow_id=workflow.id,
                        state="running",
                        step_id=step.id,
                        started_at=started,
                        updated_at=_now(),
                        last_error=last_error,
                        dirty=dirty_any,
                        lives_total=lives_total,
                        lives_left=lives_left,
                    ),
                )
                continue

            (step_out / "stream.txt").write_text(result.stdout or "", encoding="utf-8")
            _write_event(run_dir, run_id=run_id, step=step, result=result)
            dirty_any = dirty_any or result.dirty
            problem = step_pause_problem(result)
            if problem:
                _write_waiting(
                    run_dir,
                    run_id=run_id,
                    workflow_id=workflow.id,
                    step_id=step.id,
                    started=started,
                    problem=problem,
                    dirty=dirty_any,
                    lives_total=lives_total,
                    lives_left=lives_left,
                )
                return run_dir
            if result.exit_code != 0:
                last_error = result.stderr or f"exit {result.exit_code}"
                lives_left -= 1
                (step_out / "failed").write_text(str(result.exit_code), encoding="utf-8")
                write_status(
                    run_dir,
                    RunStatus(
                        run_id=run_id,
                        workflow_id=workflow.id,
                        state="running",
                        step_id=step.id,
                        started_at=started,
                        updated_at=_now(),
                        last_error=last_error,
                        dirty=dirty_any,
                        lives_total=lives_total,
                        lives_left=lives_left,
                    ),
                )
                continue
            test_code, test_detail = _run_test_command(
                step.test_command, str(workdir), step.timeout_sec
            )
            if test_code == 0:
                succeeded = True
                break
            last_error = test_detail or f"exit {test_code}"
            lives_left -= 1
            (step_out / "failed").write_text(last_error, encoding="utf-8")
            write_status(
                run_dir,
                RunStatus(
                    run_id=run_id,
                    workflow_id=workflow.id,
                    state="running",
                    step_id=step.id,
                    started_at=started,
                    updated_at=_now(),
                    last_error=last_error,
                    dirty=dirty_any,
                    lives_total=lives_total,
                    lives_left=lives_left,
                ),
            )

        if not succeeded:
            write_status(
                run_dir,
                RunStatus(
                    run_id=run_id,
                    workflow_id=workflow.id,
                    state="failed",
                    step_id=step.id,
                    started_at=started,
                    updated_at=_now(),
                    last_error=last_error,
                    dirty=dirty_any,
                    lives_total=lives_total,
                    lives_left=lives_left,
                ),
            )
            set_current(runs_root, None)
            return run_dir
        (step_out / "ok").write_text("1", encoding="utf-8")
        failed_marker = step_out / "failed"
        if failed_marker.exists():
            failed_marker.unlink()

    write_status(
        run_dir,
        RunStatus(
            run_id=run_id,
            workflow_id=workflow.id,
            state="succeeded",
            step_id=workflow.steps[-1].id if workflow.steps else None,
            started_at=started,
            updated_at=_now(),
            dirty=dirty_any,
            lives_total=lives_total,
            lives_left=lives_left,
        ),
    )
    set_current(runs_root, None)
    return run_dir

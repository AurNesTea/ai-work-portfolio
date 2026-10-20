# AI Work Runner (P0–P4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local CLI orchestrator that runs agent CLIs (Cursor first) from workflow YAML, writes per-step `usage_events` and `status.json`, then extends to multi-agent adapters, MCP profiles/gateway hook, and non-manual triggers—without calling model HTTP APIs or shipping a UI panel (P5 later).

**Architecture:** Python package `aiwork` with pure schema/ledger modules, per-agent adapters that spawn headless CLIs and normalize usage, a sequential runner that owns `runs/<run-id>/`, and a Typer CLI (`aiwork`). MCP/skills are profile names resolved to files; P3 points profiles at a local gateway URL. Auth stays each vendor’s login.

**Tech Stack:** Python 3.11+, Typer, PyYAML, pydantic v2, pytest; Windows-first (PowerShell). No Electron/UI in this plan.

**Spec:** `docs/superpowers/specs/2026-09-21-ai-agent-workflow-design.md`

## Global Constraints

- No AI API keys in repo; Orchestrator must not call model HTTP.
- One YAML step → one CLI process → one primary `usage_event` row (role=`parent`).
- Cursor: do not rely on subagent token split; mark `dirty=true` if mixed-model Task detected when detectable; prefer `model: inherit` for any custom subagents.
- P0–P4 deliver files + CLI only; no ops panel (P5).
- Sequential workflows only; no conditionals / fan-out.
- Platform: Windows PowerShell must be able to run tests and CLI.

## Review Focus

- Missing `brief_path` or prompt file → runner fails before spawn with clear error (not empty CLI prompt). Covered in Task 5.
- Cursor `inputTokens` treated as uncached only; total input = uncached + cache_read + cache_write. Covered in Task 2.
- `approval: true` step must not spawn CLI until approve file/command. Covered in Task 6.
- Second `aiwork run` while `runs/current.json` points at `running` → reject or require `--force` (default reject). Covered in Task 6.
- Unknown `mcp_profile` / `skills` pack → fail before spawn. Covered in Task 8.

## File map

| Path | Responsibility |
|---|---|
| `pyproject.toml` | package metadata, deps, `aiwork` script entry |
| `src/aiwork/models.py` | pydantic: UsageEvent, RunStatus, Workflow, Step |
| `src/aiwork/ledger.py` | append/read `usage_events.jsonl` |
| `src/aiwork/status_store.py` | read/write `status.json`, `current.json` |
| `src/aiwork/adapters/base.py` | Adapter protocol + RunResult |
| `src/aiwork/adapters/cursor.py` | spawn `agent`, parse stream-json, map usage |
| `src/aiwork/adapters/claude.py` | P2 |
| `src/aiwork/adapters/codex.py` | P2 |
| `src/aiwork/adapters/gemini.py` | P2 |
| `src/aiwork/workflow.py` | load/validate YAML |
| `src/aiwork/profiles.py` | resolve `mcp_profile` + `skills` |
| `src/aiwork/runner.py` | sequential orchestration |
| `src/aiwork/cli.py` | Typer: run, status, usage, approve, cancel |
| `src/aiwork/triggers/` | P4 cron helper + slack stub docs/hook |
| `mcp-profiles/*.yaml` | allowlists |
| `skills/` | skill packs (placeholders) |
| `tests/fixtures/` | sample Cursor/Claude JSON streams |
| `tests/` | unit/integration tests |

---

### Task 1: Package scaffold + models

**Files:**
- Create: `pyproject.toml`
- Create: `src/aiwork/__init__.py`
- Create: `src/aiwork/models.py`
- Create: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing
- Produces: `UsageEvent`, `RunStatus`, `WorkflowSpec`, `StepSpec` pydantic models

- [ ] **Step 1: Write failing test for UsageEvent required fields**

```python
# tests/test_models.py
from aiwork.models import UsageEvent

def test_usage_event_requires_ids_and_tokens():
    ev = UsageEvent(
        run_id="r1",
        step_id="s1",
        agent="cursor",
        role="parent",
        model_requested="composer-2",
        model_actual="composer-2",
        input_uncached=7,
        cache_read=100,
        cache_write=20,
        output=50,
        cost_usd=None,
        session_id="sess",
        dirty=False,
        mismatch=False,
    )
    assert ev.total_input() == 127
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py::test_usage_event_requires_ids_and_tokens -v`  
Expected: FAIL (module not found or `total_input` missing)

- [ ] **Step 3: Add pyproject + models**

```toml
# pyproject.toml
[project]
name = "aiwork"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["pydantic>=2", "pyyaml", "typer"]

[project.optional-dependencies]
dev = ["pytest"]

[project.scripts]
aiwork = "aiwork.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/aiwork"]

[tool.pytest.ini_options]
pythonpath = ["src"]
```

```python
# src/aiwork/models.py
from typing import Literal
from pydantic import BaseModel, Field

AgentName = Literal["cursor", "claude", "codex", "gemini"]
RunState = Literal[
    "queued", "running", "awaiting_approval", "succeeded", "failed", "cancelled"
]

class UsageEvent(BaseModel):
    run_id: str
    step_id: str
    agent: AgentName
    role: Literal["parent"] = "parent"
    model_requested: str
    model_actual: str
    input_uncached: int = 0
    cache_read: int = 0
    cache_write: int = 0
    output: int = 0
    cost_usd: float | None = None
    session_id: str | None = None
    dirty: bool = False
    mismatch: bool = False

    def total_input(self) -> int:
        return self.input_uncached + self.cache_read + self.cache_write

class RunStatus(BaseModel):
    run_id: str
    workflow_id: str
    state: RunState
    step_id: str | None = None
    pid: int | None = None
    started_at: str
    updated_at: str
    last_error: str | None = None
    dirty: bool = False

class StepSpec(BaseModel):
    id: str
    agent: AgentName
    model: str
    prompt_file: str
    mcp_profile: str = "default"
    skills: list[str] = Field(default_factory=list)
    timeout_sec: int = 600
    on_fail: Literal["stop"] = "stop"
    approval: bool = False

class WorkflowSpec(BaseModel):
    id: str
    brief_path: str
    trigger: Literal["manual", "cron", "slack"] = "manual"
    steps: list[StepSpec]
```

- [ ] **Step 4: Install editable + pass test**

Run:
```powershell
cd C:/path/to/ai-work
python -m pip install -e ".[dev]"
pytest tests/test_models.py -v
```
Expected: PASS

- [ ] **Step 5: Commit** (only if user asked to commit in this session; otherwise skip)

```powershell
git add pyproject.toml src/aiwork tests/test_models.py
git commit -m "feat: add aiwork models and package scaffold"
```

---

### Task 2: Ledger + status store

**Files:**
- Create: `src/aiwork/ledger.py`
- Create: `src/aiwork/status_store.py`
- Create: `tests/test_ledger.py`
- Create: `tests/test_status_store.py`

**Interfaces:**
- Consumes: `UsageEvent`, `RunStatus`
- Produces: `append_usage(run_dir, event)`, `read_usage(run_dir)`, `write_status(run_dir, status)`, `read_status(run_dir)`, `set_current(runs_root, run_id|None)`, `get_current(runs_root)`

- [ ] **Step 1: Failing ledger test**

```python
# tests/test_ledger.py
from pathlib import Path
from aiwork.models import UsageEvent
from aiwork.ledger import append_usage, read_usage

def test_append_and_read_usage(tmp_path: Path):
    run_dir = tmp_path / "r1"
    run_dir.mkdir()
    ev = UsageEvent(
        run_id="r1", step_id="s1", agent="cursor",
        model_requested="m", model_actual="m",
        input_uncached=1, cache_read=2, cache_write=3, output=4,
    )
    append_usage(run_dir, ev)
    rows = read_usage(run_dir)
    assert len(rows) == 1
    assert rows[0].total_input() == 6
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/test_ledger.py -v`

- [ ] **Step 3: Implement ledger + status_store**

```python
# src/aiwork/ledger.py
import json
from pathlib import Path
from aiwork.models import UsageEvent

def append_usage(run_dir: Path, event: UsageEvent) -> Path:
    path = run_dir / "usage_events.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(event.model_dump_json() + "\n")
    return path

def read_usage(run_dir: Path) -> list[UsageEvent]:
    path = run_dir / "usage_events.jsonl"
    if not path.exists():
        return []
    return [
        UsageEvent.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
```

```python
# src/aiwork/status_store.py
import json
from pathlib import Path
from aiwork.models import RunStatus

def write_status(run_dir: Path, status: RunStatus) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "status.json"
    path.write_text(status.model_dump_json(indent=2), encoding="utf-8")
    return path

def read_status(run_dir: Path) -> RunStatus:
    return RunStatus.model_validate_json(
        (run_dir / "status.json").read_text(encoding="utf-8")
    )

def set_current(runs_root: Path, run_id: str | None) -> Path:
    runs_root.mkdir(parents=True, exist_ok=True)
    path = runs_root / "current.json"
    if run_id is None:
        if path.exists():
            path.unlink()
        return path
    path.write_text(json.dumps({"run_id": run_id}, indent=2), encoding="utf-8")
    return path

def get_current(runs_root: Path) -> str | None:
    path = runs_root / "current.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["run_id"]
```

- [ ] **Step 4: Add status test + pass both**

```python
# tests/test_status_store.py
from datetime import datetime, timezone
from pathlib import Path
from aiwork.models import RunStatus
from aiwork.status_store import write_status, read_status, set_current, get_current

def test_status_roundtrip(tmp_path: Path):
    now = datetime.now(timezone.utc).isoformat()
    st = RunStatus(
        run_id="r1", workflow_id="w", state="running",
        step_id="s1", pid=1, started_at=now, updated_at=now,
    )
    write_status(tmp_path / "r1", st)
    assert read_status(tmp_path / "r1").state == "running"
    set_current(tmp_path, "r1")
    assert get_current(tmp_path) == "r1"
    set_current(tmp_path, None)
    assert get_current(tmp_path) is None
```

Run: `pytest tests/test_ledger.py tests/test_status_store.py -v`  
Expected: PASS

- [ ] **Step 5: Commit** (if authorized)

---

### Task 3: Cursor usage parser (fixtures, no live CLI)

**Files:**
- Create: `src/aiwork/adapters/base.py`
- Create: `src/aiwork/adapters/cursor.py` (parser helpers first)
- Create: `tests/fixtures/cursor_result_success.jsonl`
- Create: `tests/test_cursor_parse.py`

**Interfaces:**
- Consumes: NDJSON lines from Cursor `--output-format stream-json`
- Produces: `parse_cursor_stream(text) -> CursorParseResult` with usage fields + session_id + model_actual + dirty hint

- [ ] **Step 1: Add fixture + failing test**

```jsonl
{"type":"system","subtype":"init","session_id":"sess-1","model":"Composer 2"}
{"type":"result","subtype":"success","session_id":"sess-1","usage":{"inputTokens":7,"outputTokens":50,"cacheReadTokens":100,"cacheWriteTokens":20},"result":"ok"}
```

```python
# tests/test_cursor_parse.py
from pathlib import Path
from aiwork.adapters.cursor import parse_cursor_stream

def test_parse_cursor_usage_and_model():
    text = Path("tests/fixtures/cursor_result_success.jsonl").read_text(encoding="utf-8")
    parsed = parse_cursor_stream(text)
    assert parsed.session_id == "sess-1"
    assert parsed.model_actual == "Composer 2"
    assert parsed.input_uncached == 7
    assert parsed.cache_read == 100
    assert parsed.cache_write == 20
    assert parsed.output == 50
    assert parsed.dirty is False
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement parse_cursor_stream**

```python
# src/aiwork/adapters/base.py
from dataclasses import dataclass

@dataclass
class AdapterResult:
    exit_code: int
    session_id: str | None
    model_actual: str
    input_uncached: int
    cache_read: int
    cache_write: int
    output: int
    cost_usd: float | None
    dirty: bool
    stdout: str
    stderr: str
```

```python
# src/aiwork/adapters/cursor.py
import json
from dataclasses import dataclass
from aiwork.adapters.base import AdapterResult

@dataclass
class CursorParseResult:
    session_id: str | None
    model_actual: str
    input_uncached: int
    cache_read: int
    cache_write: int
    output: int
    dirty: bool

def parse_cursor_stream(text: str) -> CursorParseResult:
    model_actual = "unknown"
    session_id = None
    usage = {}
    dirty = False
    for line in text.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("type") == "system" and obj.get("subtype") == "init":
            model_actual = obj.get("model") or model_actual
            session_id = obj.get("session_id") or session_id
        if obj.get("type") == "result":
            session_id = obj.get("session_id") or session_id
            usage = obj.get("usage") or {}
            # Heuristic placeholder: Task tool names in stream → dirty if needed later
        if obj.get("type") == "tool_call":
            tc = obj.get("tool_call") or {}
            if "taskToolCall" in tc or "Task" in json.dumps(tc):
                dirty = True
    return CursorParseResult(
        session_id=session_id,
        model_actual=model_actual,
        input_uncached=int(usage.get("inputTokens") or 0),
        cache_read=int(usage.get("cacheReadTokens") or 0),
        cache_write=int(usage.get("cacheWriteTokens") or 0),
        output=int(usage.get("outputTokens") or 0),
        dirty=dirty,
    )
```

- [ ] **Step 4: Pass test**

Run: `pytest tests/test_cursor_parse.py -v`

- [ ] **Step 5: Commit** (if authorized)

---

### Task 4: Cursor adapter spawn (P0) + single-step run

**Files:**
- Modify: `src/aiwork/adapters/cursor.py`
- Create: `src/aiwork/runner.py` (minimal single-step)
- Create: `src/aiwork/cli.py`
- Create: `tests/test_cursor_adapter_cmd.py`
- Create: `tests/test_runner_single_step.py`

**Interfaces:**
- Consumes: `StepSpec`, prompt text, workdir, timeout
- Produces: `run_cursor(step, prompt, workdir, env) -> AdapterResult`; `run_single_step(...)` writes status + usage

- [ ] **Step 1: Test command construction (no live agent)**

```python
# tests/test_cursor_adapter_cmd.py
from aiwork.adapters.cursor import build_cursor_command

def test_build_cursor_command_includes_model_and_print():
    cmd = build_cursor_command(model="composer-2", prompt="hi", force=True)
    assert cmd[0] in ("agent", "cursor-agent")
    assert "-p" in cmd or "--print" in cmd
    assert "--output-format" in cmd
    assert "stream-json" in cmd
    assert "--model" in cmd
    assert "composer-2" in cmd
```

- [ ] **Step 2: Implement build + spawn**

```python
def build_cursor_command(*, model: str, prompt: str, force: bool = True) -> list[str]:
    cmd = [
        "agent",
        "-p",
        "--output-format",
        "stream-json",
        "--model",
        model,
        "--trust",
    ]
    if force:
        cmd.append("--force")
    cmd.append(prompt)
    return cmd

def run_cursor(*, model: str, prompt: str, cwd: str, timeout_sec: int, env: dict | None = None) -> AdapterResult:
    import subprocess, os
    cmd = build_cursor_command(model=model, prompt=prompt, force=True)
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        env={**os.environ, **(env or {})},
    )
    parsed = parse_cursor_stream(proc.stdout)
    return AdapterResult(
        exit_code=proc.returncode,
        session_id=parsed.session_id,
        model_actual=parsed.model_actual,
        input_uncached=parsed.input_uncached,
        cache_read=parsed.cache_read,
        cache_write=parsed.cache_write,
        output=parsed.output,
        cost_usd=None,
        dirty=parsed.dirty,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )
```

- [ ] **Step 3: Runner single-step unit test with fake adapter**

Inject a fake `run_fn` that returns fixed `AdapterResult`; assert `status.json` ended `succeeded` and one usage row with `mismatch` if models differ.

```python
# tests/test_runner_single_step.py
from datetime import datetime, timezone
from pathlib import Path
from aiwork.adapters.base import AdapterResult
from aiwork.models import StepSpec
from aiwork.runner import run_single_step
from aiwork.status_store import read_status
from aiwork.ledger import read_usage

def test_single_step_writes_status_and_usage(tmp_path: Path):
    prompt = tmp_path / "p.md"
    prompt.write_text("do thing", encoding="utf-8")
    step = StepSpec(id="s1", agent="cursor", model="composer-2", prompt_file=str(prompt))
    def fake_run(**kwargs):
        return AdapterResult(0, "sess", "Composer 2", 1, 0, 0, 2, None, False, "", "")
    run_dir = run_single_step(
        runs_root=tmp_path / "runs",
        workflow_id="demo",
        step=step,
        workdir=tmp_path,
        run_fn=fake_run,
    )
    assert read_status(run_dir).state == "succeeded"
    assert read_usage(run_dir)[0].mismatch is True  # requested slug != actual display name policy: set mismatch only if normalized differ — see impl note
```

**Impl note:** Define `normalize_model(s) -> s.strip().lower()`; set `mismatch` when normalized requested not in normalized actual and vice-versa substring match fails. Adjust test to match the chosen rule and document the rule in code comment.

- [ ] **Step 4: Implement `run_single_step` + minimal Typer `aiwork run-step`**

```python
# src/aiwork/cli.py
import typer
app = typer.Typer()

@app.command("run-step")
def run_step(
    prompt_file: str,
    model: str = "composer-2",
    runs_root: str = "runs",
    workdir: str = ".",
    timeout_sec: int = 600,
):
    from pathlib import Path
    from aiwork.models import StepSpec
    from aiwork.runner import run_single_step
    from aiwork.adapters.cursor import run_cursor
    step = StepSpec(id="step", agent="cursor", model=model, prompt_file=prompt_file, timeout_sec=timeout_sec)
    run_dir = run_single_step(
        runs_root=Path(runs_root),
        workflow_id="adhoc",
        step=step,
        workdir=Path(workdir),
        run_fn=lambda **kw: run_cursor(model=kw["model"], prompt=kw["prompt"], cwd=kw["cwd"], timeout_sec=kw["timeout_sec"]),
    )
    typer.echo(str(run_dir))
```

- [ ] **Step 5: Pass unit tests**

Run: `pytest tests/test_cursor_adapter_cmd.py tests/test_runner_single_step.py -v`

- [ ] **Step 6: Manual P0 smoke (live Cursor login required)**

```powershell
aiwork run-step prompts\_smoke.md --model <your-model-slug>
Get-Content runs\*\status.json
Get-Content runs\*\usage_events.jsonl
```

Expected: status `succeeded` or `failed` with usage row; no API key files created.

---

### Task 5: Workflow YAML loader

**Files:**
- Create: `src/aiwork/workflow.py`
- Create: `tests/test_workflow.py`
- Create: `workflows/smoke.yaml` + `briefs/smoke.md` + `prompts/smoke/step1.md` (minimal valid demo)

**Interfaces:**
- Consumes: YAML path
- Produces: `load_workflow(path) -> WorkflowSpec`; validates brief_path and each prompt_file exist

- [ ] **Step 1: Failing tests**

```python
def test_load_workflow_ok(tmp_path):
    # write brief, prompt, yaml under tmp_path; load; assert steps[0].id

def test_load_workflow_missing_brief_raises(tmp_path):
    # yaml points at missing brief → FileNotFoundError or WorkflowError
```

- [ ] **Step 2: Implement loader with existence checks**

- [ ] **Step 3: Pass tests + add repo smoke files using `_template` fields**

- [ ] **Step 4: Commit** (if authorized)

---

### Task 6: Sequential runner + approval + current (P1)

**Files:**
- Modify: `src/aiwork/runner.py`
- Modify: `src/aiwork/cli.py`
- Create: `tests/test_runner_sequential.py`

**Interfaces:**
- Consumes: `WorkflowSpec`, adapter registry `dict[AgentName, Callable]`
- Produces: `run_workflow(...)`; CLI `aiwork run`, `aiwork approve`, `aiwork cancel`, `aiwork status`

- [ ] **Step 1: Tests**

```python
def test_sequential_stops_on_failure(tmp_path): ...
def test_approval_gate_does_not_spawn_until_approved(tmp_path): ...
def test_reject_second_run_while_current_running(tmp_path): ...
```

Approval mechanism (concrete): before an `approval: true` step, write `state=awaiting_approval`, create `runs/<id>/approvals/<step_id>.pending`. `aiwork approve <run_id> <step_id>` writes `.approved`. Runner polls file or exits and `aiwork run --resume <run_id>` continues. Prefer **exit + resume** (simpler on Windows) over long poll.

- [ ] **Step 2: Implement sequential loop + resume**

- [ ] **Step 3: `aiwork status` prints current + state + step_id**

- [ ] **Step 4: Pass tests**

- [ ] **Step 5: Commit** (if authorized)

---

### Task 7: `aiwork usage` summary

**Files:**
- Create: `src/aiwork/usage_report.py`
- Modify: `src/aiwork/cli.py`
- Create: `tests/test_usage_report.py`

**Interfaces:**
- Consumes: `read_usage`
- Produces: per-run and per-model totals (input/cache/output); CLI `aiwork usage [run_id]`

- [ ] **Step 1–4:** TDD aggregate by `model_actual`; ignore nothing; show dirty counts.

---

### Task 8: mcp_profile + skills resolution

**Files:**
- Create: `src/aiwork/profiles.py`
- Create: `mcp-profiles/default.yaml`, `mcp-profiles/read-only.yaml`, `mcp-profiles/coding.yaml`
- Create: `skills/research/SKILL.md` (stub), `skills/tdd/SKILL.md` (stub)
- Create: `tests/test_profiles.py`
- Modify: Cursor adapter env / temp mcp config generation

**Interfaces:**
- Consumes: profile name, skills list, repo root
- Produces: `ResolvedProfile(env: dict, extra_args: list[str], mcp_config_path: Path | None)`

`mcp-profiles/read-only.yaml` example:

```yaml
id: read-only
servers:
  - name: notion
    allow_tools: ["search", "fetch"]
```

P0–P2 behavior: generate a step-scoped MCP config file listing only allowed servers (copy connection details from a machine-local `mcp-registry.yaml` gitignored). If profile unknown → error. Skills: copy or `--plugin-dir` / symlink packs into a temp dir passed to Cursor when supported; else prepend prompt with “Follow skills: …” **and** document limitation—prefer filesystem install into `.cursor` step workspace when `--plugin-dir` unavailable.

- [ ] **Step 1–5:** TDD unknown profile fails; known profile returns allowlist; runner passes env to adapter.

Add `mcp-registry.yaml.example` (no secrets) + `.gitignore` for `mcp-registry.yaml`.

---

### Task 9: Claude adapter (P2)

**Files:**
- Create: `src/aiwork/adapters/claude.py`
- Create: `tests/fixtures/claude_result.json`
- Create: `tests/test_claude_parse.py`

**Interfaces:**
- Map `claude -p --output-format json --model …` JSON → `AdapterResult` (`usage` + `modelUsage` + `total_cost_usd`)

- [ ] TDD parse fixture → register in adapter map → one workflow step `agent: claude` with fake run_fn integration.

---

### Task 10: Codex adapter (P2)

**Files:**
- Create: `src/aiwork/adapters/codex.py`
- Create: `tests/fixtures/codex_turn_completed.jsonl`
- Create: `tests/test_codex_parse.py`

**Interfaces:**
- Parse `codex exec --json` for `turn.completed.usage` → AdapterResult (`cached_input_tokens` → `cache_read`)

---

### Task 11: Gemini adapter (P2)

**Files:**
- Create: `src/aiwork/adapters/gemini.py`
- Create: `tests/fixtures/gemini_result.json`
- Create: `tests/test_gemini_parse.py`

**Interfaces:**
- Parse `gemini -p --output-format json -m …` `stats.models[*].tokens` → AdapterResult

---

### Task 12: MCP gateway hook (P3)

**Files:**
- Create: `docs/mcp-gateway.md` (install Conduit or mcp-gateway; point registry)
- Modify: `src/aiwork/profiles.py` to support profile type `gateway` with `url` + `allow_tools`
- Create: `mcp-profiles/gateway-default.yaml`
- Create: `tests/test_gateway_profile.py`

**Interfaces:**
- When profile `transport: gateway`, adapter MCP config is a **single** server entry (HTTP or stdio gateway command); allowlist applied as gateway profile name via env `AIWORK_MCP_PROFILE` or gateway-native profile field.

Do **not** implement OAuth UI. Done when: four agents can share one gateway endpoint in config, and step profile still restricts tools.

---

### Task 13: Triggers (P4)

**Files:**
- Create: `src/aiwork/triggers/cron_run.py` — thin wrapper documenting Task Scheduler / cron calling `aiwork run workflows/x.yaml`
- Create: `scripts/register-windows-task.ps1` example
- Create: `src/aiwork/triggers/README.md` — Slack: receive webhook → write `briefs/` + invoke `aiwork run` (stub interface + example only unless Slack MCP already available)
- Create: `tests/test_cron_argv.py` — ensure module exposes `main(argv)` that calls `run_workflow`

No always-on Slack bot service required for “done”; ship documented entrypoint + argv test.

---

### Task 14: README for operators

**Files:**
- Create: `README.md`

Contents: login each CLI, install `pip install -e .`, write brief from template, `aiwork run`, `aiwork status`, `aiwork usage`, approval flow, mcp-registry, P5 out of scope.

---

## Spec coverage checklist

| Spec area | Task |
|---|---|
| Briefs / workflows / prompts / runs paths | 5, 6, 14 |
| Status + current + aiwork status | 2, 6 |
| usage_events + Cursor cache math | 1, 2, 3 |
| One step one model / dirty | 3, 4 |
| Sequential + approval | 6 |
| mcp_profile + skills | 8, 12 |
| Claude/Codex/Gemini | 9–11 |
| Gateway | 12 |
| cron/Slack trigger | 13 |
| No panel P0–P4 | 14 (explicit) |

## Placeholder scan

None intentional. Live CLI smoke in Task 4 Step 6 is manual evidence, not a code placeholder.

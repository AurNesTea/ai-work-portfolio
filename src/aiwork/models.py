import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

AgentName = Literal["cursor", "claude", "codex", "gemini"]
EffortName = Literal["low", "medium", "high"]
RunState = Literal[
    "queued",
    "running",
    "awaiting_approval",
    "waiting",
    "succeeded",
    "failed",
    "cancelled",
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
    recorded_at: str | None = None
    effort: EffortName = "medium"
    dispatch_role: str | None = None

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
    lives_total: int | None = None
    lives_left: int | None = None


class StepSpec(BaseModel):
    id: str
    agent: AgentName | None = None
    model: str | None = None
    role: str | None = None
    prompt_file: str
    mcp_profile: str = "default"
    skills: list[str] = Field(default_factory=list)
    timeout_sec: int = 600
    on_fail: Literal["stop"] = "stop"
    approval: bool = False
    effort: EffortName = "medium"
    max_retries: int = Field(default=0, ge=0)
    test_command: str = ""
    role_file: str | None = None
    delivery: str | None = None

    @model_validator(mode="after")
    def validate_dispatch_choice(self) -> "StepSpec":
        has_role = bool(self.role and self.role.strip())
        has_agent = bool(self.agent)
        has_model = bool(self.model and self.model.strip())

        if has_role and (has_agent or has_model):
            raise ValueError(f"step {self.id}: cannot specify both role and agent/model")
        if not has_role and not (has_agent and has_model):
            raise ValueError(f"step {self.id}: must specify either role or both agent and model")
        if has_role:
            if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", self.role):
                raise ValueError(
                    f"step {self.id}: invalid role id '{self.role}', must match ^[a-z][a-z0-9-]{{0,31}}$"
                )
        return self


class WorkflowSpec(BaseModel):
    id: str
    brief_path: str
    trigger: Literal["manual", "cron", "slack"] = "manual"
    steps: list[StepSpec]

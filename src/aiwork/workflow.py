from pathlib import Path

import yaml

from aiwork.models import WorkflowSpec


class WorkflowError(Exception):
    pass


def load_workflow(path: Path, root: Path | None = None) -> WorkflowSpec:
    path = Path(path)
    root = Path(root) if root is not None else path.parent.parent
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise WorkflowError(f"workflow must be a mapping: {path}")
    spec = WorkflowSpec.model_validate(raw)
    brief = (root / spec.brief_path).resolve()
    if not brief.is_file():
        raise WorkflowError(f"brief not found: {spec.brief_path}")
    for step in spec.steps:
        prompt = (root / step.prompt_file).resolve()
        if not prompt.is_file():
            raise WorkflowError(f"prompt not found for step {step.id}: {step.prompt_file}")
    return spec

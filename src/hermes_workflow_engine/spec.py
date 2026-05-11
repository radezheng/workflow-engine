from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class SpecError(ValueError):
    """Raised when a workflow spec is invalid."""


@dataclass(frozen=True)
class StepSpec:
    id: str
    title: str
    kind: str
    profile: str | None = None
    needs: list[str] = field(default_factory=list)
    locks: list[str] = field(default_factory=list)
    prompt: str | None = None
    commands: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    review: dict[str, Any] = field(default_factory=dict)
    gates: list[str] = field(default_factory=list)
    on_fail: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def all_gates(self) -> list[str]:
        gates: list[str] = []
        gates.extend(self.gates)
        review_gates = self.review.get("gates", []) if self.review else []
        if isinstance(review_gates, list):
            gates.extend(str(gate) for gate in review_gates)
        return list(dict.fromkeys(gates))


@dataclass(frozen=True)
class WorkflowSpec:
    id: str
    version: str
    workspace_root: Path
    workspace: Path
    project: str | None
    spec_path: Path
    spec_dir: Path
    concurrency: dict[str, Any]
    profiles: dict[str, Any]
    context_profiles: dict[str, Any]
    steps: list[StepSpec]
    raw: dict[str, Any]

    @property
    def engine_dir(self) -> Path:
        return self.workspace / ".engine"


def load_workflow(path: str | Path) -> WorkflowSpec:
    spec_path = Path(path).expanduser().resolve()
    if not spec_path.exists():
        raise SpecError(f"Workflow spec does not exist: {spec_path}")
    with spec_path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}
    if not isinstance(raw, dict):
        raise SpecError("Workflow spec must be a YAML mapping.")

    workflow = raw.get("workflow")
    if not isinstance(workflow, dict):
        raise SpecError("Missing required top-level `workflow` mapping.")

    workflow_id = _required_string(workflow, "id", "workflow.id")
    version = str(workflow.get("version", "0.1.0"))
    workspace_value = _required_string(workflow, "workspace", "workflow.workspace")
    workspace_root = Path(workspace_value).expanduser()
    if not workspace_root.is_absolute():
        workspace_root = (spec_path.parent / workspace_root).resolve()
    else:
        workspace_root = workspace_root.resolve()

    project = workflow.get("project")
    if project is not None and (not isinstance(project, str) or not project.strip()):
        raise SpecError("`workflow.project` must be a non-empty relative path when provided.")
    project_name = project.strip() if isinstance(project, str) else None
    workspace = _resolve_project_workspace(workspace_root, project_name)

    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise SpecError("Missing required non-empty top-level `steps` list.")

    steps = [_parse_step(step_raw, index) for index, step_raw in enumerate(steps_raw)]
    _validate_unique_step_ids(steps)
    _validate_dependencies(steps)

    return WorkflowSpec(
        id=workflow_id,
        version=version,
        workspace_root=workspace_root,
        workspace=workspace,
        project=project_name,
        spec_path=spec_path,
        spec_dir=spec_path.parent,
        concurrency=dict(workflow.get("concurrency", {})),
        profiles=dict(raw.get("profiles", {})),
        context_profiles=dict(raw.get("context_profiles", {})),
        steps=steps,
        raw=raw,
    )


def resolve_spec_path(spec: WorkflowSpec, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    spec_relative = spec.spec_dir / path
    if spec_relative.exists():
        return spec_relative.resolve()
    return (spec.workspace / path).resolve()


def resolve_workspace_path(spec: WorkflowSpec, value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (spec.workspace / path).resolve()


def _parse_step(step_raw: Any, index: int) -> StepSpec:
    if not isinstance(step_raw, dict):
        raise SpecError(f"steps[{index}] must be a mapping.")
    step_id = _required_string(step_raw, "id", f"steps[{index}].id")
    kind = _required_string(step_raw, "kind", f"steps[{index}].kind")
    if kind not in {"agent", "command"}:
        raise SpecError(f"Step {step_id} has unsupported kind `{kind}`.")
    title = str(step_raw.get("title", step_id))
    commands = _string_list(step_raw.get("commands", []), f"steps[{index}].commands")
    if kind == "command" and not commands:
        raise SpecError(f"Command step {step_id} requires at least one command.")
    if kind == "agent" and not step_raw.get("prompt"):
        raise SpecError(f"Agent step {step_id} requires `prompt`.")
    return StepSpec(
        id=step_id,
        title=title,
        kind=kind,
        profile=str(step_raw.get("profile")) if step_raw.get("profile") else None,
        needs=_string_list(step_raw.get("needs", []), f"steps[{index}].needs"),
        locks=_string_list(step_raw.get("locks", []), f"steps[{index}].locks"),
        prompt=str(step_raw.get("prompt")) if step_raw.get("prompt") else None,
        commands=commands,
        outputs=_string_list(step_raw.get("outputs", []), f"steps[{index}].outputs"),
        context=dict(step_raw.get("context", {})),
        review=dict(step_raw.get("review", {})),
        gates=_string_list(step_raw.get("gates", []), f"steps[{index}].gates"),
        on_fail=dict(step_raw.get("on_fail", {})),
        timeout_seconds=int(step_raw["timeout_seconds"]) if step_raw.get("timeout_seconds") else None,
        raw=step_raw,
    )


def _required_string(mapping: dict[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SpecError(f"Missing required string `{label}`.")
    return value.strip()


def _resolve_project_workspace(workspace_root: Path, project: str | None) -> Path:
    if project is None:
        return workspace_root
    project_path = Path(project).expanduser()
    if project_path.is_absolute():
        raise SpecError("`workflow.project` must be relative to `workflow.workspace`.")
    resolved = (workspace_root / project_path).resolve()
    try:
        resolved.relative_to(workspace_root.resolve())
    except ValueError as exc:
        raise SpecError("`workflow.project` must stay inside `workflow.workspace`.") from exc
    return resolved


def _string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        raise SpecError(f"`{label}` must be a list of strings.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise SpecError(f"`{label}` must be a list of strings.")
        result.append(item)
    return result


def _validate_unique_step_ids(steps: list[StepSpec]) -> None:
    seen: set[str] = set()
    for step in steps:
        if step.id in seen:
            raise SpecError(f"Duplicate step id `{step.id}`.")
        seen.add(step.id)


def _validate_dependencies(steps: list[StepSpec]) -> None:
    ids = {step.id for step in steps}
    for step in steps:
        missing = [need for need in step.needs if need not in ids]
        if missing:
            raise SpecError(f"Step {step.id} depends on unknown step ids: {', '.join(missing)}")
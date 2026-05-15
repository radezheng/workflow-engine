from __future__ import annotations

from importlib import resources
from pathlib import Path
import re
from typing import Any

import yaml

from .config import HWEConfig


DEFAULT_WORKFLOW_TEMPLATE_ID = "software-project-dev"
_PARAM_PATTERN = re.compile(r"\$\{([A-Za-z0-9_.-]+)\}")
_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class WorkflowTemplateError(ValueError):
    """Raised when a workflow template is missing or invalid."""


def list_workflow_templates(config: HWEConfig, *, project_root: Path | None = None) -> list[dict[str, Any]]:
    templates: dict[str, dict[str, Any]] = {}
    for raw in _builtin_templates():
        templates[raw["id"]] = raw
    if config.workflow_template_root:
        for raw in _file_templates(config.workflow_template_root, source="config"):
            templates[raw["id"]] = raw
    if project_root:
        for raw in _file_templates(project_root / ".engine" / "workflow-templates", source="project"):
            templates[raw["id"]] = raw
    return sorted(templates.values(), key=lambda item: str(item.get("id", "")))


def get_workflow_template(config: HWEConfig, template_id: str, *, project_root: Path | None = None) -> dict[str, Any]:
    safe_id = template_id.strip()
    if not _SAFE_ID_PATTERN.fullmatch(safe_id):
        raise WorkflowTemplateError("Workflow template id must be a safe path segment.")
    for template in list_workflow_templates(config, project_root=project_root):
        if template["id"] == safe_id:
            return template
    raise WorkflowTemplateError(f"Workflow template not found: {safe_id}")


def resolve_workflow_template(raw_template: dict[str, Any], parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    params = _default_parameters(raw_template)
    for key, value in (parameters or {}).items():
        if isinstance(key, str) and key.strip():
            params[key.strip()] = str(value)
    profiles = _render_value(raw_template.get("profiles", {}), params)
    prompt_templates = _render_value(raw_template.get("prompt_templates", {}), {**params, **_prefixed("profile", profiles)})
    variables = {
        **params,
        **_prefixed("profile", profiles),
        **_prefixed("prompt_template", prompt_templates),
    }
    resolved = _render_value(raw_template, variables)
    resolved["resolved_parameters"] = params
    resolved["profiles"] = profiles
    resolved["prompt_templates"] = prompt_templates
    return resolved


def workflow_template_can_materialize(template: dict[str, Any], task: dict[str, Any]) -> bool:
    if task.get("status") != "succeeded":
        return False
    materialize = template.get("materialize") if isinstance(template.get("materialize"), dict) else {}
    sources = materialize.get("sources") if isinstance(materialize.get("sources"), list) else []
    for source in sources:
        if not isinstance(source, dict):
            continue
        statuses = source.get("statuses") if isinstance(source.get("statuses"), list) else ["succeeded"]
        if task.get("status") not in statuses:
            continue
        stage_id = source.get("stage")
        if stage_id and task.get("created_reason") == workflow_stage_created_reason(template["id"], str(stage_id)):
            return True
        if stage_id:
            continue
        source_ref = source.get("prompt_template_ref")
        if source_ref and task.get("prompt_template_ref") == source_ref:
            return True
    return False


def workflow_materialize_action(template: dict[str, Any], task: dict[str, Any]) -> dict[str, Any] | None:
    if not workflow_template_can_materialize(template, task):
        return None
    task_spec = _materialize_task_spec(template)
    return {
        "workflow_template_id": template["id"],
        "profile": task_spec.get("profile"),
        "prompt_template_ref": task_spec.get("prompt_template_ref"),
        "parameters": template.get("resolved_parameters", {}),
    }


def planning_task_spec(template: dict[str, Any]) -> dict[str, Any]:
    spec = template.get("planning_task")
    if not isinstance(spec, dict):
        raise WorkflowTemplateError(f"Workflow template `{template['id']}` has no planning_task mapping.")
    return spec


def review_task_specs(template: dict[str, Any]) -> list[dict[str, Any]]:
    specs = template.get("review_tasks")
    if not isinstance(specs, list):
        return []
    return [spec for spec in specs if isinstance(spec, dict)]


def materialize_task_spec(template: dict[str, Any]) -> dict[str, Any]:
    return _materialize_task_spec(template)


def workflow_stage_created_reason(template_id: str, stage_id: str) -> str:
    return f"workflow-template:{template_id}:stage:{stage_id}"


def render_materialize_prompt(template: dict[str, Any], variables: dict[str, Any]) -> str:
    materialize = template.get("materialize") if isinstance(template.get("materialize"), dict) else {}
    prompt = materialize.get("input_prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise WorkflowTemplateError(f"Workflow template `{template['id']}` has no materialize.input_prompt.")
    return str(_render_value(prompt, {key: str(value) for key, value in variables.items()}))


def nested_workflows_text(template: dict[str, Any]) -> str:
    nested = template.get("child_workflows") if isinstance(template.get("child_workflows"), list) else []
    if not nested:
        return "无。"
    lines = []
    for item in nested:
        if not isinstance(item, dict):
            continue
        child_id = item.get("id", "child")
        child_template = item.get("template", child_id)
        trigger = item.get("trigger", "按父 workflow 指示调用")
        description = item.get("description", "")
        lines.append(f"- {child_id}: template={child_template}; trigger={trigger}; {description}".rstrip())
    return "\n".join(lines) if lines else "无。"


def _materialize_task_spec(template: dict[str, Any]) -> dict[str, Any]:
    materialize = template.get("materialize") if isinstance(template.get("materialize"), dict) else {}
    task_spec = materialize.get("task")
    if not isinstance(task_spec, dict):
        raise WorkflowTemplateError(f"Workflow template `{template['id']}` has no materialize.task mapping.")
    return task_spec


def _builtin_templates() -> list[dict[str, Any]]:
    root = resources.files("hermes_workflow_engine").joinpath("workflow_templates")
    templates = []
    for child in sorted(root.iterdir()):
        if child.name.endswith((".yaml", ".yml")):
            with resources.as_file(child) as path:
                templates.append(_load_template_file(path, source="builtin"))
    return templates


def _file_templates(root: Path, *, source: str) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    return [_load_template_file(path, source=source) for path in sorted(root.glob("*.y*ml"))]


def _load_template_file(path: Path, *, source: str) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}
    if not isinstance(raw, dict):
        raise WorkflowTemplateError(f"Workflow template must be a YAML mapping: {path}")
    template_id = raw.get("id")
    if not isinstance(template_id, str) or not _SAFE_ID_PATTERN.fullmatch(template_id):
        raise WorkflowTemplateError(f"Workflow template id must be a safe path segment: {path}")
    raw = dict(raw)
    raw["source"] = source
    raw["path"] = str(path)
    return raw


def _default_parameters(template: dict[str, Any]) -> dict[str, str]:
    parameters = template.get("parameters", {})
    if not isinstance(parameters, dict):
        return {}
    defaults: dict[str, str] = {}
    for name, spec in parameters.items():
        if not isinstance(name, str):
            continue
        if isinstance(spec, dict):
            value = spec.get("default", "")
        else:
            value = spec
        defaults[name] = str(value)
    return defaults


def _prefixed(prefix: str, values: Any) -> dict[str, str]:
    if not isinstance(values, dict):
        return {}
    return {f"{prefix}.{key}": str(value) for key, value in values.items()}


def _render_value(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):
        return _PARAM_PATTERN.sub(lambda match: variables.get(match.group(1), match.group(0)), value)
    if isinstance(value, list):
        return [_render_value(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: _render_value(item, variables) for key, item in value.items()}
    return value
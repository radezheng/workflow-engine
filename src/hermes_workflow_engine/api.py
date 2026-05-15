from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .ai import AIProviderError, AssistTarget, create_ai_assist_response, list_ai_providers
from .config import ConfigError, HWEConfig, load_config
from .project_runtime import ProjectRuntime
from .project_storage import ProjectStorage, ProjectStorageError, resolve_project_root
from .workflow_templates import (
    DEFAULT_WORKFLOW_TEMPLATE_ID,
    WorkflowTemplateError,
    get_workflow_template,
    list_workflow_templates,
    materialize_task_spec,
    nested_workflows_text,
    planning_task_spec,
    review_task_specs,
    render_materialize_prompt,
    resolve_workflow_template,
    workflow_materialize_action,
    workflow_stage_created_reason,
)


PROJECT_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
LOCAL_CORS_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(?::\d{1,5})?$"
HERMES_SESSION_ID_PATTERN = re.compile(r"session_id:\s*([A-Za-z0-9_-]+)")


app = FastAPI(title="Hermes Workflow Engine API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=LOCAL_CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ProjectStorageError)
async def project_storage_exception_handler(_request: Request, exc: ProjectStorageError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


class RunWorkitemRequest(BaseModel):
    project_id: str | None = None
    worker_id: str = "hwe-api"
    profile: str | None = None
    max_tasks: int | None = Field(default=1, ge=1)
    dry_run: bool = False


class RunTaskRequest(BaseModel):
    project_id: str | None = None
    worker_id: str = "hwe-api"
    profile: str | None = None
    dry_run: bool = False


class PlanWorkitemRequest(BaseModel):
    project_id: str | None = None
    workflow_template_id: str = DEFAULT_WORKFLOW_TEMPLATE_ID
    parameters: dict[str, Any] = Field(default_factory=dict)
    planner_profile: str | None = None
    prompt_template_ref: str | None = None


class MaterializePlanRequest(BaseModel):
    project_id: str | None = None
    workflow_template_id: str = DEFAULT_WORKFLOW_TEMPLATE_ID
    parameters: dict[str, Any] = Field(default_factory=dict)
    profile: str | None = None
    prompt_template_ref: str | None = None
    prompt_text: str | None = None


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    project_ref: str | None = Field(default=None, min_length=1)
    project_id: str | None = Field(default=None, min_length=1)


class WorkitemCreateRequest(BaseModel):
    project_id: str | None = None
    title: str = Field(min_length=1)
    type: str = "feature"
    requirements: str = ""
    constraints: str = ""
    acceptance: list[str] = Field(default_factory=list)
    priority: int = Field(default=100, ge=0)
    risk_level: str = "medium"


class PromptTemplateCreateRequest(BaseModel):
    project_id: str | None = None
    role: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = "file"
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    body: str | None = None


class TaskUpdateRequest(BaseModel):
    project_id: str | None = None
    profile: str | None = None
    prompt_template_ref: str | None = None
    prompt_text: str | None = None


class TaskReassignRequest(BaseModel):
    project_id: str | None = None
    profile: str | None = None
    reason: str = "reassigned"


class AIAssistMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AIAssistRequest(BaseModel):
    provider: str
    target: AssistTarget
    messages: list[AIAssistMessage] = Field(default_factory=list)
    draft: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class TaskRetryRequest(BaseModel):
    reason: str = "api-retry"


class TaskReleaseRequest(BaseModel):
    reason: str = "api-release"


class TaskCompleteRequest(BaseModel):
    status: Literal["succeeded", "failed", "cancelled", "skipped", "superseded", "waiting_for_info", "waiting_for_approval"] = "succeeded"
    result: dict[str, Any] | None = None
    title: str | None = None
    body: str | None = None
    questions: list[dict[str, Any]] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    requested_by: str | None = None


class HumanActionResponseRequest(BaseModel):
    text: str = ""
    by: str | None = None
    response: dict[str, Any] | None = None


class HumanActionRejectRequest(BaseModel):
    reason: str
    by: str | None = None


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
def config_status() -> dict[str, Any]:
    config = _config()
    project_database = config.project_database or {}
    project_database_status = {
        "backend": project_database.get("backend", "sqlite"),
    }
    if project_database_status["backend"] == "postgres":
        project_database_status.update(
            {
                "host": project_database.get("host"),
                "port": project_database.get("port", 5432),
                "database": project_database.get("database"),
                "user": project_database.get("user"),
                "schema": project_database.get("schema", "hwe"),
                "maxconn": project_database.get("maxconn", 5),
                "has_password": bool(project_database.get("password") or project_database.get("password_env") or project_database.get("password_command")),
            }
        )
    return {
        "path": str(config.source_path) if config.source_path else None,
        "exists": bool(config.source_path and config.source_path.exists()),
        "default_workspace_root": str(config.default_workspace_root) if config.default_workspace_root else None,
        "prompt_template_root": str(config.prompt_template_root) if config.prompt_template_root else None,
        "workflow_template_root": str(config.workflow_template_root) if config.workflow_template_root else None,
        "project_database": project_database_status,
        "profiles": sorted((config.profiles or {}).keys()),
        "ai_providers": [provider["name"] for provider in list_ai_providers(config)],
    }


@app.get("/api/ai/providers")
def ai_providers() -> list[dict[str, Any]]:
    return list_ai_providers(_config())


@app.get("/api/prompt-templates")
def list_public_prompt_templates(role: str | None = None) -> list[dict[str, Any]]:
    return _list_file_prompt_templates(_public_template_root(_config()), source="public", role=role)


@app.post("/api/prompt-templates")
def save_public_prompt_template(request: PromptTemplateCreateRequest) -> dict[str, Any]:
    config = _config()
    role, name = _validate_template_ref(request.role, request.name)
    body = request.body if request.body is not None and request.body.strip() else _template_library_body(config, role, name)
    return _write_file_prompt_template(_public_template_root(config), source="public", role=role, name=name, body=body)


@app.delete("/api/prompt-templates/{role}/{name}")
def delete_public_prompt_template(role: str, name: str) -> dict[str, Any]:
    role, name = _validate_template_ref(role, name)
    return _delete_file_prompt_template(_public_template_root(_config()), source="public", role=role, name=name)


@app.post("/api/ai/assist")
def ai_assist(request: AIAssistRequest) -> dict[str, Any]:
    config = _config()
    try:
        return create_ai_assist_response(
            config,
            provider_name=request.provider,
            target=request.target,
            messages=[message.model_dump() for message in request.messages],
            draft=request.draft,
            context=_ai_assist_context(config, request.target, request.context),
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects")
def list_projects(include_archived: bool = False) -> dict[str, Any]:
    config = _config()
    projects = []
    if (config.project_database or {}).get("backend") == "postgres":
        storage = ProjectStorage(config.default_workspace_root or Path.cwd(), config=config)
        for project in storage.list_projects(include_archived=include_archived):
            project_root = Path(project["root_path"])
            project["project_ref"] = project_root.name
            project["engine_db"] = storage.database_location()
            projects.append(project)
        return {"projects": projects, "default_workspace_root": str(config.default_workspace_root) if config.default_workspace_root else None}
    if config.default_workspace_root and config.default_workspace_root.exists():
        for engine_db in sorted(config.default_workspace_root.glob("*/.engine/engine.db")):
            storage = ProjectStorage(engine_db.parents[1], config=config)
            for project in storage.list_projects(include_archived=include_archived):
                project["project_ref"] = engine_db.parents[1].name
                project["engine_db"] = storage.database_location()
                projects.append(project)
    return {"projects": projects, "default_workspace_root": str(config.default_workspace_root) if config.default_workspace_root else None}


@app.post("/api/projects")
def create_project(request: ProjectCreateRequest) -> dict[str, Any]:
    config = _config()
    if config.default_workspace_root is None:
        raise HTTPException(status_code=400, detail="Creating projects requires HWE config `default_workspace_root`.")
    project_name = request.name.strip()
    if not project_name:
        raise HTTPException(status_code=400, detail="Project name is required.")
    project_ref = request.project_ref.strip() if request.project_ref else _slug(project_name)
    if not PROJECT_REF_PATTERN.fullmatch(project_ref):
        raise HTTPException(status_code=400, detail="Project ref must be one path segment using letters, numbers, dots, underscores, or dashes.")
    project_root = (config.default_workspace_root / project_ref).resolve()
    _ensure_inside(project_root, config.default_workspace_root)
    storage = ProjectStorage(project_root, config=config)
    project = storage.upsert_project(project_name, project_id=request.project_id or project_ref)
    project["project_ref"] = project_ref
    project["engine_db"] = storage.database_location()
    return project


@app.get("/api/projects/{project_ref}")
def get_project(project_ref: str, project_id: str | None = None) -> dict[str, Any]:
    storage = _storage(project_ref)
    return storage.get_project(_project_id(project_ref, project_id))


@app.post("/api/projects/{project_ref}/archive")
def archive_project(project_ref: str, project_id: str | None = None) -> dict[str, Any]:
    storage = _storage(project_ref)
    project = storage.archive_project(_project_id(project_ref, project_id))
    project["project_ref"] = project_ref
    project["engine_db"] = storage.database_location()
    return project


@app.post("/api/projects/{project_ref}/restore")
def restore_project(project_ref: str, project_id: str | None = None) -> dict[str, Any]:
    storage = _storage(project_ref)
    project = storage.restore_project(_project_id(project_ref, project_id))
    project["project_ref"] = project_ref
    project["engine_db"] = storage.database_location()
    return project


@app.get("/api/projects/{project_ref}/workitems")
def list_workitems(project_ref: str, project_id: str | None = None, include_archived: bool = False) -> list[dict[str, Any]]:
    storage = _storage(project_ref)
    return storage.list_workitems(_project_id(project_ref, project_id), include_archived=include_archived)


@app.post("/api/projects/{project_ref}/workitems")
def create_workitem(project_ref: str, request: WorkitemCreateRequest) -> dict[str, Any]:
    storage = _storage(project_ref)
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Workitem title is required.")
    return storage.create_workitem(
        _project_id(project_ref, request.project_id),
        title,
        workitem_type=request.type,
        requirements=request.requirements,
        constraints=request.constraints,
        acceptance=request.acceptance,
        priority=request.priority,
        risk_level=request.risk_level,
    )


@app.post("/api/projects/{project_ref}/workitems/{workitem_id}/archive")
def archive_workitem(project_ref: str, workitem_id: str, project_id: str | None = None) -> dict[str, Any]:
    storage = _storage(project_ref)
    if storage.get_workitem(workitem_id)["project_id"] != _project_id(project_ref, project_id):
        raise HTTPException(status_code=404, detail="Workitem does not belong to project.")
    return storage.archive_workitem(workitem_id)


@app.post("/api/projects/{project_ref}/workitems/{workitem_id}/restore")
def restore_workitem(project_ref: str, workitem_id: str, project_id: str | None = None) -> dict[str, Any]:
    storage = _storage(project_ref)
    if storage.get_workitem(workitem_id)["project_id"] != _project_id(project_ref, project_id):
        raise HTTPException(status_code=404, detail="Workitem does not belong to project.")
    return storage.restore_workitem(workitem_id)


@app.get("/api/projects/{project_ref}/workitems/{workitem_id}/dashboard")
def workitem_dashboard(project_ref: str, workitem_id: str, project_id: str | None = None) -> dict[str, Any]:
    storage = _storage(project_ref)
    config = _config()
    resolved_project_id = _project_id(project_ref, project_id)
    workitem = storage.get_workitem(workitem_id)
    if workitem["project_id"] != resolved_project_id:
        raise HTTPException(status_code=404, detail="Workitem does not belong to project.")
    workflows = storage.list_workflows(resolved_project_id, workitem_id=workitem_id)
    current_workflow = storage.get_workflow(workitem["current_workflow_id"]) if workitem.get("current_workflow_id") else None
    tasks = storage.list_tasks(current_workflow["id"]) if current_workflow else []
    templates = _resolved_workflow_templates(config, storage)
    tasks = [_with_workflow_actions(task, templates) for task in tasks]
    runs = storage.list_task_runs(workflow_id=current_workflow["id"], limit=100) if current_workflow else []
    human_actions = storage.list_human_actions(resolved_project_id)
    events = storage.list_events(resolved_project_id, limit=100)
    return {
        "project": storage.get_project(resolved_project_id),
        "workitem": workitem,
        "workflows": workflows,
        "current_workflow": current_workflow,
        "tasks": tasks,
        "runs": runs,
        "human_actions": human_actions,
        "events": events,
    }


@app.get("/api/projects/{project_ref}/workflows")
def list_workflows(project_ref: str, project_id: str | None = None, workitem_id: str | None = None) -> list[dict[str, Any]]:
    storage = _storage(project_ref)
    return storage.list_workflows(_project_id(project_ref, project_id), workitem_id=workitem_id)


@app.get("/api/projects/{project_ref}/workflow-templates")
def list_project_workflow_templates(project_ref: str, project_id: str | None = None) -> list[dict[str, Any]]:
    storage = _storage(project_ref)
    resolved_project_id = _project_id(project_ref, project_id)
    storage.get_project(resolved_project_id)
    return _resolved_workflow_templates(_config(), storage)


@app.get("/api/projects/{project_ref}/workflows/{workflow_id}/tasks")
def list_tasks(project_ref: str, workflow_id: str) -> list[dict[str, Any]]:
    return _storage(project_ref).list_tasks(workflow_id)


@app.get("/api/projects/{project_ref}/tasks/{task_id}")
def get_task(project_ref: str, task_id: str) -> dict[str, Any]:
    return _storage(project_ref).get_task(task_id)


@app.get("/api/projects/{project_ref}/tasks/{task_id}/runs")
def list_task_runs(project_ref: str, task_id: str, limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    return _storage(project_ref).list_task_runs(task_id=task_id, limit=limit)


@app.get("/api/projects/{project_ref}/runs/{run_id}")
def get_task_run(project_ref: str, run_id: str) -> dict[str, Any]:
    return _storage(project_ref).get_task_run(run_id)


@app.get("/api/projects/{project_ref}/runs/{run_id}/logs")
def read_run_log(project_ref: str, run_id: str, stream: Literal["stdout", "stderr", "prompt"] = "stdout") -> dict[str, Any]:
    storage = _storage(project_ref)
    run = storage.get_task_run(run_id)
    path_key = {"stdout": "stdout_path", "stderr": "stderr_path", "prompt": "prompt_path"}[stream]
    fallback_name = {"stdout": "stdout.log", "stderr": "stderr.log", "prompt": "prompt.md"}[stream]
    raw_path = run.get(path_key)
    if not raw_path:
        fallback_path = storage.engine_dir / "runs" / run_id / fallback_name
        raw_path = str(fallback_path) if fallback_path.exists() else None
    if not raw_path:
        return {"run_id": run_id, "stream": stream, "text": ""}
    path = Path(raw_path)
    _ensure_inside(path, storage.engine_dir)
    return {"run_id": run_id, "stream": stream, "path": str(path), "text": path.read_text(encoding="utf-8") if path.exists() else ""}


@app.get("/api/projects/{project_ref}/runs/{run_id}/timeline")
def read_run_timeline(project_ref: str, run_id: str, limit: int = Query(default=200, ge=1, le=1000)) -> dict[str, Any]:
    storage = _storage(project_ref)
    run = storage.get_task_run(run_id)
    session_id = _run_hermes_session_id(storage, run)
    if not session_id:
        return {"run_id": run_id, "session_id": None, "session": None, "events": [], "status": "missing_session_id"}

    session_paths = _hermes_session_paths(session_id, profile=run.get("profile"))
    jsonl_path = next((path for path in session_paths["jsonl"] if path.exists()), None)
    json_path = next((path for path in session_paths["json"] if path.exists()), None)
    searched = [str(path) for paths in session_paths.values() for path in paths]
    if jsonl_path is None:
        json_events = _read_hermes_session_json_events(json_path, limit=limit) if json_path else []
        if json_events:
            return {
                "run_id": run_id,
                "session_id": session_id,
                "session": _read_hermes_session_summary(json_path),
                "events": json_events,
                "status": "ok",
                "path": str(json_path),
                "searched_paths": searched,
            }
        return {
            "run_id": run_id,
            "session_id": session_id,
            "session": _read_hermes_session_summary(json_path) if json_path else None,
            "events": [],
            "status": "missing_session_log",
            "searched_paths": searched,
        }

    return {
        "run_id": run_id,
        "session_id": session_id,
        "session": _read_hermes_session_summary(json_path),
        "events": _read_hermes_session_events(jsonl_path, limit=limit),
        "status": "ok",
        "path": str(jsonl_path),
        "searched_paths": searched,
    }


@app.get("/api/projects/{project_ref}/events")
def list_events(project_ref: str, project_id: str | None = None, limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    storage = _storage(project_ref)
    return storage.list_events(_project_id(project_ref, project_id), limit=limit)


@app.get("/api/projects/{project_ref}/human-actions")
def list_human_actions(project_ref: str, project_id: str | None = None, status: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
    storage = _storage(project_ref)
    return storage.list_human_actions(_project_id(project_ref, project_id), status=status, kind=kind)


@app.get("/api/projects/{project_ref}/prompt-templates")
def list_prompt_templates(project_ref: str, project_id: str | None = None, role: str | None = None) -> list[dict[str, Any]]:
    storage = _storage(project_ref)
    storage.get_project(_project_id(project_ref, project_id))
    public_templates = _list_file_prompt_templates(_public_template_root(_config()), source="public", role=role)
    project_templates = _list_file_prompt_templates(_project_template_root(storage.project_root), source="project", role=role)
    return sorted([*project_templates, *public_templates], key=lambda template: (template["role"], template["name"], template["source"]))


@app.post("/api/projects/{project_ref}/prompt-templates")
def create_prompt_template(project_ref: str, request: PromptTemplateCreateRequest) -> dict[str, Any]:
    storage = _storage(project_ref)
    config = _config()
    storage.get_project(_project_id(project_ref, request.project_id))
    role, name = _validate_template_ref(request.role, request.name)
    body = request.body if request.body is not None and request.body.strip() else _template_library_body(config, role, name)
    return _write_file_prompt_template(_project_template_root(storage.project_root), source="project", role=role, name=name, body=body)


@app.delete("/api/projects/{project_ref}/prompt-templates/{role}/{name}")
def delete_project_prompt_template(project_ref: str, role: str, name: str, project_id: str | None = None) -> dict[str, Any]:
    storage = _storage(project_ref)
    storage.get_project(_project_id(project_ref, project_id))
    role, name = _validate_template_ref(role, name)
    return _delete_file_prompt_template(_project_template_root(storage.project_root), source="project", role=role, name=name)


@app.post("/api/projects/{project_ref}/workitems/{workitem_id}/run")
def run_workitem(project_ref: str, workitem_id: str, request: RunWorkitemRequest) -> dict[str, Any]:
    storage = _storage(project_ref)
    project_id = _project_id(project_ref, request.project_id)
    runtime = ProjectRuntime(storage, dry_run=request.dry_run)
    summary = runtime.run_workitem(
        project_id,
        workitem_id,
        worker_id=request.worker_id,
        profile=request.profile,
        max_tasks=request.max_tasks,
    )
    return asdict(summary)


@app.post("/api/projects/{project_ref}/tasks/{task_id}/run")
def run_task(project_ref: str, task_id: str, request: RunTaskRequest) -> dict[str, Any]:
    storage = _storage(project_ref)
    project_id = _project_id(project_ref, request.project_id)
    runtime = ProjectRuntime(storage, dry_run=request.dry_run)
    summary = runtime.run_one_task(project_id, task_id, worker_id=request.worker_id, profile=request.profile)
    return asdict(summary)


@app.post("/api/projects/{project_ref}/workitems/{workitem_id}/plan")
def plan_workitem(project_ref: str, workitem_id: str, request: PlanWorkitemRequest) -> dict[str, Any]:
    storage = _storage(project_ref)
    config = _config()
    project_id = _project_id(project_ref, request.project_id)
    workitem = storage.get_workitem(workitem_id)
    if workitem["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Workitem does not belong to project.")
    template = _resolved_workflow_template(config, storage, request.workflow_template_id, request.parameters)
    plan_spec = planning_task_spec(template)
    planner_profile = request.planner_profile or str(plan_spec.get("profile") or "")
    prompt_template_ref = _validate_prompt_template_ref(request.prompt_template_ref or str(plan_spec.get("prompt_template_ref") or ""))
    if not planner_profile:
        raise HTTPException(status_code=400, detail=f"Workflow template `{template['id']}` planning task has no profile.")
    if not _prompt_template_exists(storage, config, prompt_template_ref):
        raise HTTPException(status_code=400, detail=f"Prompt template not found: {prompt_template_ref}")
    workflow = storage.get_workflow(workitem["current_workflow_id"]) if workitem.get("current_workflow_id") else storage.create_workflow(project_id, workitem_id, planner_profile=planner_profile)
    tasks = storage.list_tasks(workflow["id"])
    created_reason = workflow_stage_created_reason(template["id"], str(plan_spec.get("stage", "planning")))
    planner_task = next((task for task in tasks if task.get("created_reason") == created_reason), None)
    if planner_task is None:
        planner_task = storage.create_task(
            workflow["id"],
            str(plan_spec.get("title") or "规划 workitem"),
            kind=str(plan_spec.get("kind") or "planning"),
            profile=planner_profile,
            prompt_template_ref=prompt_template_ref,
            prompt_text=str(plan_spec.get("prompt_text") or ""),
            skills=_string_list(plan_spec.get("skills"), default=["hwe"]),
            outputs=_string_list(plan_spec.get("outputs")),
            gates=_string_list(plan_spec.get("gates")),
            priority=_int_value(plan_spec.get("priority"), 10),
            risk_level=workitem["risk_level"],
            created_by="hwe-api",
            created_reason=created_reason,
        )
    for review_spec in review_task_specs(template):
        review_stage = str(review_spec.get("stage") or "planning-review")
        review_created_reason = workflow_stage_created_reason(template["id"], review_stage)
        if any(task.get("created_reason") == review_created_reason for task in storage.list_tasks(workflow["id"])):
            continue
        review_profile = str(review_spec.get("profile") or "")
        review_prompt_template_ref = _validate_prompt_template_ref(str(review_spec.get("prompt_template_ref") or ""))
        if not review_profile:
            raise HTTPException(status_code=400, detail=f"Workflow template `{template['id']}` review task `{review_stage}` has no profile.")
        if not _prompt_template_exists(storage, config, review_prompt_template_ref):
            raise HTTPException(status_code=400, detail=f"Prompt template not found: {review_prompt_template_ref}")
        storage.create_task(
            workflow["id"],
            str(review_spec.get("title") or "Review plan"),
            kind=str(review_spec.get("kind") or "review"),
            profile=review_profile,
            depends_on=[planner_task["id"]],
            prompt_template_ref=review_prompt_template_ref,
            prompt_text=str(review_spec.get("prompt_text") or ""),
            skills=_string_list(review_spec.get("skills"), default=["hwe"]),
            outputs=_string_list(review_spec.get("outputs")),
            gates=_string_list(review_spec.get("gates")),
            priority=planner_task["priority"] + _int_value(review_spec.get("priority_offset"), 1),
            risk_level=workitem["risk_level"],
            created_by="hwe-api",
            created_reason=review_created_reason,
        )
    return {"workflow": workflow, "task": planner_task, "tasks": storage.list_tasks(workflow["id"])}


@app.post("/api/projects/{project_ref}/tasks/{task_id}/retry")
def retry_task(project_ref: str, task_id: str, request: TaskRetryRequest) -> dict[str, Any]:
    return _storage(project_ref).retry_task(task_id, reason=request.reason)


@app.post("/api/projects/{project_ref}/tasks/{task_id}/release")
def release_task(project_ref: str, task_id: str, request: TaskReleaseRequest) -> dict[str, Any]:
    return _storage(project_ref).release_task_claim(task_id, reason=request.reason)


@app.patch("/api/projects/{project_ref}/tasks/{task_id}")
def update_task(project_ref: str, task_id: str, request: TaskUpdateRequest) -> dict[str, Any]:
    storage = _storage(project_ref)
    task = storage.get_task(task_id)
    project_id = _project_id(project_ref, request.project_id)
    if task["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Task does not belong to project.")
    prompt_template_ref = _validate_prompt_template_ref(request.prompt_template_ref) if request.prompt_template_ref else None
    if prompt_template_ref and not _prompt_template_exists(storage, _config(), prompt_template_ref):
        raise HTTPException(status_code=400, detail=f"Prompt template not found: {prompt_template_ref}")
    return storage.update_task_definition(task_id, profile=request.profile, prompt_template_ref=prompt_template_ref, prompt_text=request.prompt_text)


@app.post("/api/projects/{project_ref}/tasks/{task_id}/reassign")
def reassign_task(project_ref: str, task_id: str, request: TaskReassignRequest) -> dict[str, Any]:
    storage = _storage(project_ref)
    task = storage.get_task(task_id)
    project_id = _project_id(project_ref, request.project_id)
    if task["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Task does not belong to project.")
    return storage.reassign_task_profile(task_id, profile=request.profile, reason=request.reason)


@app.get("/api/projects/{project_ref}/tasks/{task_id}/prompt-preview")
def task_prompt_preview(project_ref: str, task_id: str, project_id: str | None = None) -> dict[str, Any]:
    storage = _storage(project_ref)
    task = storage.get_task(task_id)
    if task["project_id"] != _project_id(project_ref, project_id):
        raise HTTPException(status_code=404, detail="Task does not belong to project.")
    try:
        prompt = ProjectRuntime(storage).build_task_prompt(task)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"task_id": task_id, "prompt_template_ref": task.get("prompt_template_ref"), "text": prompt}


@app.post("/api/projects/{project_ref}/tasks/{task_id}/complete")
def complete_task(project_ref: str, task_id: str, request: TaskCompleteRequest) -> dict[str, Any]:
    return _storage(project_ref).complete_task(
        task_id,
        status=request.status,
        result=request.result,
        human_action_title=request.title,
        human_action_body=request.body,
        questions=request.questions,
        options=request.options,
        evidence=request.evidence,
        requested_by=request.requested_by,
    )


@app.post("/api/projects/{project_ref}/tasks/{task_id}/materialize-plan")
def materialize_plan(project_ref: str, task_id: str, request: MaterializePlanRequest) -> dict[str, Any]:
    storage = _storage(project_ref)
    config = _config()
    task = storage.get_task(task_id)
    project_id = _project_id(project_ref, request.project_id)
    if task["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Task does not belong to project.")
    template = _resolved_workflow_template(config, storage, request.workflow_template_id, request.parameters)
    if workflow_materialize_action(template, task) is None:
        raise HTTPException(status_code=400, detail=f"Task is not a materialization source for workflow template `{template['id']}`.")
    runs = storage.list_task_runs(task_id=task_id, limit=20)
    run = next((item for item in runs if item["status"] == "succeeded" and item.get("stdout_path")), None)
    if run is None:
        raise HTTPException(status_code=400, detail="Plan task has no successful stdout run to materialize.")
    stdout_path = Path(str(run["stdout_path"]))
    _ensure_inside(stdout_path, storage.engine_dir)
    if not stdout_path.exists():
        raise HTTPException(status_code=400, detail="Plan task stdout log is missing.")
    review_stdout_path: Path | None = None
    dependency_ids = storage.list_task_dependencies(task_id)
    if dependency_ids:
        dependency_runs = storage.list_task_runs(task_id=dependency_ids[0], limit=20)
        dependency_run = next((item for item in dependency_runs if item["status"] == "succeeded" and item.get("stdout_path")), None)
        if dependency_run:
            review_stdout_path = stdout_path
            stdout_path = Path(str(dependency_run["stdout_path"]))
            _ensure_inside(stdout_path, storage.engine_dir)
            if not stdout_path.exists():
                raise HTTPException(status_code=400, detail="Reviewed plan task stdout log is missing.")
    task_spec = materialize_task_spec(template)
    profile = request.profile or str(task_spec.get("profile") or "")
    prompt_template_ref = _validate_prompt_template_ref(request.prompt_template_ref or str(task_spec.get("prompt_template_ref") or ""))
    if not profile:
        raise HTTPException(status_code=400, detail=f"Workflow template `{template['id']}` materialize task has no profile.")
    if not _prompt_template_exists(storage, config, prompt_template_ref):
        raise HTTPException(status_code=400, detail=f"Prompt template not found: {prompt_template_ref}")
    existing = storage.list_tasks(task["workflow_id"])
    created_reason = f"breakdown-from-plan:{task_id}"
    existing_task = next((item for item in existing if item.get("created_reason") == created_reason), None)
    if existing_task:
        return {"created": [], "skipped": [existing_task], "tasks": storage.list_tasks(task["workflow_id"])}
    workitem = storage.get_workitem(task["workitem_id"])
    prompt_text = request.prompt_text or render_materialize_prompt(
        template,
        {
            "project_root": str(storage.project_root),
            "project_id": project_id,
            "workitem_id": workitem["id"],
            "workitem_title": workitem["title"],
            "workflow_id": task["workflow_id"],
            "source_task_id": task["id"],
            "stdout_path": str(stdout_path),
            "review_stdout_path": str(review_stdout_path) if review_stdout_path else "无",
            "child_workflows": nested_workflows_text(template),
        },
    )
    created = storage.create_task(
        task["workflow_id"],
        str(task_spec.get("title") or "将 plan 物化为可执行任务"),
        kind=str(task_spec.get("kind") or "planning"),
        profile=profile,
        prompt_template_ref=prompt_template_ref,
        prompt_text=prompt_text,
        outputs=_string_list(task_spec.get("outputs")),
        gates=_string_list(task_spec.get("gates")),
        skills=_string_list(task_spec.get("skills"), default=["hwe"]),
        priority=task["priority"] + _int_value(task_spec.get("priority_offset"), 1),
        risk_level=task["risk_level"],
        created_by="hwe-api",
        created_reason=created_reason,
    )
    return {"created": [created], "skipped": [], "tasks": storage.list_tasks(task["workflow_id"])}


@app.post("/api/projects/{project_ref}/human-actions/{action_id}/answer")
def answer_human_action(project_ref: str, action_id: str, request: HumanActionResponseRequest) -> dict[str, Any]:
    response = request.response if request.response is not None else {"text": request.text}
    return _storage(project_ref).resolve_human_action(action_id, resolution="answered", response=response, resolved_by=request.by)


@app.post("/api/projects/{project_ref}/human-actions/{action_id}/approve")
def approve_human_action(project_ref: str, action_id: str, request: HumanActionResponseRequest) -> dict[str, Any]:
    response = request.response if request.response is not None else {"text": request.text}
    return _storage(project_ref).resolve_human_action(action_id, resolution="approved", response=response, resolved_by=request.by)


@app.post("/api/projects/{project_ref}/human-actions/{action_id}/reject")
def reject_human_action(project_ref: str, action_id: str, request: HumanActionRejectRequest) -> dict[str, Any]:
    return _storage(project_ref).resolve_human_action(action_id, resolution="rejected", response={"reason": request.reason}, resolved_by=request.by)


def _config() -> HWEConfig:
    try:
        return load_config()
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _storage(project_ref: str) -> ProjectStorage:
    try:
        config = _config()
        storage = ProjectStorage(resolve_project_root(project_ref, config), config=config)
        storage.initialize()
        return storage
    except ProjectStorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _run_hermes_session_id(storage: ProjectStorage, run: dict[str, Any]) -> str | None:
    result = run.get("result")
    if isinstance(result, dict):
        for key in ("hermes_session_id", "session_id"):
            value = result.get(key)
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]+", value):
                return value

    raw_path = run.get("stderr_path")
    if not raw_path:
        fallback_path = storage.engine_dir / "runs" / str(run["id"]) / "stderr.log"
        raw_path = str(fallback_path) if fallback_path.exists() else None
    if not raw_path:
        return None

    path = Path(str(raw_path))
    _ensure_inside(path, storage.engine_dir)
    if not path.exists():
        return None
    matches = HERMES_SESSION_ID_PATTERN.findall(path.read_text(encoding="utf-8", errors="replace"))
    return matches[-1] if matches else None


def _hermes_session_paths(session_id: str, *, profile: str | None = None) -> dict[str, list[Path]]:
    roots = _hermes_session_roots(profile)
    return {
        "jsonl": [path for root in roots for path in (root / f"{session_id}.jsonl", root / f"session_{session_id}.jsonl")],
        "json": [path for root in roots for path in (root / f"session_{session_id}.json", root / f"{session_id}.json")],
    }


def _hermes_session_roots(profile: str | None = None) -> list[Path]:
    hermes_root = Path.home() / ".hermes"
    roots: list[Path] = []

    def add(root: Path) -> None:
        if root not in roots:
            roots.append(root)

    add(hermes_root / "sessions")
    profiles_root = hermes_root / "profiles"
    if profile and re.fullmatch(r"[A-Za-z0-9_.-]+", profile):
        add(profiles_root / profile / "sessions")
    if profiles_root.exists():
        for profile_root in sorted(path for path in profiles_root.iterdir() if path.is_dir()):
            add(profile_root / "sessions")
    return roots


def _read_hermes_session_summary(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"path": str(path), "error": "unreadable_session_summary"}
    return {
        "path": str(path),
        "session_id": data.get("session_id"),
        "model": data.get("model"),
        "base_url": data.get("base_url"),
        "platform": data.get("platform"),
        "session_start": data.get("session_start"),
        "last_updated": data.get("last_updated"),
        "message_count": data.get("message_count") or (len(data.get("messages", [])) if isinstance(data.get("messages"), list) else None),
    }


def _read_hermes_session_events(path: Path, *, limit: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if len(events) >= limit:
                    break
                raw = line.strip()
                if not raw:
                    continue
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    events.append({"index": line_number, "role": "raw", "timestamp": None, "content": raw, "tool_calls": []})
                    continue
                events.append(_hermes_session_event(line_number, item))
    except OSError:
        return []
    return events


def _read_hermes_session_json_events(path: Path | None, *, limit: int) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    messages = data.get("messages")
    if not isinstance(messages, list):
        return []
    session_start = data.get("session_start") if isinstance(data.get("session_start"), str) else None
    last_updated = data.get("last_updated") if isinstance(data.get("last_updated"), str) else None
    message_items = [item for item in messages if isinstance(item, dict)]
    events: list[dict[str, Any]] = []
    total = len(message_items)
    for index, item in enumerate(message_items, start=1):
        if len(events) >= limit:
            break
        fallback_timestamp = _session_json_message_timestamp(index, total, session_start=session_start, last_updated=last_updated)
        events.append(_hermes_session_event(index, item, fallback_timestamp=fallback_timestamp))
    return events


def _session_json_message_timestamp(index: int, total: int, *, session_start: str | None, last_updated: str | None) -> str | None:
    if total <= 1:
        return last_updated or session_start
    if index == 1:
        return session_start
    if index == total:
        return last_updated or session_start
    return None


def _hermes_session_event(index: int, item: dict[str, Any], *, fallback_timestamp: str | None = None) -> dict[str, Any]:
    return {
        "index": index,
        "role": item.get("role") or item.get("type") or "unknown",
        "timestamp": item.get("timestamp") or fallback_timestamp,
        "content": _session_content_text(item.get("content")),
        "tool_call_id": item.get("tool_call_id"),
        "tool_calls": [_compact_tool_call(call) for call in item.get("tool_calls", []) if isinstance(call, dict)],
        "finish_reason": item.get("finish_reason"),
    }


def _session_content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _compact_tool_call(call: dict[str, Any]) -> dict[str, Any]:
    function = call.get("function") if isinstance(call.get("function"), dict) else {}
    return {
        "id": call.get("id") or call.get("call_id"),
        "type": call.get("type"),
        "name": function.get("name") or call.get("name"),
        "arguments": function.get("arguments") or call.get("arguments") or "",
    }


def _resolved_workflow_templates(config: HWEConfig, storage: ProjectStorage) -> list[dict[str, Any]]:
    try:
        return [resolve_workflow_template(template) for template in list_workflow_templates(config, project_root=storage.project_root)]
    except WorkflowTemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _resolved_workflow_template(config: HWEConfig, storage: ProjectStorage, template_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
    try:
        return resolve_workflow_template(get_workflow_template(config, template_id, project_root=storage.project_root), parameters)
    except WorkflowTemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _with_workflow_actions(task: dict[str, Any], templates: list[dict[str, Any]]) -> dict[str, Any]:
    actions: dict[str, Any] = {}
    for template in templates:
        action = workflow_materialize_action(template, task)
        if action:
            actions["materialize_plan"] = action
            break
    if not actions:
        return task
    return {**task, "workflow_actions": actions}


def _string_list(value: Any, *, default: list[str] | None = None) -> list[str]:
    if value is None:
        return list(default or [])
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ai_assist_context(config: HWEConfig, target: AssistTarget, raw_context: dict[str, Any]) -> dict[str, Any]:
    project_ref = raw_context.get("project_ref")
    if not isinstance(project_ref, str) or not project_ref.strip():
        return {}
    project_ref = project_ref.strip()
    if not PROJECT_REF_PATTERN.fullmatch(project_ref):
        raise HTTPException(status_code=400, detail="AI assist project_ref must be a safe project reference.")
    project_id_value = raw_context.get("project_id")
    project_id = project_id_value.strip() if isinstance(project_id_value, str) and project_id_value.strip() else None
    try:
        storage = ProjectStorage(resolve_project_root(project_ref, config), config=config)
        storage.initialize()
        resolved_project_id = _project_id(project_ref, project_id)
        project = storage.get_project(resolved_project_id)
        if target == "human_action":
            action_id = raw_context.get("action_id")
            if not isinstance(action_id, str) or not action_id.strip():
                return {}
            return _human_action_assist_context(storage, project, action_id.strip())
        if target != "workitem":
            return {}
        workitems = storage.list_workitems(resolved_project_id)
        return _workitem_assist_context(storage, project, workitems)
    except ProjectStorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _workitem_assist_context(storage: ProjectStorage, project: dict[str, Any], workitems: list[dict[str, Any]]) -> dict[str, Any]:
    summarized_workitems = []
    for item in workitems[:20]:
        summary = {
            "id": item["id"],
            "title": item["title"],
            "type": item["type"],
            "status": item["status"],
            "priority": item["priority"],
            "risk_level": item["risk_level"],
        }
        if item.get("requirements_md"):
            summary["requirements"] = _clip_context_text(item["requirements_md"])
        if item.get("constraints_md"):
            summary["constraints"] = _clip_context_text(item["constraints_md"])
        workflow_id = item.get("current_workflow_id")
        if workflow_id:
            tasks = storage.list_tasks(workflow_id, update_readiness=False)
            status_counts: dict[str, int] = {}
            for task in tasks:
                status_counts[task["status"]] = status_counts.get(task["status"], 0) + 1
            summary["current_workflow"] = {
                "id": workflow_id,
                "task_status_counts": status_counts,
                "tasks": [
                    {
                        "id": task["id"],
                        "title": task["title"],
                        "kind": task["kind"],
                        "profile": task.get("profile"),
                        "status": task["status"],
                    }
                    for task in tasks[:12]
                ],
            }
        summarized_workitems.append(summary)
    return {
        "project": {
            "id": project["id"],
            "name": project["name"],
            "status": project["status"],
        },
        "existing_workitems": summarized_workitems,
        "limits": {"workitems": 20, "tasks_per_workitem": 12, "text_chars": 600},
    }


def _human_action_assist_context(storage: ProjectStorage, project: dict[str, Any], action_id: str) -> dict[str, Any]:
    action = storage.get_human_action(action_id)
    if action["project_id"] != project["id"]:
        raise ProjectStorageError("Human action does not belong to project.")
    workitem = storage.get_workitem(action["workitem_id"]) if action.get("workitem_id") else None
    workflow_id = action.get("workflow_id") or (workitem or {}).get("current_workflow_id")
    tasks = storage.list_tasks(workflow_id, update_readiness=False) if workflow_id else []
    task_runs = storage.list_task_runs(workflow_id=workflow_id, limit=20) if workflow_id else []
    events = storage.list_events(project["id"], limit=30)
    return {
        "project": {
            "id": project["id"],
            "name": project["name"],
            "status": project["status"],
        },
        "workitem": _summarize_workitem_for_assist(workitem) if workitem else None,
        "human_action": {
            "id": action["id"],
            "kind": action["kind"],
            "status": action["status"],
            "title": action["title"],
            "body": _clip_context_text(action.get("body"), 1200),
            "questions": action.get("questions", []),
            "options": action.get("options", []),
            "evidence": action.get("evidence", []),
            "requested_by": action.get("requested_by"),
            "task_id": action.get("task_id"),
            "run_id": action.get("run_id"),
        },
        "workflow": {
            "id": workflow_id,
            "tasks": [
                {
                    "id": task["id"],
                    "title": task["title"],
                    "kind": task["kind"],
                    "profile": task.get("profile"),
                    "status": task["status"],
                    "prompt_template_ref": task.get("prompt_template_ref"),
                    "prompt_text": _clip_context_text(task.get("prompt_text"), 500) if task.get("prompt_text") else "",
                }
                for task in tasks[:20]
            ],
            "task_runs": [
                {
                    "id": run["id"],
                    "task_id": run["task_id"],
                    "status": run["status"],
                    "profile": run.get("profile"),
                    "started_at": run.get("started_at"),
                    "ended_at": run.get("ended_at"),
                    "stdout_path": run.get("stdout_path"),
                    "stderr_path": run.get("stderr_path"),
                    "prompt_path": run.get("prompt_path"),
                }
                for run in task_runs[:12]
            ],
        },
        "recent_events": [
            {
                "id": event["id"],
                "type": event["type"],
                "task_id": event.get("task_id"),
                "run_id": event.get("run_id"),
                "human_action_id": event.get("human_action_id"),
                "created_at": event.get("created_at"),
                "payload": event.get("payload", {}),
            }
            for event in events[:30]
        ],
        "limits": {"tasks": 20, "task_runs": 12, "events": 30, "text_chars": 1200},
    }


def _summarize_workitem_for_assist(workitem: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": workitem["id"],
        "title": workitem["title"],
        "type": workitem["type"],
        "status": workitem["status"],
        "priority": workitem["priority"],
        "risk_level": workitem["risk_level"],
        "requirements": _clip_context_text(workitem.get("requirements_md"), 1200) if workitem.get("requirements_md") else "",
        "constraints": _clip_context_text(workitem.get("constraints_md"), 1200) if workitem.get("constraints_md") else "",
        "current_workflow_id": workitem.get("current_workflow_id"),
    }


def _clip_context_text(value: Any, limit: int = 600) -> str:
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _project_id(project_ref: str, project_id: str | None) -> str:
    return project_id or Path(project_ref).expanduser().name


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(".-_").lower()
    return slug or "project"


def _template_library_body(config: HWEConfig, role: str, name: str) -> str:
    path = _public_template_root(config) / role / f"{name}.md"
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"Missing prompt template library file: {path}")
    return path.read_text(encoding="utf-8")


def _public_template_root(config: HWEConfig) -> Path:
    if config.prompt_template_root is None:
        raise HTTPException(status_code=400, detail="Prompt template operations require HWE config `prompt_template_root`.")
    return config.prompt_template_root


def _project_template_root(project_root: Path) -> Path:
    return project_root / ".engine" / "prompt-templates"


def _validate_template_ref(role: str, name: str) -> tuple[str, str]:
    role = role.strip()
    name = name.strip().removesuffix(".md")
    if not PROJECT_REF_PATTERN.fullmatch(role) or not PROJECT_REF_PATTERN.fullmatch(name):
        raise HTTPException(status_code=400, detail="Prompt template role and name must be single safe path segments.")
    return role, name


def _validate_prompt_template_ref(prompt_template_ref: str) -> str:
    safe_ref = prompt_template_ref.strip().removesuffix(".md")
    parts = safe_ref.split("/")
    if len(parts) != 2 or not all(PROJECT_REF_PATTERN.fullmatch(part) for part in parts):
        raise HTTPException(status_code=400, detail="Prompt template ref must look like role/name with safe path segments.")
    return safe_ref


def _prompt_template_exists(storage: ProjectStorage, config: HWEConfig, prompt_template_ref: str) -> bool:
    relative_path = Path(prompt_template_ref).with_suffix(".md")
    candidates = [
        storage.engine_dir / "prompt-templates" / relative_path,
        config.prompt_template_root / relative_path if config.prompt_template_root else None,
    ]
    return any(candidate.exists() for candidate in candidates if candidate is not None)


def _list_file_prompt_templates(root: Path, *, source: str, role: str | None = None) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    records = []
    role_dirs = [root / role] if role else sorted(path for path in root.iterdir() if path.is_dir())
    for role_dir in role_dirs:
        if not role_dir.exists() or not role_dir.is_dir():
            continue
        template_role = role_dir.name
        for template_path in sorted(role_dir.glob("*.md")):
            _ensure_inside(template_path, root)
            name = template_path.stem
            records.append(_file_prompt_template_record(source=source, role=template_role, name=name, path=template_path))
    return records


def _write_file_prompt_template(root: Path, *, source: str, role: str, name: str, body: str) -> dict[str, Any]:
    path = root / role / f"{name}.md"
    _ensure_inside(path, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return _file_prompt_template_record(source=source, role=role, name=name, path=path)


def _delete_file_prompt_template(root: Path, *, source: str, role: str, name: str) -> dict[str, Any]:
    path = root / role / f"{name}.md"
    _ensure_inside(path, root)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Prompt template not found: {role}/{name}")
    path.unlink()
    return {"deleted": True, "source": source, "role": role, "name": name, "path": str(path)}


def _file_prompt_template_record(*, source: str, role: str, name: str, path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "id": f"{source}:{role}/{name}",
        "source": source,
        "role": role,
        "name": name,
        "version": "file",
        "description": "",
        "body_md": path.read_text(encoding="utf-8"),
        "tags": [],
        "path": str(path),
        "updated_at": stat.st_mtime,
    }


def _ensure_inside(path: Path, parent: Path) -> None:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Run log path is outside the project engine directory.") from exc

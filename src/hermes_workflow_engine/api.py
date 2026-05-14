from __future__ import annotations

from dataclasses import asdict
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


PROJECT_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
LOCAL_CORS_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(?::\d{1,5})?$"


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
    planner_profile: str = "designer"
    prompt_template_ref: str = "designer/workitem-plan"


class MaterializePlanRequest(BaseModel):
    project_id: str | None = None
    profile: str = "designer"
    prompt_template_ref: str = "designer/task-breakdown"
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
def list_workitems(project_ref: str, project_id: str | None = None) -> list[dict[str, Any]]:
    storage = _storage(project_ref)
    return storage.list_workitems(_project_id(project_ref, project_id))


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


@app.get("/api/projects/{project_ref}/workitems/{workitem_id}/dashboard")
def workitem_dashboard(project_ref: str, workitem_id: str, project_id: str | None = None) -> dict[str, Any]:
    storage = _storage(project_ref)
    resolved_project_id = _project_id(project_ref, project_id)
    workitem = storage.get_workitem(workitem_id)
    if workitem["project_id"] != resolved_project_id:
        raise HTTPException(status_code=404, detail="Workitem does not belong to project.")
    workflows = storage.list_workflows(resolved_project_id, workitem_id=workitem_id)
    current_workflow = storage.get_workflow(workitem["current_workflow_id"]) if workitem.get("current_workflow_id") else None
    tasks = storage.list_tasks(current_workflow["id"]) if current_workflow else []
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
    prompt_template_ref = _validate_prompt_template_ref(request.prompt_template_ref)
    if not _prompt_template_exists(storage, config, prompt_template_ref):
        raise HTTPException(status_code=400, detail=f"Prompt template not found: {prompt_template_ref}")
    workflow = storage.get_workflow(workitem["current_workflow_id"]) if workitem.get("current_workflow_id") else storage.create_workflow(project_id, workitem_id, planner_profile=request.planner_profile)
    tasks = storage.list_tasks(workflow["id"])
    planner_task = next((task for task in tasks if task.get("prompt_template_ref") == prompt_template_ref), None)
    if planner_task is None:
        planner_task = storage.create_task(
            workflow["id"],
            "规划 workitem",
            kind="planning",
            profile=request.planner_profile,
            prompt_template_ref=prompt_template_ref,
            prompt_text="为这个 workitem 制定执行策略，并提出后续 task-breakdown 可物化的任务候选。不要在本 planning 任务中直接创建实现/评审任务。",
            skills=["hwe"],
            outputs=["工作流计划", "任务图候选"],
            gates=["计划覆盖需求", "任务候选包含角色和依赖", "包含验证任务建议"],
            priority=10,
            risk_level=workitem["risk_level"],
            created_by="hwe-api",
            created_reason="plan-workitem",
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
    runs = storage.list_task_runs(task_id=task_id, limit=20)
    run = next((item for item in runs if item["status"] == "succeeded" and item.get("stdout_path")), None)
    if run is None:
        raise HTTPException(status_code=400, detail="Plan task has no successful stdout run to materialize.")
    stdout_path = Path(str(run["stdout_path"]))
    _ensure_inside(stdout_path, storage.engine_dir)
    if not stdout_path.exists():
        raise HTTPException(status_code=400, detail="Plan task stdout log is missing.")
    prompt_template_ref = _validate_prompt_template_ref(request.prompt_template_ref)
    if not _prompt_template_exists(storage, config, prompt_template_ref):
        raise HTTPException(status_code=400, detail=f"Prompt template not found: {prompt_template_ref}")
    existing = storage.list_tasks(task["workflow_id"])
    created_reason = f"breakdown-from-plan:{task_id}"
    existing_task = next((item for item in existing if item.get("created_reason") == created_reason), None)
    if existing_task:
        return {"created": [], "skipped": [existing_task], "tasks": storage.list_tasks(task["workflow_id"])}
    workitem = storage.get_workitem(task["workitem_id"])
    created = storage.create_task(
        task["workflow_id"],
        "将 plan 物化为可执行任务",
        kind="planning",
        profile=request.profile,
        prompt_template_ref=prompt_template_ref,
        prompt_text=request.prompt_text or _plan_breakdown_prompt(storage.project_root, project_id, workitem, task, stdout_path),
        outputs=["已创建 HWE 任务图"],
        gates=["已阅读 plan/design 文件", "任务使用正确角色和依赖创建", "包含验证任务建议"],
        skills=["hwe"],
        priority=task["priority"] + 1,
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


def _ai_assist_context(config: HWEConfig, target: AssistTarget, raw_context: dict[str, Any]) -> dict[str, Any]:
    if target != "workitem":
        return {}
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


def _plan_breakdown_prompt(project_root: Path, project_id: str, workitem: dict[str, Any], plan_task: dict[str, Any], stdout_path: Path) -> str:
    return "\n".join(
        [
            "读取已完成的 workitem plan/design 文件，并将其拆解为可执行的 HWE Task 记录。",
            "",
            f"项目根目录：{project_root}",
            f"Project id：{project_id}",
            f"Workitem id：{workitem['id']}",
            f"Workitem 标题：{workitem['title']}",
            f"Workflow id：{plan_task['workflow_id']}",
            f"源 planning/design task id：{plan_task['id']}",
            f"Plan stdout 路径：{stdout_path}",
            "",
            "以 plan/design 文件为事实来源，不要只根据本 prompt 摘要推断任务。",
            "从 workflow-engine 环境运行 `hwe task create` 创建聚焦的 HWE 任务。",
            "先验证 HWE config 中实际存在的 profiles；只把任务分配给真实可路由、技能和模板可用的 profile。",
            "为每一步选择合适的 prompt template；必要时创建项目本地 override 到 `.engine/prompt-templates/<role>/<name>.md`。",
            "保留 plan/design 中的依赖关系，加入能证明完成的 gates/outputs。",
            "如果 plan/design 文件信息不足以安全创建任务，请请求 human action，不要猜测。",
        ]
    )


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

from __future__ import annotations

import os
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import HWEConfig, load_config
from .project_runtime import ProjectRuntime
from .project_storage import ProjectStorage, ProjectStorageError, resolve_project_root


@dataclass(frozen=True)
class ProjectWorkerRunSummary:
    requests_claimed: int
    requests_succeeded: int
    requests_failed: int
    requests_waiting_for_human: int
    requests_cancelled: int


class ProjectWorker:
    def __init__(self, *, config: HWEConfig | None = None, worker_id: str | None = None, profile: str | None = None):
        self.config = load_config() if config is None else config
        self.worker_id = worker_id or f"hwe-worker-{os.getpid()}"
        self.profile = profile

    def run_once(self, *, project_ref: str | None = None, max_requests: int | None = None) -> ProjectWorkerRunSummary:
        claimed = 0
        succeeded = 0
        failed = 0
        waiting = 0
        cancelled = 0
        for storage, project_id in self._storages(project_ref):
            while max_requests is None or claimed < max_requests:
                request = storage.claim_next_run_request(worker_id=self.worker_id, profile=self.profile, project_id=project_id)
                if request is None:
                    break
                claimed += 1
                status = self._execute_request(storage, request)
                if status == "succeeded":
                    succeeded += 1
                elif status == "waiting_for_human":
                    waiting += 1
                elif status == "cancelled":
                    cancelled += 1
                else:
                    failed += 1
            if max_requests is not None and claimed >= max_requests:
                break
        return ProjectWorkerRunSummary(claimed, succeeded, failed, waiting, cancelled)

    def run_forever(self, *, project_ref: str | None = None, poll_interval_seconds: float = 2.0) -> None:
        while True:
            summary = self.run_once(project_ref=project_ref, max_requests=1)
            if summary.requests_claimed == 0:
                time.sleep(poll_interval_seconds)

    def _execute_request(self, storage: ProjectStorage, request: dict[str, Any]) -> str:
        runtime = ProjectRuntime(storage, dry_run=bool(request.get("dry_run")), config=self.config)
        try:
            if request["kind"] == "task":
                summary = runtime.run_one_task(
                    request["project_id"],
                    request["task_id"],
                    worker_id=self.worker_id,
                    profile=request.get("profile") or self.profile,
                )
            elif request["kind"] == "post_execution":
                result = runtime.run_post_execution(request, worker_id=self.worker_id)
                status = result.get("status")
                if status in {"waiting_for_info", "waiting_for_approval"}:
                    request_status = "waiting_for_human"
                elif status == "succeeded":
                    request_status = "succeeded"
                elif status == "cancelled":
                    request_status = "cancelled"
                else:
                    request_status = "failed"
                storage.complete_run_request(request["id"], status=request_status, result=result)
                if request_status == "succeeded":
                    _enqueue_post_execution_continuation(storage, request, worker_id=self.worker_id)
                return request_status
            else:
                summary = runtime.run_workitem(
                    request["project_id"],
                    request["workitem_id"],
                    worker_id=self.worker_id,
                    profile=request.get("profile") or self.profile,
                    max_tasks=request.get("max_tasks"),
                )
            result = summary.__dict__
            if summary.tasks_failed:
                status = "failed"
            elif summary.waiting_for_human:
                status = "waiting_for_human"
            else:
                status = "succeeded"
            storage.complete_run_request(request["id"], status=status, result=result)
            return status
        except (KeyboardInterrupt, SystemExit) as exc:
            storage.complete_run_request(
                request["id"],
                status="cancelled",
                result={"error": "worker_interrupted", "type": type(exc).__name__, "message": str(exc)},
                error=str(exc),
            )
            raise
        except (ProjectStorageError, RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
            storage.complete_run_request(
                request["id"],
                status="failed",
                result={"error": "worker_exception", "type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()},
                error=str(exc),
            )
            return "failed"

    def _storages(self, project_ref: str | None = None) -> Iterable[tuple[ProjectStorage, str | None]]:
        if project_ref:
            storage = ProjectStorage(resolve_project_root(project_ref, self.config), config=self.config)
            project_id = _project_id_for_storage(storage, project_ref)
            yield storage, project_id
            return

        if (self.config.project_database or {}).get("backend") == "postgres":
            root = self.config.default_workspace_root or Path.cwd()
            index_storage = ProjectStorage(root, config=self.config)
            for project in index_storage.list_projects(include_archived=False):
                yield ProjectStorage(Path(project["root_path"]), config=self.config), project["id"]
            return

        if not self.config.default_workspace_root or not self.config.default_workspace_root.exists():
            return
        for engine_db in sorted(self.config.default_workspace_root.glob("*/.engine/engine.db")):
            storage = ProjectStorage(engine_db.parents[1], config=self.config)
            for project in storage.list_projects(include_archived=False):
                yield storage, project["id"]


def _project_id_for_storage(storage: ProjectStorage, project_ref: str) -> str | None:
    try:
        project = storage.get_project(Path(project_ref).expanduser().name)
        return project["id"]
    except ProjectStorageError:
        projects = storage.list_projects(include_archived=False)
        if len(projects) == 1:
            return projects[0]["id"]
        return None

def _enqueue_post_execution_continuation(storage: ProjectStorage, request: dict[str, Any], *, worker_id: str) -> dict[str, Any] | None:
    context = request.get("result") if isinstance(request.get("result"), dict) else {}
    if context.get("source_status") not in {"succeeded", "skipped", "superseded"}:
        return None
    workflow_id = request["workflow_id"]
    storage.mark_ready_tasks(workflow_id)
    ready_tasks = [task for task in storage.list_tasks(workflow_id) if task["status"] == "ready"]
    if not ready_tasks:
        return None
    existing = storage.list_run_requests(project_id=request["project_id"], workitem_id=request["workitem_id"], status="queued", limit=200)
    if any(item["kind"] in {"workitem", "task"} for item in existing):
        return None
    continuation = storage.enqueue_run_request(
        request["project_id"],
        request["workitem_id"],
        kind="workitem",
        requested_worker_id=worker_id,
        max_tasks=1,
        dry_run=bool(request.get("dry_run")),
    )
    storage.event(
        request["project_id"],
        request["workitem_id"],
        workflow_id,
        request.get("task_id"),
        "task_post_execution_continuation_queued",
        {"request_id": continuation["id"], "source_request_id": request["id"], "ready_task_ids": [task["id"] for task in ready_tasks]},
    )
    return continuation

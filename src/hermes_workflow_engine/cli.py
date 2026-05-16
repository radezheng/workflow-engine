from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config import ConfigError, HWEConfig, configured_config_path, load_config, write_config
from .doctor import Doctor
from .project_worker import ProjectWorker
from .runtime import WorkflowRuntime
from .spec import SpecError, load_workflow
from .storage import Storage
from .project_storage import ProjectStorage, ProjectStorageError, resolve_project_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hwe", description="Hermes Workflow Engine local CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Parse a workflow spec and initialize SQLite state.")
    validate_parser.add_argument("workflow")

    run_parser = subparsers.add_parser("run", help="Run ready workflow steps serially.")
    run_parser.add_argument("workflow")
    run_parser.add_argument("--dry-run", action="store_true", help="Do not launch Hermes for agent steps.")
    run_parser.add_argument("--max-steps", type=int, default=None, help="Stop after running at most N steps.")
    run_parser.add_argument("--reset", action="store_true", help="Reset step states before running.")

    status_parser = subparsers.add_parser("status", help="Show current step states.")
    status_parser.add_argument("workflow")

    events_parser = subparsers.add_parser("events", help="Show recent workflow events as JSON lines.")
    events_parser.add_argument("workflow")
    events_parser.add_argument("--limit", type=int, default=50)

    serve_parser = subparsers.add_parser("serve", help="Run the HWE FastAPI server for the local UI.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8711)
    serve_parser.add_argument("--reload", action="store_true")

    doctor_parser = subparsers.add_parser("doctor", help="Check HWE repo, config, project database, profiles, and local services.")
    doctor_parser.add_argument("--repo", type=Path, default=None)
    doctor_parser.add_argument("--config", type=Path, default=None)
    doctor_parser.add_argument("--fix", action="store_true", help="Apply safe local fixes such as creating configured directories.")

    run_workitem_parser = subparsers.add_parser("run-workitem", help="Run ready tasks for a project work item.")
    run_workitem_parser.add_argument("project")
    run_workitem_parser.add_argument("workitem_id")
    run_workitem_parser.add_argument("--project-id", default=None)
    run_workitem_parser.add_argument("--worker-id", default="hwe-runner")
    run_workitem_parser.add_argument("--profile", default=None)
    run_workitem_parser.add_argument("--max-tasks", type=int, default=None)
    run_workitem_parser.add_argument("--dry-run", action="store_true")
    run_workitem_parser.add_argument("--api-url", default=None, help="HWE API base URL. Defaults to HWE_API_URL or http://127.0.0.1:8711.")
    run_workitem_parser.add_argument("--local", action="store_true", help="Bypass the API and enqueue directly into project storage.")

    worker_parser = subparsers.add_parser("worker", help="Run the HWE project worker that consumes queued run requests.")
    worker_parser.add_argument("project", nargs="?", default=None, help="Optional project name/path/ref. Omit to process all discoverable projects.")
    worker_parser.add_argument("--worker-id", default=None)
    worker_parser.add_argument("--profile", default=None)
    worker_parser.add_argument("--once", action="store_true", help="Process currently queued requests once and exit.")
    worker_parser.add_argument("--max-requests", type=int, default=1, help="Maximum requests to process with --once.")
    worker_parser.add_argument("--poll-interval", type=float, default=2.0)

    config_parser = subparsers.add_parser("config", help="Manage HWE local configuration.")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    config_subparsers.add_parser("path", help="Print the active HWE config path.")
    config_subparsers.add_parser("show", help="Print the active HWE config as JSON.")
    config_init = config_subparsers.add_parser("init", help="Create an HWE config file.")
    config_init.add_argument("--default-workspace-root", default="~/workspaces/hermes")
    config_init.add_argument("--prompt-template-root", default="./ptemplate")
    config_init.add_argument("--force", action="store_true", help="Overwrite an existing config file.")

    project_parser = subparsers.add_parser("project", help="Manage projects.")
    project_subparsers = project_parser.add_subparsers(dest="project_command", required=True)
    project_init = project_subparsers.add_parser("init", help="Initialize state for a project.")
    project_init.add_argument("project", help="Project name under default_workspace_root or an explicit path.")
    project_init.add_argument("--id", dest="project_id", default=None)
    project_init.add_argument("--name", default=None)
    project_show = project_subparsers.add_parser("show", help="Show a project record.")
    project_show.add_argument("project")
    project_show.add_argument("--id", dest="project_id", default=None)
    project_archive = project_subparsers.add_parser("archive", help="Archive a project without deleting its state.")
    project_archive.add_argument("project")
    project_archive.add_argument("--id", dest="project_id", default=None)
    project_restore = project_subparsers.add_parser("restore", help="Restore an archived project.")
    project_restore.add_argument("project")
    project_restore.add_argument("--id", dest="project_id", default=None)
    project_events = project_subparsers.add_parser("events", help="Show project events as JSON lines.")
    project_events.add_argument("project")
    project_events.add_argument("--id", dest="project_id", default=None)
    project_events.add_argument("--limit", type=int, default=50)

    workitem_parser = subparsers.add_parser("workitem", help="Manage work items.")
    workitem_subparsers = workitem_parser.add_subparsers(dest="workitem_command", required=True)
    workitem_create = workitem_subparsers.add_parser("create", help="Create a work item.")
    workitem_create.add_argument("project")
    workitem_create.add_argument("title")
    workitem_create.add_argument("--project-id", default=None)
    workitem_create.add_argument("--type", default="feature")
    workitem_create.add_argument("--requirements", default="")
    workitem_create.add_argument("--constraints", default="")
    workitem_create.add_argument("--acceptance", action="append", default=[])
    workitem_create.add_argument("--priority", type=int, default=100)
    workitem_create.add_argument("--risk-level", default="medium")
    workitem_list = workitem_subparsers.add_parser("list", help="List work items.")
    workitem_list.add_argument("project")
    workitem_list.add_argument("--project-id", default=None)

    workflow_parser = subparsers.add_parser("workflow", help="Manage workflows.")
    workflow_subparsers = workflow_parser.add_subparsers(dest="workflow_command", required=True)
    workflow_create = workflow_subparsers.add_parser("create", help="Create a workflow for a work item.")
    workflow_create.add_argument("project")
    workflow_create.add_argument("workitem_id")
    workflow_create.add_argument("--project-id", default=None)
    workflow_create.add_argument("--planner-profile", default=None)

    task_parser = subparsers.add_parser("task", help="Manage tasks.")
    task_subparsers = task_parser.add_subparsers(dest="task_command", required=True)
    task_create = task_subparsers.add_parser("create", help="Create a task in a workflow.")
    task_create.add_argument("project")
    task_create.add_argument("workflow_id")
    task_create.add_argument("title")
    task_create.add_argument("--kind", required=True)
    task_create.add_argument("--profile", default=None)
    task_create.add_argument("--depends-on", action="append", default=[])
    task_create.add_argument("--skill", action="append", default=[])
    task_create.add_argument("--prompt-template-ref", default=None, help="File template ref such as reviewer/implementation-review.")
    task_create.add_argument("--output", action="append", default=[])
    task_create.add_argument("--gate", action="append", default=[])
    task_create.add_argument("--prompt-text", default=None)
    task_create.add_argument("--priority", type=int, default=100)
    task_create.add_argument("--risk-level", default="medium")
    task_create.add_argument("--created-by", default=None)
    task_create.add_argument("--created-reason", default=None)
    task_list = task_subparsers.add_parser("list", help="List tasks in a workflow.")
    task_list.add_argument("project")
    task_list.add_argument("workflow_id")
    task_claim = task_subparsers.add_parser("claim", help="Start the next ready task and mark it running.")
    task_claim.add_argument("project")
    task_claim.add_argument("workflow_id")
    task_claim.add_argument("--worker-id", required=True)
    task_claim.add_argument("--profile", default=None)
    task_claim.add_argument("--lease-seconds", type=int, default=900)
    task_release = task_subparsers.add_parser("release", help="Release an abandoned running task back to ready.")
    task_release.add_argument("project")
    task_release.add_argument("task_id")
    task_release.add_argument("--reason", default="released")
    task_reassign = task_subparsers.add_parser("reassign", help="Change the profile for a pending or ready task while preserving run history.")
    task_reassign.add_argument("project")
    task_reassign.add_argument("task_id")
    task_reassign.add_argument("--profile", default=None)
    task_reassign.add_argument("--reason", default="reassigned")
    task_retry = task_subparsers.add_parser("retry", help="Retry a failed or cancelled task by returning it to ready.")
    task_retry.add_argument("project")
    task_retry.add_argument("task_id")
    task_retry.add_argument("--reason", default="retry")
    task_complete = task_subparsers.add_parser("complete", help="Complete a running task.")
    task_complete.add_argument("project")
    task_complete.add_argument("task_id")
    task_complete.add_argument("--status", default="succeeded", choices=["succeeded", "failed", "cancelled", "skipped", "superseded", "waiting_for_info", "waiting_for_approval"])
    task_complete.add_argument("--result-json", default=None)
    task_complete.add_argument("--title", default=None, help="Human action title when status waits for information or approval.")
    task_complete.add_argument("--body", default=None, help="Human action body when status waits for information or approval.")
    task_complete.add_argument("--question", action="append", default=[])
    task_complete.add_argument("--option", action="append", default=[])
    task_complete.add_argument("--evidence", action="append", default=[])
    task_complete.add_argument("--requested-by", default=None)

    human_action_parser = subparsers.add_parser("human-action", help="Manage pending human information and approval requests.")
    human_action_subparsers = human_action_parser.add_subparsers(dest="human_action_command", required=True)
    human_action_list = human_action_subparsers.add_parser("list", help="List human actions for a project.")
    human_action_list.add_argument("project")
    human_action_list.add_argument("--project-id", default=None)
    human_action_list.add_argument("--status", default=None)
    human_action_list.add_argument("--kind", default=None, choices=["info_request", "approval_request"])
    human_action_create = human_action_subparsers.add_parser("create", help="Create a human information or approval request.")
    human_action_create.add_argument("project")
    human_action_create.add_argument("title")
    human_action_create.add_argument("--project-id", default=None)
    human_action_create.add_argument("--kind", default="info_request", choices=["info_request", "approval_request"])
    human_action_create.add_argument("--body", required=True)
    human_action_create.add_argument("--workitem-id", default=None)
    human_action_create.add_argument("--workflow-id", default=None)
    human_action_create.add_argument("--task-id", default=None)
    human_action_create.add_argument("--run-id", default=None)
    human_action_create.add_argument("--conversation-id", default=None)
    human_action_create.add_argument("--question", action="append", default=[])
    human_action_create.add_argument("--option", action="append", default=[])
    human_action_create.add_argument("--evidence", action="append", default=[])
    human_action_create.add_argument("--requested-by", default=None)
    human_action_show = human_action_subparsers.add_parser("show", help="Show a human action.")
    human_action_show.add_argument("project")
    human_action_show.add_argument("human_action_id")
    human_action_show.add_argument("--project-id", default=None)
    human_action_answer = human_action_subparsers.add_parser("answer", help="Answer an information request.")
    human_action_answer.add_argument("project")
    human_action_answer.add_argument("human_action_id")
    human_action_answer.add_argument("--project-id", default=None)
    human_action_answer.add_argument("--text", required=True)
    human_action_answer.add_argument("--by", dest="resolved_by", default=None)
    human_action_approve = human_action_subparsers.add_parser("approve", help="Approve an approval request.")
    human_action_approve.add_argument("project")
    human_action_approve.add_argument("human_action_id")
    human_action_approve.add_argument("--project-id", default=None)
    human_action_approve.add_argument("--text", default="")
    human_action_approve.add_argument("--by", dest="resolved_by", default=None)
    human_action_reject = human_action_subparsers.add_parser("reject", help="Reject a human action.")
    human_action_reject.add_argument("project")
    human_action_reject.add_argument("human_action_id")
    human_action_reject.add_argument("--project-id", default=None)
    human_action_reject.add_argument("--reason", required=True)
    human_action_reject.add_argument("--by", dest="resolved_by", default=None)

    answer_parser = subparsers.add_parser("answer", help="Answer an information request.")
    answer_parser.add_argument("project")
    answer_parser.add_argument("human_action_id")
    answer_parser.add_argument("--project-id", default=None)
    answer_parser.add_argument("--text", required=True)
    answer_parser.add_argument("--by", dest="resolved_by", default=None)
    answer_parser.set_defaults(human_action_command="answer")
    approve_parser = subparsers.add_parser("approve", help="Approve an approval request.")
    approve_parser.add_argument("project")
    approve_parser.add_argument("human_action_id")
    approve_parser.add_argument("--project-id", default=None)
    approve_parser.add_argument("--text", default="")
    approve_parser.add_argument("--by", dest="resolved_by", default=None)
    approve_parser.set_defaults(human_action_command="approve")
    reject_parser = subparsers.add_parser("reject", help="Reject a human action.")
    reject_parser.add_argument("project")
    reject_parser.add_argument("human_action_id")
    reject_parser.add_argument("--project-id", default=None)
    reject_parser.add_argument("--reason", required=True)
    reject_parser.add_argument("--by", dest="resolved_by", default=None)
    reject_parser.set_defaults(human_action_command="reject")

    args = parser.parse_args(argv)

    try:
        if args.command == "config":
            return _handle_config(args)
        if args.command == "project":
            return _handle_project(args)
        if args.command == "workitem":
            return _handle_workitem(args)
        if args.command == "workflow":
            return _handle_workflow(args)
        if args.command == "task":
            return _handle_task(args)
        if args.command in {"human-action", "answer", "approve", "reject"}:
            return _handle_human_action(args)
        if args.command == "run-workitem":
            return _handle_run_workitem(args)
        if args.command == "worker":
            return _handle_worker(args)
        if args.command == "serve":
            return _handle_serve(args)
        if args.command == "doctor":
            return _handle_doctor(args)

        spec = load_workflow(args.workflow)
        storage = Storage(spec.engine_dir)
        if args.command == "validate":
            runtime = WorkflowRuntime(spec, storage, dry_run=True)
            runtime.load()
            print(f"valid workflow: {spec.id}")
            print(f"workspace_root: {spec.workspace_root}")
            if spec.project:
                print(f"project: {spec.project}")
            print(f"project_workspace: {spec.workspace}")
            print(f"engine: {spec.engine_dir}")
            print(f"steps: {len(spec.steps)}")
            return 0
        if args.command == "run":
            runtime = WorkflowRuntime(spec, storage, dry_run=args.dry_run)
            runtime.load()
            if args.reset:
                storage.reset_workflow(spec.id)
            summary = runtime.run(max_steps=args.max_steps)
            print(json.dumps(summary.__dict__, indent=2, sort_keys=True))
            return 1 if summary.steps_failed else 0
        if args.command == "status":
            storage.initialize()
            storage.upsert_workflow(spec)
            _print_status(storage, spec.id)
            return 0
        if args.command == "events":
            storage.initialize()
            for event in storage.list_events(spec.id, args.limit):
                print(json.dumps(event, sort_keys=True))
            return 0
        return 2
    except SpecError as exc:
        print(f"spec error: {exc}", file=sys.stderr)
        return 2
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    except ProjectStorageError as exc:
        print(f"project error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("canceled", file=sys.stderr)
        return 130


def _print_status(storage: Storage, workflow_id: str) -> None:
    rows = storage.list_steps(workflow_id)
    if not rows:
        print("No steps recorded. Run `hwe validate workflow.yaml` first.")
        return
    width = max(len(row["id"]) for row in rows)
    for row in rows:
        profile = row["profile"] or ""
        print(f"{row['id']:<{width}}  {row['state']:<18} attempt={row['attempt']} kind={row['kind']} profile={profile}")


def _handle_config(args: argparse.Namespace) -> int:
    if args.config_command == "path":
        print(configured_config_path())
        return 0
    if args.config_command == "show":
        config = load_config()
        payload = {
            "path": str(config.source_path) if config.source_path else None,
            "exists": bool(config.source_path and config.source_path.exists()),
            "default_workspace_root": str(config.default_workspace_root) if config.default_workspace_root else None,
            "prompt_template_root": str(config.prompt_template_root) if config.prompt_template_root else None,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.config_command == "init":
        config = HWEConfig(
            default_workspace_root=Path(args.default_workspace_root).expanduser(),
            prompt_template_root=Path(args.prompt_template_root).expanduser(),
        )
        path = write_config(config, force=args.force)
        print(f"created HWE config: {path}")
        return 0
    return 2


def _handle_project(args: argparse.Namespace) -> int:
    storage = _project_storage(args.project)
    project_id = args.project_id or Path(args.project).expanduser().name
    if args.project_command == "init":
        name = args.name or project_id
        _print_json(storage.upsert_project(name, project_id=project_id))
        return 0
    if args.project_command == "show":
        _print_json(storage.get_project(project_id))
        return 0
    if args.project_command == "archive":
        _print_json(storage.archive_project(project_id))
        return 0
    if args.project_command == "restore":
        _print_json(storage.restore_project(project_id))
        return 0
    if args.project_command == "events":
        for event in storage.list_events(project_id, limit=args.limit):
            print(json.dumps(event, sort_keys=True))
        return 0
    return 2


def _handle_workitem(args: argparse.Namespace) -> int:
    storage = _project_storage(args.project)
    project_id = args.project_id or Path(args.project).expanduser().name
    if args.workitem_command == "create":
        _ensure_project(storage, project_id)
        _print_json(
            storage.create_workitem(
                project_id,
                args.title,
                workitem_type=args.type,
                requirements=args.requirements,
                constraints=args.constraints,
                acceptance=args.acceptance,
                priority=args.priority,
                risk_level=args.risk_level,
            )
        )
        return 0
    if args.workitem_command == "list":
        _print_json(storage.list_workitems(project_id))
        return 0
    return 2


def _handle_workflow(args: argparse.Namespace) -> int:
    storage = _project_storage(args.project)
    project_id = args.project_id or Path(args.project).expanduser().name
    if args.workflow_command == "create":
        _print_json(storage.create_workflow(project_id, args.workitem_id, planner_profile=args.planner_profile))
        return 0
    return 2


def _handle_task(args: argparse.Namespace) -> int:
    storage = _project_storage(args.project)
    if args.task_command == "create":
        _print_json(
            storage.create_task(
                args.workflow_id,
                args.title,
                kind=args.kind,
                profile=args.profile,
                depends_on=args.depends_on,
                skills=args.skill,
                prompt_template_ref=args.prompt_template_ref,
                outputs=args.output,
                gates=args.gate,
                prompt_text=args.prompt_text,
                priority=args.priority,
                risk_level=args.risk_level,
                created_by=args.created_by,
                created_reason=args.created_reason,
            )
        )
        return 0
    if args.task_command == "list":
        _print_json(storage.list_tasks(args.workflow_id))
        return 0
    if args.task_command == "claim":
        task = storage.claim_next_task(args.workflow_id, worker_id=args.worker_id, profile=args.profile, lease_seconds=args.lease_seconds)
        _print_json(task or {})
        return 0 if task else 1
    if args.task_command == "release":
        _print_json(storage.release_task_claim(args.task_id, reason=args.reason))
        return 0
    if args.task_command == "reassign":
        _print_json(storage.reassign_task_profile(args.task_id, profile=args.profile, reason=args.reason))
        return 0
    if args.task_command == "retry":
        _print_json(storage.retry_task(args.task_id, reason=args.reason))
        return 0
    if args.task_command == "complete":
        _print_json(
            storage.complete_task(
                args.task_id,
                status=args.status,
                result=_json_option(args.result_json, "--result-json"),
                human_action_title=args.title,
                human_action_body=args.body,
                questions=_question_options(args.question),
                options=args.option,
                evidence=args.evidence,
                requested_by=args.requested_by,
            )
        )
        return 0
    return 2


def _handle_run_workitem(args: argparse.Namespace) -> int:
    project_id = args.project_id or Path(args.project).expanduser().name
    payload = {
        "project_id": project_id,
        "worker_id": args.worker_id,
        "profile": args.profile,
        "max_tasks": args.max_tasks,
        "dry_run": args.dry_run,
    }
    if args.local:
        storage = _project_storage(args.project)
        _print_json(
            storage.enqueue_run_request(
                project_id,
                args.workitem_id,
                kind="workitem",
                requested_worker_id=args.worker_id,
                profile=args.profile,
                max_tasks=args.max_tasks,
                dry_run=args.dry_run,
            )
        )
        return 0
    api_url = (args.api_url or os.environ.get("HWE_API_URL") or "http://127.0.0.1:8711").rstrip("/")
    project_ref = _api_project_ref(args.project)
    path = f"/api/projects/{urllib.parse.quote(project_ref)}/workitems/{urllib.parse.quote(args.workitem_id)}/run"
    _print_json(_api_json_request(api_url, path, payload))
    return 0


def _handle_worker(args: argparse.Namespace) -> int:
    worker = ProjectWorker(worker_id=args.worker_id, profile=args.profile)
    if args.once:
        summary = worker.run_once(project_ref=args.project, max_requests=args.max_requests)
        _print_json(summary.__dict__)
        return 1 if summary.requests_failed else 0
    try:
        print(f"HWE worker started: worker_id={worker.worker_id} profile={args.profile or '*'} project={args.project or '*'}", file=sys.stderr)
        worker.run_forever(project_ref=args.project, poll_interval_seconds=args.poll_interval)
    except KeyboardInterrupt:
        print("HWE worker interrupted.", file=sys.stderr)
    return 0


def _handle_human_action(args: argparse.Namespace) -> int:
    storage = _project_storage(args.project)
    project_id = args.project_id or Path(args.project).expanduser().name
    command = args.human_action_command
    if command == "list":
        _print_json(storage.list_human_actions(project_id, status=args.status, kind=args.kind))
        return 0
    if command == "create":
        _print_json(
            storage.create_human_action(
                project_id,
                kind=args.kind,
                title=args.title,
                body=args.body,
                workitem_id=args.workitem_id,
                workflow_id=args.workflow_id,
                task_id=args.task_id,
                run_id=args.run_id,
                conversation_id=args.conversation_id,
                questions=[{"id": f"q{index}", "question": question} for index, question in enumerate(args.question, start=1)],
                options=args.option,
                evidence=args.evidence,
                requested_by=args.requested_by,
            )
        )
        return 0
    if command == "show":
        action = storage.get_human_action(args.human_action_id)
        if action["project_id"] != project_id:
            raise ProjectStorageError("Human action does not belong to project.")
        _print_json(action)
        return 0
    if command == "answer":
        _print_json(
            storage.resolve_human_action(
                args.human_action_id,
                resolution="answered",
                response={"text": args.text},
                resolved_by=args.resolved_by,
            )
        )
        return 0
    if command == "approve":
        _print_json(
            storage.resolve_human_action(
                args.human_action_id,
                resolution="approved",
                response={"text": args.text},
                resolved_by=args.resolved_by,
            )
        )
        return 0
    if command == "reject":
        _print_json(
            storage.resolve_human_action(
                args.human_action_id,
                resolution="rejected",
                response={"reason": args.reason},
                resolved_by=args.resolved_by,
            )
        )
        return 0
    return 2


def _handle_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError as exc:
        raise ConfigError("Install HWE with API dependencies before running `hwe serve`.") from exc
    uvicorn.run("hermes_workflow_engine.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def _handle_doctor(args: argparse.Namespace) -> int:
    return Doctor(repo=args.repo, config_path=args.config, fix=args.fix).run()


def _project_storage(project: str) -> ProjectStorage:
    config = load_config()
    resolved_root = resolve_project_root(project, config)
    return ProjectStorage(resolved_root, config=config)


def _ensure_project(storage: ProjectStorage, project_id: str) -> None:
    try:
        storage.get_project(project_id)
    except ProjectStorageError:
        storage.upsert_project(project_id, project_id=project_id)


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _json_option(value: str | None, label: str) -> dict[str, object] | None:
    if value is None:
        return None
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ProjectStorageError(f"{label} must be valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ProjectStorageError(f"{label} must be a JSON object.")
    return payload


def _api_project_ref(project: str) -> str:
    path = Path(project).expanduser()
    if path.is_absolute() or len(path.parts) > 1:
        return path.name
    return project


def _api_json_request(api_url: str, path: str, payload: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        f"{api_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ProjectStorageError(f"HWE API request failed with HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise ProjectStorageError(f"HWE API is not reachable at {api_url}: {exc.reason}") from exc


def _question_options(questions: list[str]) -> list[dict[str, object]]:
    return [{"id": f"q{index}", "question": question} for index, question in enumerate(questions, start=1)]


def _body_text(
    body: str | None,
    body_file: str | None,
    label: str,
    *,
    base_dir: Path | None = None,
    default_file: Path | None = None,
) -> str:
    if body and body_file:
        raise ProjectStorageError(f"Provide either --body or --body-file for {label}, not both.")
    if body_file:
        path = Path(body_file).expanduser()
        if not path.is_absolute() and base_dir is not None:
            path = base_dir / path
        return path.read_text(encoding="utf-8")
    if body:
        return body
    if default_file is not None and base_dir is not None:
        path = base_dir / default_file
        if path.exists():
            return path.read_text(encoding="utf-8")
        raise ProjectStorageError(f"Missing {label}; provide --body, --body-file, or create {path}.")
    raise ProjectStorageError(f"Missing {label}; provide --body or --body-file.")


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]
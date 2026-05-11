from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ConfigError, HWEConfig, configured_config_path, load_config, write_config
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

    prompt_template_parser = subparsers.add_parser("prompt-template", help="Manage role prompt templates.")
    prompt_template_subparsers = prompt_template_parser.add_subparsers(dest="prompt_template_command", required=True)
    prompt_template_create = prompt_template_subparsers.add_parser("create", help="Create a role prompt template.")
    prompt_template_create.add_argument("project")
    prompt_template_create.add_argument("role")
    prompt_template_create.add_argument("name")
    prompt_template_create.add_argument("--project-id", default=None)
    prompt_template_create.add_argument("--version", default="0.1.0")
    prompt_template_create.add_argument("--description", default="")
    prompt_template_create.add_argument("--body", default=None)
    prompt_template_create.add_argument("--body-file", default=None)
    prompt_template_create.add_argument("--tag", action="append", default=[])
    prompt_template_list = prompt_template_subparsers.add_parser("list", help="List role prompt templates.")
    prompt_template_list.add_argument("project")
    prompt_template_list.add_argument("--project-id", default=None)
    prompt_template_list.add_argument("--role", default=None)

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
    task_create.add_argument("--prompt-template-id", default=None)
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
    task_claim = task_subparsers.add_parser("claim", help="Claim the next ready task.")
    task_claim.add_argument("project")
    task_claim.add_argument("workflow_id")
    task_claim.add_argument("--worker-id", required=True)
    task_claim.add_argument("--profile", default=None)
    task_claim.add_argument("--lease-seconds", type=int, default=900)
    task_complete = task_subparsers.add_parser("complete", help="Complete a claimed task.")
    task_complete.add_argument("project")
    task_complete.add_argument("task_id")
    task_complete.add_argument("--status", default="succeeded", choices=["succeeded", "failed", "cancelled", "waiting_for_info", "waiting_for_approval"])

    args = parser.parse_args(argv)

    try:
        if args.command == "config":
            return _handle_config(args)
        if args.command == "project":
            return _handle_project(args)
        if args.command == "workitem":
            return _handle_workitem(args)
        if args.command == "prompt-template":
            return _handle_prompt_template(args)
        if args.command == "workflow":
            return _handle_workflow(args)
        if args.command == "task":
            return _handle_task(args)

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


def _handle_prompt_template(args: argparse.Namespace) -> int:
    storage = _project_storage(args.project)
    project_id = args.project_id or Path(args.project).expanduser().name
    if args.prompt_template_command == "create":
        _ensure_project(storage, project_id)
        config = load_config()
        body = _body_text(
            args.body,
            args.body_file,
            "prompt template body",
            base_dir=config.prompt_template_root,
            default_file=Path(args.role) / f"{args.name}.md",
        )
        _print_json(
            storage.create_role_prompt_template(
                project_id,
                args.role,
                args.name,
                body,
                version=args.version,
                description=args.description,
                tags=args.tag,
            )
        )
        return 0
    if args.prompt_template_command == "list":
        _print_json(storage.list_role_prompt_templates(project_id, role=args.role))
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
                prompt_template_id=args.prompt_template_id,
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
    if args.task_command == "complete":
        _print_json(storage.complete_task(args.task_id, status=args.status))
        return 0
    return 2


def _project_storage(project: str) -> ProjectStorage:
    resolved_root = resolve_project_root(project)
    return ProjectStorage(resolved_root)


def _ensure_project(storage: ProjectStorage, project_id: str) -> None:
    try:
        storage.get_project(project_id)
    except ProjectStorageError:
        storage.upsert_project(project_id, project_id=project_id)


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


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
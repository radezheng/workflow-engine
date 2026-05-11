from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ConfigError, HWEConfig, configured_config_path, load_config, write_config
from .runtime import WorkflowRuntime
from .spec import SpecError, load_workflow
from .storage import Storage


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
    config_init.add_argument("--force", action="store_true", help="Overwrite an existing config file.")

    args = parser.parse_args(argv)

    try:
        if args.command == "config":
            return _handle_config(args)

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
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.config_command == "init":
        config = HWEConfig(default_workspace_root=Path(args.default_workspace_root).expanduser())
        path = write_config(config, force=args.force)
        print(f"created HWE config: {path}")
        return 0
    return 2


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]
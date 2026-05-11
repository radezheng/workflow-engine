# Hermes Workflow Engine

This is a local MVP implementation of the workflow engine described in [workflow_engine_design.md](workflow_engine_design.md). It drives Hermes profiles as bounded subprocess workers while keeping workflow state, context bundles, logs, artifacts, gate results, and events under each target project's `.engine/` directory.

## What Works Now

- Parse a `workflow.yaml` spec.
- Support one shared workspace root with per-project folders.
- Store workflow, step, run, event, context, artifact, and gate state in SQLite.
- Run `command` steps and Hermes `agent` steps serially.
- Respect `needs` dependencies for serial scheduling.
- Compile deterministic context bundles before worker launch.
- Run profile preflight: optional model switch command and optional LM Studio-style healthcheck.
- Invoke Hermes through profile aliases such as `coder chat -Q --source workflow-engine -q <prompt>`.
- Capture stdout, stderr, final prompt, result JSON, artifact snapshots, and git diff.
- Run initial deterministic validators.
- Support `--dry-run` for exercising workflow scheduling without launching Hermes.

## Install For Local Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

You can also run directly without installing:

```bash
PYTHONPATH=src python3 -m hermes_workflow_engine --help
```

## Try The Example

The example writes a small file with a command step, then dry-runs a coder profile step.

```bash
PYTHONPATH=src python3 -m hermes_workflow_engine run examples/workflow.yaml --dry-run
PYTHONPATH=src python3 -m hermes_workflow_engine status examples/workflow.yaml
PYTHONPATH=src python3 -m hermes_workflow_engine events examples/workflow.yaml
```

Runtime files are written to `examples/workspace/projects/example/.engine/`.

## Workspace And Project Layout

For multiple projects, use `workflow.workspace` as the shared workspace root and `workflow.project` as the project folder under it:

```yaml
workflow:
  id: my-project-flow
  workspace: /path/to/hermes-workspace
  project: projects/my-project
```

All commands, Hermes profile invocations, output paths, validators, artifacts, and state then use `/path/to/hermes-workspace/projects/my-project` as the project workspace. That project gets its own `.engine/` directory, so progress is tracked independently per project. If `workflow.project` is omitted, the old single-project behavior is preserved and `workflow.workspace` itself is treated as the project workspace.

## Running A Real Hermes Profile Step

Set the workflow workspace and optional project folder to the project you want Hermes to edit, then define an `agent` step:

```yaml
steps:
  - id: implement_slice
    title: Implement focused slice
    kind: agent
    profile: coder
    locks: [repo]
    prompt: prompts/implement_slice.md
    context:
      include:
        - artifacts.paths:
            - docs/requirements.md
            - docs/design.md
    outputs:
      - src/feature.py
    review:
      mode: inline
      reviewer: reviewer
      gates:
        - python_syntax_ok
        - no_hardcoded_credentials
```

Profiles map workflow names to Hermes profiles and optional model preflight:

```yaml
profiles:
  coder:
    hermes_profile: coder
    # Optional. Defaults to the profile alias when it exists, then HERMES_BIN/hermes.
    hermes_command: coder
    hermes_args: [--accept-hooks]
    switch_command: /Users/rade/loadcoder.sh
    healthcheck:
      url: http://127.0.0.1:1234/v1/chat/completions
      model: qwen/qwen3-coder-next
```

## CLI

```bash
hwe validate workflow.yaml
hwe run workflow.yaml [--dry-run] [--max-steps N]
hwe status workflow.yaml
hwe events workflow.yaml [--limit N]
```

## Current Validator Names

- `git_initialized`
- `planning_docs_complete`
- `external_services_declared`
- `no_hardcoded_credentials`
- `no_external_service_mutation`
- `no_placeholder_ingestion`
- `source_evidence_required`
- `python_syntax_ok`
- `node_build_ok`
- `review_result_parseable`
- `no_untracked_debug_artifacts`

Unknown gate names are recorded as `skipped` so specs can be forward-compatible while the plugin surface grows.
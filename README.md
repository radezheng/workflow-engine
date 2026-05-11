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

Runtime files are written to the example project's `.engine/` directory.

## Workspace And Project Layout

For multiple projects, use `workflow.workspace` as the shared workspace root and `workflow.project` as the project folder under it:

```yaml
workflow:
  id: my-project-flow
  workspace: /path/to/hermes-workspace
  project: my-project
```

All commands, Hermes profile invocations, output paths, validators, artifacts, and state then use `/path/to/hermes-workspace/my-project` as the project workspace. That project gets its own `.engine/` directory, so progress is tracked independently per project. If `workflow.project` is omitted, the old single-project behavior is preserved and `workflow.workspace` itself is treated as the project workspace.

## HWE Local Config

Machine-specific defaults belong in HWE config, not in skills or workflow templates. By default, HWE looks for `hwe.config.yaml` from the current directory upward. If none exists, `hwe config init` creates `hwe.config.yaml` in the current directory. Set `HWE_CONFIG` to use an explicit file.

Create or inspect the local config with:

```bash
hwe config init --default-workspace-root ~/workspaces/hermes --prompt-template-root ./ptemplate
hwe config show
hwe config path
```

When a workflow omits `workflow.workspace`, HWE uses `default_workspace_root` from this config:

```yaml
default_workspace_root: ~/workspaces/hermes
prompt_template_root: ./ptemplate
```

`prompt_template_root` is an HWE-side template library path, not a target project path. Relative values are resolved from the directory containing `hwe.config.yaml`; the default is `./ptemplate`.

Then a workflow can specify only the project name:

```yaml
workflow:
  id: my-project-flow
  project: my-project
```

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
    # Optional. Prefer values generated from Hermes CLI/API or profile metadata.
    switch_command: ./scripts/use-coder-profile.sh
    healthcheck:
      url: http://localhost:1234/v1/chat/completions
      model: coder-model
```

## CLI

```bash
hwe validate workflow.yaml
hwe run workflow.yaml [--dry-run] [--max-steps N]
hwe status workflow.yaml
hwe events workflow.yaml [--limit N]
```

## Project/WorkItem/Task Queue

Project workflow mode stores state in each project's `.engine/engine.db` and starts with project, work item, workflow, and task queue records. This is the persistence layer for the future planner and worker loop.

```bash
hwe project init my-project --id my-project

WORKITEM_ID=$(hwe workitem create my-project "Add notes" \
  --requirements "Support Markdown notes" \
  --acceptance "Create, edit, delete, and view notes" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

WORKFLOW_ID=$(hwe workflow create my-project "$WORKITEM_ID" \
  --planner-profile reviewer \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

hwe task create my-project "$WORKFLOW_ID" "Design notes" --kind design --profile reviewer
hwe task list my-project "$WORKFLOW_ID"
hwe task claim my-project "$WORKFLOW_ID" --worker-id local-reviewer --profile reviewer
```

When a task is completed with `hwe task complete <project> <task-id>`, dependent tasks whose prerequisites succeeded become `ready` automatically.

Role prompt templates let a project accumulate reusable planner, reviewer, QA, or coder instructions. Tasks can reference a template and declare the skills they expect:

```bash
TEMPLATE_ID=$(hwe prompt-template create my-project reviewer implementation-review \
  --body "Check correctness, tests, security, regressions, and acceptance evidence." \
  --tag review --tag best-practices \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

hwe task create my-project "$WORKFLOW_ID" "Review implementation" \
  --kind review \
  --profile reviewer \
  --prompt-template-id "$TEMPLATE_ID" \
  --skill hermes-project-workflow
```

If `--body` and `--body-file` are omitted, HWE reads the template from `<prompt_template_root>/<role>/<name>.md`, for example `./ptemplate/reviewer/implementation-review.md`. Relative `--body-file` paths are also resolved from `prompt_template_root`.

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
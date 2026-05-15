# Finance News Collector Dogfood Run

Date: 2026-05-14
HWE repo: `/Users/rade/workspace/hermes/workflow-engine`
Target project: `/Users/rade/workspaces/hermes/finance-news-collector`
Project id/ref: `finance-news-collector`
Workflow template: `software-project-dev`

## Goal

从零创建 Finance News Collector 项目，并用 HWE workflow template 驱动完整流程：project -> workitem -> workflow template planning -> designer planning run -> template materialization -> generated task graph -> implementation/verification/review。

## Requirement

Implement a daily financial news collection and display system.

1. Data Collection: Use mx-search skill to fetch daily financial news, extract key info, and store in a structured local file (JSON).
2. Frontend: A modern React/Vite interface to display the news items from the local file.
3. Verification: End-to-end smoke tests ensuring data flows from search to UI.

Constraints:

- Strictly follow the HWE software development lifecycle: Designer -> Coder -> Reviewer.
- For data collection, use mx-search via `hermes chat -p default -q "<query>"` to ensure the skill is invoked correctly.
- Use workflow template `software-project-dev` as the source of workflow resources and materialization rules.
- Do not parse natural-language plan output in HWE code; pass stdout paths to worker tasks.

## Interaction Log

### 0. Reset Existing Project

- Deleted HWE project state for `finance-news-collector` through `ProjectStorage.connect()` with `DELETE FROM projects WHERE id = %s`.
- Removed exact target directory `/Users/rade/workspaces/hermes/finance-news-collector`.
- Result: clean start.

### 1. Create Project And Workitem

Command shape:

```bash
HWE_CONFIG=$PWD/hwe.config.yaml .venv/bin/hwe project init finance-news-collector --id finance-news-collector
HWE_CONFIG=$PWD/hwe.config.yaml .venv/bin/hwe workitem create finance-news-collector 'Finance News Collector' ...
```

Result:

- Project id: `finance-news-collector`
- Project root: `/Users/rade/workspaces/hermes/finance-news-collector`
- Workitem id: `wi_96d174791285`
- Workitem status: `ready`

### 2. Create Initial Planning Task From Workflow Template

API call:

```bash
POST /api/projects/finance-news-collector/workitems/wi_96d174791285/plan
{
	"project_id": "finance-news-collector",
	"workflow_template_id": "software-project-dev",
	"parameters": {
		"designer_profile": "designer",
		"coder_profile": "coder",
		"reviewer_profile": "reviewer"
	}
}
```

Result:

- Workflow id: `wf_a09bf279026a`
- Planning task id: `task_b33bf9fdba8b`
- Planning task title: `规划 workitem`
- Planning task profile: `designer`
- Planning task prompt template: `designer/workitem-plan`
- Planning task created reason: `workflow-template:software-project-dev:stage:workitem-plan`

### 3. Run Planning Task

Command:

```bash
HWE_CONFIG=$PWD/hwe.config.yaml .venv/bin/hwe run-workitem finance-news-collector wi_96d174791285 --project-id finance-news-collector --max-tasks 1
```

Result:

- Started: 1
- Succeeded: 1
- Failed: 0
- Waiting for human: 0
- Run id: `run_7f0fb70f9c37`
- Prompt path: `/Users/rade/workspaces/hermes/finance-news-collector/.engine/runs/run_7f0fb70f9c37/prompt.md`
- Stdout path: `/Users/rade/workspaces/hermes/finance-news-collector/.engine/runs/run_7f0fb70f9c37/stdout.log`
- Stderr path: `/Users/rade/workspaces/hermes/finance-news-collector/.engine/runs/run_7f0fb70f9c37/stderr.log`

Planning output summary:

- Project type: new project.
- Required constraint: use `hermes chat -p default -q "<query>"` for `mx-search`; do not call lower-level APIs directly.
- Suggested path: Technical Design -> Task Breakdown -> Implementation.
- Planning identified three human-confirmation topics: cron/manual trigger, query template, and JSON retention strategy.
- The task itself completed successfully; the template action exposed `materialize_plan` for the next designer breakdown step.

### 4. Materialize Planning Output Into Breakdown Task

API call:

```bash
POST /api/projects/finance-news-collector/tasks/task_b33bf9fdba8b/materialize-plan
{
	"project_id": "finance-news-collector",
	"workflow_template_id": "software-project-dev"
}
```

Result:

- Created breakdown task id: `task_c5efa0e7cba3`
- Status: `ready`
- Profile: `designer`
- Prompt template: `designer/task-breakdown`
- Created reason: `breakdown-from-plan:task_b33bf9fdba8b`
- Prompt includes the plan stdout path: `/Users/rade/workspaces/hermes/finance-news-collector/.engine/runs/run_7f0fb70f9c37/stdout.log`
- Prompt includes child workflow template hints: `qa-review`, `publish-release`

### 5. Run Breakdown Task

Command:

```bash
HWE_CONFIG=$PWD/hwe.config.yaml .venv/bin/hwe run-workitem finance-news-collector wi_96d174791285 --project-id finance-news-collector --max-tasks 1
```

Result:

- Started: 1
- Succeeded: 0
- Failed: 1
- Run id: `run_281f17678735`
- Exit code: `-9`
- Stderr summary: healthcheck succeeded, then Hermes command timed out after 600 seconds.
- Stdout was empty.

Side effects verified after timeout:

- The designer task created a persistent task graph before timing out.
- Ready task: `task_c504a8608a4d` (`Technical Design: Data Schema & Collection Logic`, profile `designer`).
- Pending implementation/review tasks:
	- `task_21425c5ab086` (`Implement News Collector Script`, profile `coder`) depends on `task_c504a8608a4d`.
	- `task_938ae486133a` (`Implement News Frontend`, profile `coder`) depends on `task_c504a8608a4d`.
	- `task_5c5b04439515` (`End-to-End Smoke Test`, profile `coder`) depends on `task_21425c5ab086`.
	- `task_4151bc872d14` (`End-to-End Smoke Test (Frontend)`, profile `coder`) depends on `task_938ae486133a`.
	- `task_5f92387e663e` (`Final Implementation Review`, profile `reviewer`) depends on `task_5c5b04439515`.

Operator decision:

- Marked `task_c5efa0e7cba3` as `superseded`, with result noting that the run timed out after creating the persistent task graph.
- This preserves the failed run evidence while avoiding a stale failed materialization task blocking the rest of the generated queue.

### 6. Run Technical Design Task

Command:

```bash
HWE_CONFIG=$PWD/hwe.config.yaml .venv/bin/hwe run-workitem finance-news-collector wi_96d174791285 --project-id finance-news-collector --max-tasks 1
```

Result:

- Started: 1
- Succeeded: 1
- Failed: 0
- Waiting for human: 0
- Task id: `task_c504a8608a4d`
- Run id: `run_fc51ed5d0dd6`
- Stdout path: `/Users/rade/workspaces/hermes/finance-news-collector/.engine/runs/run_fc51ed5d0dd6/stdout.log`
- Stderr path: `/Users/rade/workspaces/hermes/finance-news-collector/.engine/runs/run_fc51ed5d0dd6/stderr.log`

Generated artifact:

- `/Users/rade/workspaces/hermes/finance-news-collector/docs/data_schema.md`

Current ready queue after design:

- `task_21425c5ab086` (`Implement News Collector Script`, profile `coder`)
- `task_938ae486133a` (`Implement News Frontend`, profile `coder`)

### 7. Run Collector Implementation Task, Interrupted By Operator Error

Command:

```bash
HWE_CONFIG=$PWD/hwe.config.yaml .venv/bin/hwe run-workitem finance-news-collector wi_96d174791285 --project-id finance-news-collector --max-tasks 1
```

Task:

- Task id: `task_21425c5ab086`
- Title: `Implement News Collector Script`
- Profile: `coder`
- Run id: `run_876fe60df506`

What happened:

- The run created partial artifacts:
	- `/Users/rade/workspaces/hermes/finance-news-collector/scripts/collect_news.py`
	- `/Users/rade/workspaces/hermes/finance-news-collector/data/news.json`
	- several temporary debug scripts under `/Users/rade/workspaces/hermes/finance-news-collector/scripts/`
- I misread the state and manually terminated the active Hermes child process while LMS was still working.
- HWE therefore recorded the task as `failed` with exit code `-2`.
- This was operator error, not a valid worker failure.

Gate check after interruption:

- `data/news.json` existed but contained `[]`, so the collector gate was not satisfied.

Recovery decision:

- Retry the same HWE task and allow the worker to finish naturally.
- Do not manually kill the Hermes/LMS path while it is actively generating.

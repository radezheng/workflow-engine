# Workflow Template Authoring

Use this reference when creating or editing HWE workflow templates. The skill entrypoint should only say to follow templates; this file owns template-building details.

## When To Create Or Edit A Template

Create or edit a workflow template when:

- The user is asking for a repeatable workflow, not a one-off task.
- Existing templates do not encode the desired stages, gates, profiles, source rules, or child workflows.
- Workers are likely to improvise task order, skip review/verification, or manually transcribe plan prose into tasks.
- A project needs local flow overrides without changing built-in behavior for every project.

Do not patch the HWE skill with workflow-specific task order. Put task order and gates in YAML templates.

## Locations And Precedence

Templates are YAML files loaded in this order; later entries override earlier templates by `id`:

1. Built-in package: `src/hermes_workflow_engine/workflow_templates/*.yaml`
2. Config library: `<workflow_template_root>/*.yaml`
3. Project override: `<project>/.engine/workflow-templates/*.yaml`

Use project overrides for one project, config templates for local reusable flows, and built-ins only for HWE product defaults.

## Template Shape

```yaml
id: example-flow
name: Example Flow
description: Short operator-facing description.
version: 1
parameters:
  designer_profile:
    default: designer
    description: Profile for planning and design.
  reviewer_profile:
    default: reviewer
profiles:
  designer: ${designer_profile}
  reviewer: ${reviewer_profile}
prompt_templates:
  plan: designer/workitem-plan
planning_task:
  stage: workitem-plan
  title: Plan workitem
  kind: planning
  profile: ${designer_profile}
  prompt_template_ref: designer/workitem-plan
  prompt_text: Plan this workitem. Do not create the executable queue here.
  skills: [hwe]
  outputs: [plan]
  gates: [requirements covered]
  priority: 10
review_tasks:
  - stage: plan-gate
    title: Gate plan
    kind: review
    profile: ${reviewer_profile}
    prompt_template_ref: reviewer/planning-review
    prompt_text: Verify this source can be materialized.
    skills: [hwe]
    priority_offset: 1
materialize:
  sources:
    - stage: plan-gate
      prompt_template_ref: reviewer/planning-review
      statuses: [succeeded]
  task:
    stage: task-breakdown
    title: Materialize executable queue
    kind: planning
    profile: ${designer_profile}
    prompt_template_ref: designer/task-breakdown
    skills: [hwe]
    priority_offset: 1
  input_prompt: |
    Read source evidence at ${stdout_path}.
    Project id: ${project_id}
    Workitem id: ${workitem_id}
    Workflow id: ${workflow_id}
    Create real HWE task records; do not output prose-only tasks.
child_workflows:
  - id: qa
    template: qa-review
    trigger: implementation and checks complete
    description: Verification and acceptance flow.
```

## Supported Variables

Template parameter values are strings. `${name}` substitutions work throughout the template after defaults and request parameters are merged.

Common parameter pattern:

```yaml
parameters:
  reviewer_profile:
    default: reviewer
profiles:
  reviewer: ${reviewer_profile}
prompt_templates:
  review: ${review_prompt_template}
```

Materialization prompt variables currently include:

- `${project_root}`
- `${project_id}`
- `${workitem_id}`
- `${workitem_title}`
- `${workflow_id}`
- `${source_task_id}`
- `${stdout_path}`
- `${review_stdout_path}`
- `${child_workflows}`
- `${profile.<name>}` from resolved profiles
- `${prompt_template.<name>}` from resolved prompt templates

## Authoring Rules

- Keep flow decisions in the template, not in the HWE skill.
- Prefer explicit stages and `created_reason`-backed source rules. If a source has `stage`, HWE matches that stage rather than only matching prompt template refs.
- Keep planning/design tasks from directly creating implementation queues unless the template explicitly makes that their job.
- Make materialization tasks create real HWE task records through CLI/API, with real `depends_on` relationships. Prose tables are not task state.
- Put profile names behind parameters when the flow may run in default-profile orchestration mode.
- Use `review_tasks` or other gates in the template when plan/design/task-breakdown quality must be checked before later actions appear.
- Include deterministic `command` or `http_check` tasks in the materialized queue for runnable apps when practical.
- Use child workflow references to advertise optional nested flows such as QA or publish; do not hard-code nested flow behavior in the skill.

## Validation Checklist

After editing a template:

1. Confirm YAML parses and `id` is a safe path segment.
1. Confirm every `prompt_template_ref` exists in the project override or public prompt template root.
1. Confirm every `profile` resolves to a configured HWE profile or an intentional default-profile parameter.
1. Confirm `planning_task`, `materialize.task`, and `materialize.input_prompt` exist when the template is meant to plan and materialize.
1. Confirm `materialize.sources` matches the intended source stage/status.
1. Run the API/template tests or at least load templates through HWE:

```bash
HWE_CONFIG="$HWE_CONFIG" "$HWE_PYTHON" - <<'PY'
from hermes_workflow_engine.config import load_config
from hermes_workflow_engine.workflow_templates import list_workflow_templates, resolve_workflow_template
config = load_config()
for template in list_workflow_templates(config):
    resolved = resolve_workflow_template(template)
    print(resolved['id'], resolved.get('source'), resolved.get('path'))
PY
```

1. Restart `hwe serve` if the API was already running.

For built-in template changes, run `.venv/bin/pytest` from the HWE repository root.

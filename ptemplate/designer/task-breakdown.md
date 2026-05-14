# Task Breakdown

You are refining an existing workitem into executable HWE tasks. As the designer profile, you own PM clarification, planning, and design decisions before implementation starts.

If the task input names a plan stdout path, read that file and use it as the source of truth. Do not rely on summary text in the prompt when the plan file is available. Your success condition is persisted HWE task records, not a prose task list.

Build a task graph that minimizes ambiguity for workers:

- Use designer tasks for unclear requirements, architecture, data flow, or acceptance criteria.
- Use coder tasks only for focused implementation or repair slices.
- Use reviewer tasks for implementation review, QA review, and acceptance checks.
- Use qa task templates for test plans, regression checks, and acceptance evidence while routing them to the reviewer profile.
- Use command and http_check tasks for deterministic verification whenever possible.

For each proposed task, include:

- Title.
- Role/profile.
- Task kind.
- Dependencies.
- Prompt intent.
- Expected files or artifacts.
- Gates that prove completion.

Flag any task that should not run until a human action is answered. Keep the graph small enough that failed tasks are easy to retry or supersede.

Create the resulting tasks through HWE CLI/API operations instead of only describing them in prose. Use `hwe task create` with explicit `--depends-on`, `--profile`, `--kind`, `--prompt-template-ref` or `--prompt-text`, and deterministic gates where appropriate. Do not delete or rewrite the source planning task; preserve it as evidence.

If HWE is routing real `designer`, `coder`, `reviewer`, or `qa` profiles and their skills/templates are verified, assign tasks to those profiles. If the workflow is single `default` profile only, create the same staged task graph using `default` or no profile instead of pretending other profiles will run. If you cannot safely create the task graph, complete this task as `waiting_for_info` with the specific missing parameter or approval.

# Task Breakdown

You are refining an existing workitem into executable HWE tasks.

If the task input names a plan stdout path, read that file and use it as the source of truth. Your success condition is persisted HWE task records, not a prose task list.

Build a task graph that minimizes ambiguity for workers:

- Use planner or designer tasks for unclear architecture, data flow, or acceptance criteria.
- Use coder tasks only for focused implementation or repair slices.
- Use reviewer tasks for design and implementation review.
- Use qa tasks for test plans, regression checks, and acceptance evidence.
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

Create the resulting tasks through HWE CLI/API operations instead of only describing them in prose. If you cannot safely create the task graph, complete this task as `waiting_for_info` with the specific missing parameter or approval.

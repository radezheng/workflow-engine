# Planning Review

You are reviewing a plan, design, QA plan, publish plan, or task-breakdown source before HWE materializes it into executable tasks.

Focus on whether the next worker can create a real, dependency-aware task graph from the upstream plan.

Check:

- Requirements, constraints, and acceptance criteria are covered.
- Human decisions are either already answered or represented as real HWE human actions.
- The proposed task graph has clear dependencies, not a flat list of ready tasks.
- Every task has a real configured profile, task kind, prompt/template strategy, outputs, and gates.
- Deterministic verification and final review are included where practical.
- The plan avoids fake `kind=human-action` tasks and does not rely on prose-only "pending" tasks.

Output findings first. If the plan is materializable, say that clearly and include the exact upstream plan stdout path or evidence path you reviewed. If it is not materializable, list blocking gaps and recommend whether to retry planning, ask a human action, or revise the task breakdown prompt.
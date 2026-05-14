# Prompt Templates

HWE reads role prompt template source files from this directory by default.

Use one folder per role and one Markdown file per template name:

```text
ptemplate/
  designer/
    workitem-plan.md
    technical-design.md
  reviewer/
    implementation-review.md
```

Agent tasks can reference templates by `role/name`, for example `reviewer/implementation-review`. HWE checks the project-local override at `.engine/prompt-templates/<role>/<name>.md` first, then falls back to this public library.

Current templates:

Assistant form-drafting templates:

- `assistant/project.md`: draft project creation fields.
- `assistant/workitem.md`: draft workitem creation fields.
- `assistant/human_action.md`: draft human-action answer, approval, or rejection text.
- `assistant/prompt_template.md`: draft prompt template file fields and body.

Worker role templates:

- `designer/workitem-plan.md`: turn a workitem into an execution strategy.
- `designer/task-breakdown.md`: read a plan file and create/refine an HWE task graph with roles, dependencies, and gates.
- `designer/technical-design.md`: produce implementation design without editing code.
- `coder/implementation-slice.md`: implement one focused feature slice.
- `coder/fix-slice.md`: repair one specific failure with minimal blast radius.
- `reviewer/implementation-review.md`: review implementation risk and regressions.
- `reviewer/acceptance-review.md`: final acceptance against requirements and evidence.
- `reviewer/runtime-smoke.md`: runtime smoke review for runnable applications.
- `qa/test-plan.md`: design deterministic test and smoke coverage.
- `qa/regression-review.md`: check for behavior regressions around touched surfaces.
- `researcher/source-research.md`: gather codebase context before implementation.
- `operator/recovery-plan.md`: plan task release, retry, skip, or supersede recovery.

The historical `planner/` templates remain compatible for existing projects, but new PM, planning, and design tasks should use the `designer` profile. The `reviewer` profile should stay focused on implementation review, QA review, and acceptance evidence.

Example task reference:

```bash
hwe task create my-project "$WORKFLOW_ID" "Review implementation" \
  --kind review \
  --profile reviewer \
  --prompt-template-ref reviewer/implementation-review
```

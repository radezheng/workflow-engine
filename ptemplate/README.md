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

- `designer/workitem-plan.md`: 用中文梳理 workitem，区分新项目/已有项目，提出 research/design/task 候选，但不创建可执行队列。
- `designer/task-breakdown.md`: 用中文读取 plan/design 文件，把任务候选物化为 HWE Task 记录，并验证 profile/template 选择。
- `designer/technical-design.md`: 用中文产出技术设计；已有项目先做只读 research，再给任务候选、profile 分配和 template 建议。
- `coder/implementation-slice.md`: implement one focused feature slice.
- `coder/fix-slice.md`: repair one specific failure with minimal blast radius.
- `reviewer/implementation-review.md`: review implementation risk and regressions.
- `reviewer/planning-review.md`: review plan/design/task-breakdown sources before materialization.
- `reviewer/acceptance-review.md`: final acceptance against requirements and evidence.
- `reviewer/runtime-smoke.md`: runtime smoke review for runnable applications.
- `qa/test-plan.md`: design deterministic test and smoke coverage.
- `qa/regression-review.md`: check for behavior regressions around touched surfaces.
- `pm/recovery-plan.md`: decide task post-execution workflow progress, recover failed tasks, and propose workflow-template improvements when outcomes reveal repeatable process gaps.
- `researcher/source-research.md`: 用中文做已有项目的只读源码/文档研究，为 technical design 和任务拆分提供事实依据。
- `operator/recovery-plan.md`: plan task release, retry, skip, or supersede recovery.

The historical `planner/` templates remain compatible for existing projects, but new planning and design tasks should use the `designer` profile. Task post-execution control uses the template-selected `pm_profile`, which defaults to `designer` unless configured separately. The `reviewer` profile should stay focused on implementation review, QA review, and acceptance evidence.

Example task reference:

```bash
hwe task create my-project "$WORKFLOW_ID" "Review implementation" \
  --kind review \
  --profile reviewer \
  --prompt-template-ref reviewer/implementation-review
```

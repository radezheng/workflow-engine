# Task Breakdown

你正在把已有 workitem 的 plan/design 物化成可执行 HWE Task 记录。

如果任务输入给出了 plan/design 的 `stdout.log` 路径，先读取该文件并以它为事实来源。你的成功条件是持久化的 HWE Task 记录，不是 prose task list。

物化前必须检查：

- 项目类型：新项目、已有项目或不确定。已有项目如果缺少 research/design 证据，先创建 research 或 design 任务，不要直接创建 coder 任务。
- HWE config 中实际存在的 profiles。只把任务分配给真实可路由、技能和模板可用的 profile。
- 如果是 single `default` profile 模式，使用 `default` 或不写 profile，不要假装 coder/reviewer 会执行。
- 每一步的 prompt template 是否合适；优先项目 override，再使用 public template。
- 如需项目定制 prompt，创建或更新 `<project>/.engine/prompt-templates/<role>/<name>.md`，然后仍用 `--prompt-template-ref role/name` 引用。

构建任务图时减少 worker 的歧义：

- 需求、架构、数据流或验收不清楚时，创建 planner/designer/research/human-action 任务。
- coder 任务只用于聚焦的实现或修复切片。
- reviewer 任务用于 design review、implementation review、QA review 和 acceptance evidence。
- command 和 http_check 用于 deterministic verification。

每个任务都应明确 title、真实 profile、kind、dependencies、prompt template 或 prompt_text、预期产物和验证 gates。

通过 HWE CLI/API 创建结果任务，不要只描述。无法安全创建任务图时，把本任务完成为 `waiting_for_info`，说明缺少的 profile、template、research 证据、参数或审批。

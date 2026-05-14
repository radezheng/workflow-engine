# Task Breakdown

你正在把已有 workitem 的 plan/design 物化成可执行的 HWE Task 记录。作为 designer profile，你负责在实现开始前确认 PM 澄清、规划、技术设计、profile 分配和 prompt template 选择都足够可靠。

如果任务输入给出了 plan/design 的 `stdout.log` 路径，先读取该文件并以它为事实来源。不要只依赖 prompt 中的摘要。你的成功条件是持久化的 HWE Task 记录，不是 prose task list。

物化前必须检查：

- 项目类型：新项目、已有项目或不确定。已有项目如果缺少 research/design 证据，先创建 research 或 technical design 任务，不要直接创建 coder 任务。
- HWE config 中实际存在的 profiles。只把任务分配给真实可路由、技能和模板可用的 profile。
- 如果是 single `default` profile 模式，使用 `default` 或不写 profile 创建同样的分阶段任务图，不要假装 coder/reviewer 会执行。
- 每一步的 prompt template 是否合适。优先使用项目 override，再使用 public template。
- 如需项目定制 prompt，创建或更新 `<project>/.engine/prompt-templates/<role>/<name>.md`，然后仍用 `--prompt-template-ref role/name` 引用。不要为了单个项目改公共模板。

构建任务图时减少 worker 的歧义：

- 需求、架构、数据流或验收不清楚时，创建 designer/research/human-action 任务。
- coder 任务只用于聚焦的实现或修复切片。
- reviewer 任务用于 implementation review、QA review、acceptance evidence。
- qa template 可用于测试计划、回归检查和验收证据；实际 profile 按配置选择，通常可路由到 reviewer。
- command 和 http_check 用于 deterministic verification、build/test/runtime smoke。

每个要创建的任务都应明确：

- Title。
- 真实 profile 或 single-default 分配。
- Task kind。
- Dependencies。
- Prompt template ref 或明确 prompt_text。
- Prompt intent。
- 预期文件、产物或证据路径。
- 验证 gates。

标出必须等待 human action 的任务。保持任务图足够小，失败后容易 retry、fix 或 supersede。

通过 HWE CLI/API 创建结果任务，不要只描述。使用 `hwe task create`，并尽量显式设置 `--depends-on`、`--profile`、`--kind`、`--prompt-template-ref` 或 `--prompt-text`、`--gate`。不要删除或重写源 planning/design task；它们是证据。

如果无法安全创建任务图，把本任务完成为 `waiting_for_info`，说明缺少的参数、profile、template、research 证据或审批。

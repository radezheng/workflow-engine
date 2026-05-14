# Recovery Plan

You are planning recovery for an interrupted, failed, or stale HWE workflow.

Inspect the current project workflow state and decide which tasks should be released, retried, skipped, superseded, or left alone.

Consider:

- Claimed tasks whose worker is no longer active.
- Failed tasks that are transient versus genuinely broken.
- Duplicate tasks already replaced by successful work.
- Human actions that are pending or resolved.
- Run logs and task results that explain the failure.

Output:

1. Current workflow health summary.
2. Recommended recovery actions with task ids.
3. Commands to run, such as `hwe task release`, `hwe task retry`, or `hwe task complete --status superseded`.
4. Risks before resuming `hwe run-workitem`.
5. Verification tasks to run after recovery.

Do not delete workflow history. Prefer state transitions that preserve evidence.
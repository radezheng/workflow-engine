# Regression Review

You are checking whether a change reintroduces old failures or creates new ones around the touched behavior.

Review:

- Recent failures and fixes mentioned in the workitem context.
- State cleanup, retry, release, skip, supersede, and human-action flows.
- API/UI behavior across project, workitem, task, and run selection changes.
- Build and test signals from task runs.

Output:

1. Regression risks checked.
2. Evidence from commands, logs, or source inspection.
3. Any regressions found, with focused repair tasks.
4. Additional smoke checks recommended.

Do not broaden the review into unrelated refactors. Keep the focus on behavior that could be affected by this workitem.
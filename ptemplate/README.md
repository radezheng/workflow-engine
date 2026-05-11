# Prompt Templates

HWE reads role prompt template source files from this directory by default.

Use one folder per role and one Markdown file per template name:

```text
ptemplate/
  reviewer/
    implementation-review.md
  planner/
    feature-plan.md
```

When `hwe prompt-template create <project> <role> <name>` is called without `--body` or `--body-file`, HWE reads `ptemplate/<role>/<name>.md` relative to `hwe.config.yaml`.

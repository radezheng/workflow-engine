# HWE Skill Maintenance Notes

Use this reference when editing the HWE skill itself.

## Public Skill Design Guidance Checked

Sources checked on 2026-05-14:

- VS Code Copilot Agent Skills documentation: skills are folders with `SKILL.md`, optional `scripts/`, `references/`, and `assets/`; `description` is the discovery surface; use supporting files for detailed material.
- Claude Code skills documentation: create skills for repeated procedures; the skill body loads only when used but then stays in context across turns; keep the body concise; move detailed reference material to supporting files; keep `SKILL.md` under 500 lines; put key use cases first in `description`/`when_to_use` because listings may be truncated.

## Maintenance Rules

- Keep the entrypoint actionable. `SKILL.md` should contain the standing rules needed for safe HWE operation, not long essays.
- Keep safety-critical rules in `SKILL.md`: project discovery through configured HWE state, profile/template/skill checks, human-action ambiguity handling, auto-run limits, claimed-task recovery, external-service safety, and secrets handling.
- Keep the skill portable. Do not bake in one machine's repo path, workspace root, service name, model name, or API/UI port as a requirement; use `HWE_REPO`, `HWE_CONFIG`, active config values, arguments, or current repository discovery.
- Keep `/hwe doctor` as the first response to config/environment mismatch reports. Doctor can auto-fix safe local directory issues, but must ask before changing credentials, ports, database/container lifecycle, schemas, profile commands, model switch commands, service lifecycle, or existing profile-local skills.
- Move bulky examples, rare troubleshooting notes, and historical rationale into `references/` once the entrypoint approaches 500 lines or starts burying the first-run workflow.
- Reference supporting files from `SKILL.md` with relative Markdown links so agents know they exist.
- Keep the frontmatter `description` keyword-rich and specific. Include HWE, project/workitem/workflow/task queues, run-workitem, human actions, prompt templates, profile orchestration, runtime smoke checks, and recovery terms.
- Do not add broad pre-approved tool permissions to this skill. HWE operations can mutate workflow state and generated projects, so tool use should remain visible to the operator.
- Prefer short checklists over prose. The remote/default profile must be able to recover the operational sequence after compaction.
- When adding a new HWE operating rule, update `.github/agents/hwe-dev.agent.md` if Copilot agents also need the rule.

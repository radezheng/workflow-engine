# Hermes Agent Bootstrap Guide For HWE

Use this guide when a Hermes `default` profile needs to install or update HWE, install the HWE skill, and validate that the current environment matches the active HWE config.

Public repository: `https://github.com/radezheng/workflow-engine`

The public repository is the source of truth. Do not treat an unversioned local checkout, copied skill directory, or old machine-specific installation as authoritative. If an existing `HWE_REPO` is not a clean checkout of the public repo, ask the owner before moving it aside, reusing it, or choosing a different install directory.

## Confirm Parameters With The Owner

Before installing or changing HWE, confirm any parameter that is not already explicit in the request:

- Install directory for `HWE_REPO`.
- Local `HWE_CONFIG` path and whether to create a new config or reuse an existing one.
- `default_workspace_root` for generated/managed projects.
- Project storage backend: SQLite or an owner-approved PostgreSQL service.
- Current Hermes profile provider details for HWE `ai_providers`: OpenAI-compatible base URL, model, timeout, and secret environment variable if needed.
- Hermes user skill directory and any per-profile skill directories that also need the `hwe` skill.
- Whether existing skill directories may be overwritten by the public repo copy.
- API/UI host and ports if starting the console.
- Whether to run the smoke workflow and whether to archive/remove it afterward.

## 1. Clone Or Update The Public HWE Repo

For a new install, clone the public repo into the owner-approved directory:

```bash
export HWE_REPO=${HWE_REPO:-$HOME/workflow-engine}
git clone https://github.com/radezheng/workflow-engine.git "$HWE_REPO"
cd "$HWE_REPO"
```

For an existing install, verify it is the public repo before updating:

```bash
cd "$HWE_REPO"
git remote get-url origin
git status --short
git pull --ff-only
```

If `origin` is not `https://github.com/radezheng/workflow-engine.git`, or `git status --short` shows local changes, stop and ask the owner how to proceed. Do not run destructive git commands.

## 2. Install HWE Locally

Use a project-local virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
export HWE=$PWD/.venv/bin/hwe
export HWE_PYTHON=$PWD/.venv/bin/python
```

Verify the CLI:

```bash
"$HWE" --help
```

After every HWE update, rerun the editable install so the CLI uses the latest source:

```bash
cd "$HWE_REPO"
. .venv/bin/activate
python -m pip install -e .
```

## 3. Create Or Select HWE Config

For a new machine, initialize a local config. Keep this file local and do not commit secrets:

```bash
"$HWE" config init --default-workspace-root "$HOME/workspaces/hermes"
export HWE_CONFIG=$PWD/hwe.config.yaml
```

If a config already exists and the owner wants to reuse it, point HWE at it:

```bash
export HWE_CONFIG=/path/to/hwe.config.yaml
```

Machine-specific values belong in `hwe.config.yaml` or environment variables: workspace root, prompt template root, project database settings, profile commands, model switch commands, healthcheck URLs, and provider secrets.

Use [docs/hwe.config.example.yaml](hwe.config.example.yaml) as the starting example when the owner wants a full config shape.

### AI Provider Mapping During Bootstrap

HWE `ai_providers` are for UI assistant drafting of projects, workitems, prompt templates, and human-action responses. They do not route worker tasks and they do not need to mirror HWE profiles.

When bootstrapping from an existing Hermes profile, inspect or ask for the current profile's provider. If it is OpenAI-compatible, copy that provider into `hwe.config.yaml` as a single `ai_providers` entry:

```yaml
ai_providers:
  current-profile:
    type: openai_compatible
    base_url: http://127.0.0.1:1234/v1
    model: model-from-current-hermes-profile
    # api_key_env: OPENAI_API_KEY
    timeout_seconds: 60
```

If the current Hermes profile has only one provider, create only one HWE provider. Do not invent separate `designer`, `coder`, or `reviewer` AI providers just because those worker profiles exist. Add multiple HWE `ai_providers` only when the owner explicitly provides multiple distinct OpenAI-compatible providers, such as one local endpoint and one hosted endpoint. If the current profile's provider is hidden, not OpenAI-compatible, or uses credentials the agent cannot read safely, ask the owner for the HWE provider values instead of guessing.

## 4. Install The HWE Skill Into Hermes

This repo carries the project skill at `.agents/skills/hwe`. After owner approval to overwrite the target skill copy, install it into the active Hermes user skill directory:

```bash
mkdir -p "$HOME/.hermes/skills"
rsync -a --delete --exclude '__pycache__/' --exclude '*.pyc' \
  "$HWE_REPO/.agents/skills/hwe/" \
  "$HOME/.hermes/skills/hwe/"
```

If the target already exists and overwrite permission is unclear, compare first and ask the owner:

```bash
diff -ru "$HOME/.hermes/skills/hwe" "$HWE_REPO/.agents/skills/hwe" || true
```

If HWE will dispatch work to multiple Hermes profiles, verify each target profile can discover every required skill. When a profile has its own configured skill directory and the owner approves syncing it, copy the full skill directory there too. Preserve `SKILL.md`, `scripts/`, `references/`, frontmatter, and relative layout.

## 5. Run HWE Doctor

Run doctor before mutating workflow state on a new machine, after changing config, or whenever project discovery/profile routing looks wrong:

```bash
"$HWE_PYTHON" "$HWE_REPO/.agents/skills/hwe/scripts/doctor.py" \
  --repo "$HWE_REPO" \
  --config "$HWE_CONFIG"
```

Doctor reports `OK`, `WARN`, and `FAIL` findings for repo discovery, CLI executable, config loading, workspace/template paths, project database reachability, profiles, switch commands, healthchecks, and AI provider URLs.

Doctor can apply only safe local fixes such as creating configured local directories:

```bash
"$HWE_PYTHON" "$HWE_REPO/.agents/skills/hwe/scripts/doctor.py" \
  --repo "$HWE_REPO" \
  --config "$HWE_CONFIG" \
  --fix
```

Ask the user before changing credentials, ports, database/container lifecycle, schemas, profile commands, model switch commands, API/UI service lifecycle, or overwriting an existing profile-local skill.

## Update Checklist

Use this checklist when the user asks Hermes to update HWE:

1. Confirm owner-approved install/config/skill parameters.
2. Set `HWE_REPO`, `HWE`, `HWE_PYTHON`, and `HWE_CONFIG`.
3. Verify `origin` is `https://github.com/radezheng/workflow-engine.git`.
4. Run `git status --short`; ask before touching local changes.
5. Run `git pull --ff-only`.
6. Reinstall with `python -m pip install -e .` inside `.venv`.
7. Sync `.agents/skills/hwe/` into every approved Hermes profile skill directory that needs it.
8. Run doctor and resolve `FAIL` findings before mutating workflow state.
9. Restart `hwe serve` if the API is running and source/config changed.

## 6. Start Optional Local Console

Only start the console when operator visibility is needed:

```bash
"$HWE" serve --host "${HWE_API_HOST:-127.0.0.1}" --port "${HWE_API_PORT:-8711}"
npm --prefix ui install
npm --prefix ui run dev -- --host "${HWE_UI_HOST:-127.0.0.1}" --port "${HWE_UI_PORT:-5173}"
```

Start `hwe serve` from `HWE_REPO` or set `HWE_CONFIG` explicitly. If projects disappear, run doctor before creating replacement project records.

## 7. First Workflow Smoke Test

Create a small workitem only after doctor is clean or the user approves known warnings:

```bash
"$HWE" project init smoke-lab --id smoke-lab
WORKITEM_ID=$("$HWE" workitem create smoke-lab "HWE smoke" \
  --project-id smoke-lab \
  --requirements "Create a small HWE smoke workflow." \
  --acceptance "Task queue can be created and listed." \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
WORKFLOW_ID=$("$HWE" workflow create smoke-lab "$WORKITEM_ID" \
  --project-id smoke-lab \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
"$HWE" task create smoke-lab "$WORKFLOW_ID" "Echo smoke" \
  --kind command \
  --prompt-text 'printf "hwe smoke ok\\n"'
"$HWE" run-workitem smoke-lab "$WORKITEM_ID" --project-id smoke-lab --max-tasks 1
```

Archive or remove the smoke project only if the user approves cleanup policy for the target environment.

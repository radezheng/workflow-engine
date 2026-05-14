# Hermes Bootstrap Guide For HWE

Use this guide when a Hermes `default` profile needs to install or update HWE, install the HWE skill, and validate that the current environment matches the active HWE config.

Public repository: `https://github.com/radezheng/workflow-engine`

## 1. Locate Or Clone The HWE Repo

If the repo already exists, set `HWE_REPO` to it:

```bash
export HWE_REPO=/path/to/workflow-engine
cd "$HWE_REPO"
```

If installing from GitHub, clone the public repo first:

```bash
export HWE_REPO=${HWE_REPO:-$HOME/workflow-engine}
git clone https://github.com/radezheng/workflow-engine.git "$HWE_REPO"
cd "$HWE_REPO"
```

If updating an existing checkout, preserve local changes and only fast-forward:

```bash
cd "$HWE_REPO"
git status --short
git pull --ff-only
```

If `git status --short` shows local changes, stop and ask the user whether to commit, stash, or keep the local checkout unchanged.

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

If a config already exists, point HWE at it:

```bash
export HWE_CONFIG=/path/to/hwe.config.yaml
```

Machine-specific values belong in `hwe.config.yaml` or environment variables: workspace root, prompt template root, project database settings, profile commands, model switch commands, healthcheck URLs, and provider secrets.

## 4. Install The HWE Skill Into Hermes

This repo carries the project skill at `.agents/skills/hwe`. Install it into the active Hermes user skill directory:

```bash
mkdir -p "$HOME/.hermes/skills"
rsync -a --delete --exclude '__pycache__/' --exclude '*.pyc' \
  "$HWE_REPO/.agents/skills/hwe/" \
  "$HOME/.hermes/skills/hwe/"
```

If the target already exists and may have local changes, compare before overwriting:

```bash
diff -ru "$HOME/.hermes/skills/hwe" "$HWE_REPO/.agents/skills/hwe" || true
```

If HWE will dispatch work to multiple Hermes profiles, verify each target profile can discover every required skill. When a profile has its own configured skill directory, copy the full skill directory there too. Preserve `SKILL.md`, `scripts/`, `references/`, frontmatter, and relative layout.

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

1. Set `HWE_REPO`, `HWE`, `HWE_PYTHON`, and `HWE_CONFIG`.
2. Run `git status --short`; ask before touching local changes.
3. Run `git pull --ff-only`.
4. Reinstall with `python -m pip install -e .` inside `.venv`.
5. Sync `.agents/skills/hwe/` into every Hermes profile skill directory that needs it.
6. Run doctor and resolve `FAIL` findings before mutating workflow state.
7. Restart `hwe serve` if the API is running and source/config changed.

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

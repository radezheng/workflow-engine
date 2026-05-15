from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .context import sha256_file
from .spec import StepSpec, WorkflowSpec, resolve_spec_path


@dataclass(frozen=True)
class WorkerResult:
    status: str
    exit_code: int | None
    stdout_path: Path
    stderr_path: Path
    prompt_path: Path | None
    result_path: Path
    diff_path: Path | None
    artifacts: list[dict[str, Any]]


class WorkerAdapter:
    def __init__(self, spec: WorkflowSpec, dry_run: bool = False):
        self.spec = spec
        self.dry_run = dry_run

    def run_command_step(self, step: StepSpec, run_id: str) -> WorkerResult:
        run_dir = self._run_dir(run_id)
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        exit_code = 0
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            for command in step.commands:
                stdout.write(f"$ {command}\n")
                stdout.flush()
                completed = subprocess.run(
                    command,
                    cwd=self.spec.workspace,
                    shell=True,
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=step.timeout_seconds,
                )
                stdout.write(completed.stdout)
                stderr.write(completed.stderr)
                exit_code = completed.returncode
                if exit_code != 0:
                    break
        diff_path = self._write_git_diff(step, run_dir)
        artifacts = self._snapshot_artifacts(step, run_id, diff_path)
        status = "succeeded" if exit_code == 0 else "failed"
        return self._write_result(run_dir, status, exit_code, stdout_path, stderr_path, None, diff_path, artifacts)

    def run_agent_step(self, step: StepSpec, run_id: str, context_bundle_path: Path) -> WorkerResult:
        run_dir = self._run_dir(run_id)
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        prompt_path = run_dir / "prompt.md"
        profile_name = step.profile or "default"
        profile_config = self._profile_config(profile_name)

        prompt_text = self._build_prompt(step, context_bundle_path)
        prompt_path.write_text(prompt_text, encoding="utf-8")

        if self.dry_run:
            stdout_path.write_text(f"DRY RUN: would invoke Hermes profile `{profile_name}`.\n", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            diff_path = self._write_git_diff(step, run_dir)
            artifacts = self._snapshot_artifacts(step, run_id, diff_path)
            return self._write_result(run_dir, "succeeded", 0, stdout_path, stderr_path, prompt_path, diff_path, artifacts)

        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            self._run_switch_command(profile_config, stdout, stderr)
            self._healthcheck(profile_config)
            hermes_command = self._hermes_command_args(profile_name, profile_config, prompt_text)
            completed = subprocess.run(
                hermes_command,
                cwd=self.spec.workspace,
                check=False,
                text=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=step.timeout_seconds or 3600,
            )
            stdout.write(completed.stdout)
            stderr.write(completed.stderr)
        diff_path = self._write_git_diff(step, run_dir)
        artifacts = self._snapshot_artifacts(step, run_id, diff_path)
        status = "succeeded" if self._is_success_exit_code(completed.returncode, profile_config) else "failed"
        return self._write_result(run_dir, status, completed.returncode, stdout_path, stderr_path, prompt_path, diff_path, artifacts)

    def _run_dir(self, run_id: str) -> Path:
        run_dir = self.spec.engine_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _profile_config(self, profile_name: str) -> dict[str, Any]:
        raw = self.spec.profiles.get(profile_name, {})
        return dict(raw) if isinstance(raw, dict) else {}

    def _hermes_command_args(self, profile_name: str, profile_config: dict[str, Any], prompt_text: str) -> list[str]:
        hermes_profile = str(profile_config.get("hermes_profile", profile_name))
        configured_command = profile_config.get("hermes_command") or profile_config.get("command")
        if configured_command:
            base_command = shlex.split(str(configured_command))
        elif hermes_profile != "default" and shutil.which(hermes_profile):
            base_command = [hermes_profile]
        else:
            base_command = [os.environ.get("HERMES_BIN", "hermes")]

        extra_args = profile_config.get("hermes_args", [])
        if isinstance(extra_args, str):
            extra_args = shlex.split(extra_args)
        elif not isinstance(extra_args, list):
            extra_args = []

        profile_args = _hermes_profile_args(base_command, hermes_profile, extra_args)
        return [*base_command, "chat", *profile_args, "-Q", "--source", "workflow-engine", *[str(arg) for arg in extra_args], "-q", prompt_text]

    def hermes_command_preview(self, profile_name: str, prompt_text: str) -> list[str]:
        profile_config = self._profile_config(profile_name)
        return self._hermes_command_args(profile_name, profile_config, prompt_text)

    def _is_success_exit_code(self, exit_code: int, profile_config: dict[str, Any]) -> bool:
        success_exit_codes = profile_config.get("success_exit_codes", [0])
        if not isinstance(success_exit_codes, list):
            success_exit_codes = [0]
        allowed = {int(code) for code in success_exit_codes if isinstance(code, int) or str(code).lstrip("-").isdigit()}
        return exit_code in allowed

    def _build_prompt(self, step: StepSpec, context_bundle_path: Path) -> str:
        prompt_path = resolve_spec_path(self.spec, step.prompt)
        task_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path and prompt_path.exists() else ""
        context_text = context_bundle_path.read_text(encoding="utf-8")
        return (
            f"{task_prompt.rstrip()}\n\n"
            "# Engine Instructions\n\n"
            "Use the supplied context bundle as the authoritative task input. "
            "If required context is missing, return a JSON block with status `blocked` and `needs_context`.\n\n"
            "# Supplied Context Bundle\n\n"
            f"{context_text}"
        )

    def _run_switch_command(self, profile_config: dict[str, Any], stdout: Any, stderr: Any) -> None:
        switch_commands = _switch_commands(profile_config)
        if not switch_commands:
            return
        strict_switch = _config_bool(profile_config.get("switch_command_required")) or _config_bool(
            profile_config.get("strict_switch_command")
        )
        for switch_command in switch_commands:
            command = str(switch_command["command"])
            stdout.write(f"$ {command}\n")
            stdout.flush()
            completed = subprocess.run(
                command,
                cwd=self.spec.workspace,
                shell=True,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=int(switch_command.get("timeout_seconds", profile_config.get("switch_timeout_seconds", 600))),
            )
            stdout.write(completed.stdout)
            stderr.write(completed.stderr)
            if completed.returncode != 0:
                message = f"Model switch command failed with exit code {completed.returncode}"
                if strict_switch or _config_bool(switch_command.get("required")):
                    raise RuntimeError(message)
                stderr.write(f"WARNING: {message}; continuing with next switch step.\n")
                stderr.flush()

    def _healthcheck(self, profile_config: dict[str, Any]) -> None:
        healthcheck = profile_config.get("healthcheck")
        if not isinstance(healthcheck, dict) or not healthcheck.get("url"):
            return
        payload = {
            "model": healthcheck.get("model", profile_config.get("model", "")),
            "messages": [{"role": "user", "content": "healthcheck"}],
            "max_tokens": 4,
        }
        request = urllib.request.Request(
            str(healthcheck["url"]),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status >= 400:
                    raise RuntimeError(f"Model healthcheck failed with HTTP {response.status}")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Model healthcheck failed: {exc}") from exc

    def _write_git_diff(self, step: StepSpec, run_dir: Path) -> Path | None:
        diff_path = run_dir / "diff.patch"
        args = ["git", "-C", str(self.spec.workspace), "diff", "--"]
        args.extend(step.outputs)
        completed = subprocess.run(args, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if completed.returncode != 0:
            diff_path.write_text(completed.stderr, encoding="utf-8")
            return diff_path
        diff_path.write_text(completed.stdout, encoding="utf-8")
        return diff_path

    def _snapshot_artifacts(self, step: StepSpec, run_id: str, diff_path: Path | None) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        artifact_root = self.spec.engine_dir / "artifacts" / run_id
        artifact_root.mkdir(parents=True, exist_ok=True)
        for output in step.outputs:
            output_path = self.spec.workspace / output
            if not output_path.exists():
                artifacts.append({"path": output, "kind": "missing", "sha256": None, "diff_path": str(diff_path) if diff_path else None})
                continue
            target = artifact_root / output
            if output_path.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(output_path, target, ignore=shutil.ignore_patterns(".git", ".engine", "node_modules", ".venv", "__pycache__", "dist", "build"))
                artifacts.append({"path": output, "kind": "directory", "sha256": None, "diff_path": str(diff_path) if diff_path else None})
            elif output_path.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(output_path, target)
                artifacts.append({"path": output, "kind": "file", "sha256": sha256_file(output_path), "diff_path": str(diff_path) if diff_path else None})
        return artifacts

    def _write_result(
        self,
        run_dir: Path,
        status: str,
        exit_code: int | None,
        stdout_path: Path,
        stderr_path: Path,
        prompt_path: Path | None,
        diff_path: Path | None,
        artifacts: list[dict[str, Any]],
    ) -> WorkerResult:
        result_path = run_dir / "result.json"
        result = {
            "status": status,
            "exit_code": exit_code,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "prompt_path": str(prompt_path) if prompt_path else None,
            "diff_path": str(diff_path) if diff_path else None,
            "artifacts": artifacts,
        }
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        return WorkerResult(status, exit_code, stdout_path, stderr_path, prompt_path, result_path, diff_path, artifacts)


def _config_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _hermes_profile_args(base_command: list[str], hermes_profile: str, extra_args: list[Any]) -> list[str]:
    if not hermes_profile:
        return []
    combined_args = [str(arg) for arg in [*base_command[1:], *extra_args]]
    if "-p" in combined_args or "--profile" in combined_args or any(arg.startswith("--profile=") for arg in combined_args):
        return []
    if base_command and Path(base_command[0]).name == hermes_profile:
        return []
    return ["-p", hermes_profile]


def _switch_commands(profile_config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_commands = profile_config.get("switch_commands")
    if raw_commands is None:
        raw_commands = profile_config.get("switch_command")
    if not raw_commands:
        return []
    if isinstance(raw_commands, str):
        return [{"command": raw_commands}]
    if not isinstance(raw_commands, list):
        raise RuntimeError("Profile switch_commands must be a string or list")

    commands: list[dict[str, Any]] = []
    for index, raw_command in enumerate(raw_commands, start=1):
        if isinstance(raw_command, str):
            if raw_command.strip():
                commands.append({"command": raw_command})
            continue
        if isinstance(raw_command, dict):
            command = raw_command.get("command")
            if not command:
                raise RuntimeError(f"Profile switch_commands step {index} is missing command")
            commands.append({**raw_command, "command": str(command)})
            continue
        raise RuntimeError(f"Profile switch_commands step {index} must be a string or mapping")
    return commands
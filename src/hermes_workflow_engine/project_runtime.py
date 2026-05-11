from __future__ import annotations

import os
import json
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import HWEConfig, load_config
from .project_storage import ProjectStorage, TASK_DONE_STATUSES


@dataclass(frozen=True)
class ProjectRunSummary:
    project_id: str
    workitem_id: str
    workflow_id: str
    tasks_started: int
    tasks_succeeded: int
    tasks_failed: int
    waiting_for_human: int
    blocked: list[str]
    failed: list[str]
    open: list[str]


class ProjectRuntime:
    def __init__(self, storage: ProjectStorage, *, dry_run: bool = False, config: HWEConfig | None = None):
        self.storage = storage
        self.dry_run = dry_run
        self.config = load_config() if config is None else config

    def run_workitem(
        self,
        project_id: str,
        workitem_id: str,
        *,
        worker_id: str = "hwe-runner",
        profile: str | None = None,
        max_tasks: int | None = None,
    ) -> ProjectRunSummary:
        workflow = self.storage.current_workflow_for_workitem(project_id, workitem_id)
        workflow_id = workflow["id"]
        tasks_started = 0
        tasks_succeeded = 0
        tasks_failed = 0
        waiting_for_human = 0

        while max_tasks is None or tasks_started < max_tasks:
            task = self.storage.claim_next_task(workflow_id, worker_id=worker_id, profile=profile)
            if task is None:
                break
            tasks_started += 1
            status = self.run_task(task)
            if status == "succeeded":
                tasks_succeeded += 1
            elif status in {"waiting_for_info", "waiting_for_approval"}:
                waiting_for_human += 1
                break
            else:
                tasks_failed += 1
                break

        tasks = self.storage.list_tasks(workflow_id)
        failed = [task["id"] for task in tasks if task["status"] in {"failed", "cancelled"}]
        blocked = [task["id"] for task in tasks if task["status"] == "pending"]
        open_tasks = [task["id"] for task in tasks if task["status"] not in TASK_DONE_STATUSES and task["status"] not in {"failed", "cancelled"}]
        return ProjectRunSummary(project_id, workitem_id, workflow_id, tasks_started, tasks_succeeded, tasks_failed, waiting_for_human, blocked, failed, open_tasks)

    def run_task(self, task: dict[str, Any]) -> str:
        run = self.storage.create_task_run(task["id"], claim_id=task.get("claim_id"), profile=task.get("profile"))
        run_dir = self.storage.engine_dir / "runs" / run["id"]
        run_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        prompt_path = run_dir / "prompt.md"

        if task["kind"] == "command":
            status, exit_code, result = self._run_command_task(task, stdout_path, stderr_path)
            prompt_for_run = None
        elif task["kind"] == "http_check":
            status, exit_code, result = self._run_http_check_task(task, stdout_path, stderr_path)
            prompt_for_run = None
        else:
            prompt_text = self._build_prompt(task)
            prompt_path.write_text(prompt_text, encoding="utf-8")
            status, exit_code, result = self._run_agent_task(task, prompt_text, stdout_path, stderr_path)
            prompt_for_run = prompt_path

        self.storage.finish_task_run(
            run["id"],
            status=status,
            exit_code=exit_code,
            result=result,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            prompt_path=prompt_for_run,
        )
        self.storage.complete_task(task["id"], status=status, result={"run_id": run["id"], **result})
        return status

    def _run_command_task(self, task: dict[str, Any], stdout_path: Path, stderr_path: Path) -> tuple[str, int | None, dict[str, Any]]:
        command = (task.get("prompt_text") or "").strip()
        if not command:
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text("Command task has no --prompt-text shell command.\n", encoding="utf-8")
            return "failed", None, {"error": "missing_command"}
        if self.dry_run:
            stdout_path.write_text(f"DRY RUN: would run command: {command}\n", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            return "succeeded", 0, {"dry_run": True, "command": command}

        completed = subprocess.run(
            command,
            cwd=self.storage.project_root,
            shell=True,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
        status = "succeeded" if completed.returncode == 0 else "failed"
        return status, completed.returncode, {"command": command}

    def _run_http_check_task(self, task: dict[str, Any], stdout_path: Path, stderr_path: Path) -> tuple[str, int | None, dict[str, Any]]:
        try:
            spec = self._http_check_spec(task)
        except ValueError as exc:
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text(f"{exc}\n", encoding="utf-8")
            return "failed", None, {"error": str(exc)}

        if self.dry_run:
            stdout_path.write_text(f"DRY RUN: would run {len(spec)} HTTP check(s)\n", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            return "succeeded", 0, {"dry_run": True, "checks": len(spec)}

        results: list[dict[str, Any]] = []
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        for index, check in enumerate(spec, start=1):
            ok, result, detail = self._run_single_http_check(check)
            results.append(result)
            stdout_lines.append(f"[{index}] {result['method']} {result['url']} -> {result.get('status')} {result['status_text']}")
            if detail:
                stdout_lines.append(detail)
            if not ok:
                stderr_lines.append(result["error"])

        stdout_path.write_text("\n".join(stdout_lines) + ("\n" if stdout_lines else ""), encoding="utf-8")
        stderr_path.write_text("\n".join(stderr_lines) + ("\n" if stderr_lines else ""), encoding="utf-8")
        status = "succeeded" if not stderr_lines else "failed"
        return status, 0 if status == "succeeded" else 1, {"checks": results}

    def _http_check_spec(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        raw = (task.get("prompt_text") or "").strip()
        if not raw:
            raise ValueError("HTTP check task has no --prompt-text URL or JSON spec.")
        if raw.startswith("http://") or raw.startswith("https://"):
            return [{"url": raw}]
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"HTTP check prompt is not a URL or JSON: {exc}") from exc
        checks = parsed.get("requests", parsed if isinstance(parsed, list) else [parsed])
        if not isinstance(checks, list) or not checks:
            raise ValueError("HTTP check JSON must define at least one request.")
        normalized = []
        for check in checks:
            if not isinstance(check, dict) or not check.get("url"):
                raise ValueError("Each HTTP check request must be an object with a url.")
            normalized.append(check)
        return normalized

    def _run_single_http_check(self, check: dict[str, Any]) -> tuple[bool, dict[str, Any], str]:
        method = str(check.get("method", "GET")).upper()
        url = str(check["url"])
        headers = {str(key): str(value) for key, value in check.get("headers", {}).items()} if isinstance(check.get("headers", {}), dict) else {}
        body = None
        if "json" in check:
            body = json.dumps(check["json"]).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif "body" in check:
            body = str(check["body"]).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        expect_status = int(check.get("expect_status", 200))
        retries = int(check.get("retries", 5))
        retry_delay_seconds = float(check.get("retry_delay_seconds", 1))
        timeout = float(check.get("timeout_seconds", 30))
        last_result: dict[str, Any] = {"method": method, "url": url, "status": None, "status_text": "failed", "error": "not attempted"}
        last_detail = ""
        for attempt in range(max(1, retries)):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    response_text = response.read().decode("utf-8", errors="replace")
                    last_result, last_detail = self._evaluate_http_response(check, method, url, response.status, response_text, expect_status)
            except urllib.error.HTTPError as exc:
                response_text = exc.read().decode("utf-8", errors="replace")
                last_result, last_detail = self._evaluate_http_response(check, method, url, exc.code, response_text, expect_status)
            except urllib.error.URLError as exc:
                last_result = {"method": method, "url": url, "status": None, "status_text": "failed", "error": str(exc)}
                last_detail = ""
            if last_result["status_text"] == "ok":
                return True, last_result, last_detail
            if attempt < retries - 1:
                time.sleep(retry_delay_seconds)
        return False, last_result, last_detail

    def _evaluate_http_response(self, check: dict[str, Any], method: str, url: str, status: int, response_text: str, expect_status: int) -> tuple[dict[str, Any], str]:
        result: dict[str, Any] = {"method": method, "url": url, "status": status, "status_text": "ok"}
        errors: list[str] = []
        if status != expect_status:
            errors.append(f"expected HTTP {expect_status}, got {status}")
        if "expect_contains" in check and str(check["expect_contains"]) not in response_text:
            errors.append("response did not contain expected text")
        if "expect_json" in check:
            try:
                response_json = json.loads(response_text)
            except json.JSONDecodeError:
                errors.append("response was not JSON")
            else:
                expected = check["expect_json"]
                if isinstance(expected, dict) and isinstance(response_json, dict):
                    for key, value in expected.items():
                        if response_json.get(key) != value:
                            errors.append(f"JSON field {key!r} expected {value!r}, got {response_json.get(key)!r}")
                elif response_json != expected:
                    errors.append("response JSON did not equal expected JSON")
        detail = response_text[:4096]
        if errors:
            result["status_text"] = "failed"
            result["error"] = "; ".join(errors)
        return result, detail

    def _run_agent_task(
        self,
        task: dict[str, Any],
        prompt_text: str,
        stdout_path: Path,
        stderr_path: Path,
    ) -> tuple[str, int | None, dict[str, Any]]:
        profile_name = task.get("profile") or "default"
        profile_config = self.config.profile_config(profile_name)
        command = self._hermes_command_args(profile_name, profile_config, prompt_text)
        if self.dry_run:
            stdout_path.write_text(f"DRY RUN: would invoke {' '.join(shlex.quote(part) for part in command)}\n", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            return "succeeded", 0, {"dry_run": True, "profile": profile_name}

        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            try:
                self._run_switch_command(profile_config, stdout, stderr)
                self._healthcheck(profile_config)
            except RuntimeError as exc:
                stderr.write(f"{exc}\n")
                return "failed", None, {"profile": profile_name, "error": str(exc)}

            completed = subprocess.run(
                command,
                cwd=self.storage.project_root,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=int(profile_config.get("timeout_seconds", 3600)),
            )
            stdout.write(completed.stdout)
            stderr.write(completed.stderr)

        status = "succeeded" if self._is_success_exit_code(completed.returncode, profile_config) else "failed"
        return status, completed.returncode, {"profile": profile_name}

    def _build_prompt(self, task: dict[str, Any]) -> str:
        workitem = self.storage.get_workitem(task["workitem_id"])
        parts: list[str] = []
        template_id = task.get("prompt_template_id")
        if template_id:
            template = self.storage.get_role_prompt_template(template_id)
            parts.append(template["body_md"].rstrip())
        if task.get("prompt_text"):
            parts.append(str(task["prompt_text"]).rstrip())

        metadata = [
            "# HWE Project Task",
            "",
            f"Project root: {self.storage.project_root}",
            f"Workitem: {workitem['title']}",
            f"Task: {task['title']}",
            f"Kind: {task['kind']}",
            f"Profile: {task.get('profile') or 'default'}",
            f"Risk: {task['risk_level']}",
            "",
            "## Requirements",
            workitem.get("requirements_md") or "(none)",
            "",
            "## Constraints",
            workitem.get("constraints_md") or "(none)",
            "",
            "## Declared Skills",
            "\n".join(f"- {skill}" for skill in task.get("skills", [])) or "(none)",
            "",
            "## Expected Outputs",
            "\n".join(f"- {output}" for output in task.get("outputs", [])) or "(none)",
            "",
            "## Gates",
            "\n".join(f"- {gate}" for gate in task.get("gates", [])) or "(none)",
            "",
            "If required information is missing, stop and request a human action instead of guessing.",
        ]
        parts.append("\n".join(metadata))
        return "\n\n".join(part for part in parts if part.strip())

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
        return [*base_command, "chat", "-Q", "--source", "workflow-engine", *[str(arg) for arg in extra_args], "-q", prompt_text]

    def _run_switch_command(self, profile_config: dict[str, Any], stdout: Any, stderr: Any) -> None:
        switch_command = profile_config.get("switch_command")
        if not switch_command:
            return
        stdout.write(f"$ {switch_command}\n")
        stdout.flush()
        completed = subprocess.run(
            str(switch_command),
            cwd=self.storage.project_root,
            shell=True,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=int(profile_config.get("switch_timeout_seconds", 900)),
        )
        stdout.write(completed.stdout)
        stderr.write(completed.stderr)
        if completed.returncode != 0:
            raise RuntimeError(f"Model switch command failed with exit code {completed.returncode}")

    def _healthcheck(self, profile_config: dict[str, Any]) -> None:
        healthcheck = profile_config.get("healthcheck")
        if not isinstance(healthcheck, dict) or not healthcheck.get("url"):
            return
        retries = int(healthcheck.get("retries", 5))
        retry_delay_seconds = float(healthcheck.get("retry_delay_seconds", 2))
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
        last_error: Exception | None = None
        for attempt in range(max(1, retries)):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    if response.status < 400:
                        return
                    last_error = RuntimeError(f"Model healthcheck failed with HTTP {response.status}")
            except urllib.error.URLError as exc:
                last_error = exc
            if attempt < retries - 1:
                time.sleep(retry_delay_seconds)
        raise RuntimeError(f"Model healthcheck failed: {last_error}")

    def _is_success_exit_code(self, exit_code: int, profile_config: dict[str, Any]) -> bool:
        success_exit_codes = profile_config.get("success_exit_codes", [0])
        if not isinstance(success_exit_codes, list):
            success_exit_codes = [0]
        allowed = {int(code) for code in success_exit_codes if isinstance(code, int) or str(code).lstrip("-").isdigit()}
        return exit_code in allowed

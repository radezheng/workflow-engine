from __future__ import annotations

import os
import json
import shlex
import shutil
import subprocess
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import HWEConfig, load_config
from .project_storage import ProjectStorage, ProjectStorageError, TASK_DONE_STATUSES


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
        self.storage.event(
            project_id,
            workitem_id,
            workflow_id,
            None,
            "workitem_run_requested",
            {"worker_id": worker_id, "profile": profile, "max_tasks": max_tasks},
        )

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
        summary = ProjectRunSummary(project_id, workitem_id, workflow_id, tasks_started, tasks_succeeded, tasks_failed, waiting_for_human, blocked, failed, open_tasks)
        event_type = "workitem_run_no_ready_task" if tasks_started == 0 else "workitem_run_completed"
        self.storage.event(project_id, workitem_id, workflow_id, None, event_type, summary.__dict__)
        return summary

    def run_one_task(self, project_id: str, task_id: str, *, worker_id: str = "hwe-runner", profile: str | None = None) -> ProjectRunSummary:
        task = self.storage.get_task(task_id)
        if task["project_id"] != project_id:
            raise ProjectStorageError("Task does not belong to project.")
        self.storage.event(project_id, task["workitem_id"], task["workflow_id"], task_id, "task_run_requested", {"worker_id": worker_id, "profile": profile})
        running_task = self.storage.claim_task(task_id, worker_id=worker_id, profile=profile)
        status = self.run_task(running_task)
        tasks = self.storage.list_tasks(task["workflow_id"])
        failed = [item["id"] for item in tasks if item["status"] in {"failed", "cancelled"}]
        blocked = [item["id"] for item in tasks if item["status"] == "pending"]
        open_tasks = [item["id"] for item in tasks if item["status"] not in TASK_DONE_STATUSES and item["status"] not in {"failed", "cancelled"}]
        summary = ProjectRunSummary(
            project_id=project_id,
            workitem_id=task["workitem_id"],
            workflow_id=task["workflow_id"],
            tasks_started=1,
            tasks_succeeded=1 if status == "succeeded" else 0,
            tasks_failed=0 if status in {"succeeded", "waiting_for_info", "waiting_for_approval"} else 1,
            waiting_for_human=1 if status in {"waiting_for_info", "waiting_for_approval"} else 0,
            blocked=blocked,
            failed=failed,
            open=open_tasks,
        )
        self.storage.event(project_id, task["workitem_id"], task["workflow_id"], task_id, "task_run_completed", summary.__dict__)
        return summary

    def run_task(self, task: dict[str, Any]) -> str:
        run = self.storage.create_task_run(task["id"], claim_id=task.get("claim_id"), profile=task.get("profile"))
        run_dir = self.storage.engine_dir / "runs" / run["id"]
        run_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        prompt_path = run_dir / "prompt.md"
        self.storage.update_task_run_paths(run["id"], stdout_path=stdout_path, stderr_path=stderr_path)
        prompt_for_run = None

        try:
            if task["kind"] == "command":
                status, exit_code, result = self._run_command_task(task, stdout_path, stderr_path)
            elif task["kind"] == "http_check":
                status, exit_code, result = self._run_http_check_task(task, stdout_path, stderr_path)
            else:
                prompt_text = self.build_task_prompt(task)
                prompt_path.write_text(prompt_text, encoding="utf-8")
                self.storage.update_task_run_paths(run["id"], prompt_path=prompt_path)
                status, exit_code, result = self._run_agent_task(task, prompt_text, stdout_path, stderr_path)
                prompt_for_run = prompt_path
        except (RuntimeError, OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
            status = "failed"
            exit_code = None
            result = {"error": "runtime_exception", "type": type(exc).__name__, "message": str(exc)}
            with stderr_path.open("a", encoding="utf-8") as stderr:
                stderr.write("Unhandled HWE task runtime exception.\n")
                stderr.write("".join(traceback.format_exception(exc)))

        human_action_title = result.pop("_human_action_title", None)
        human_action_body = result.pop("_human_action_body", None)
        human_action_questions = result.pop("_human_action_questions", None)
        human_action_evidence = result.pop("_human_action_evidence", None)
        self.storage.finish_task_run(
            run["id"],
            status=status,
            exit_code=exit_code,
            result=result,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            prompt_path=prompt_for_run,
        )
        self.storage.complete_task(
            task["id"],
            status=status,
            result={"run_id": run["id"], **result},
            human_action_title=human_action_title,
            human_action_body=human_action_body,
            questions=human_action_questions,
            evidence=human_action_evidence,
            requested_by=task.get("profile"),
            run_id=run["id"],
        )
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

        header = _command_log_header(kind="command", cwd=self.storage.project_root, command=command)

        completed = subprocess.run(
            command,
            cwd=self.storage.project_root,
            shell=True,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout_path.write_text(f"{header}{completed.stdout}{_exit_code_log(completed.returncode)}", encoding="utf-8")
        stderr_path.write_text(f"{header}{completed.stderr}{_exit_code_log(completed.returncode)}", encoding="utf-8")
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
        stdout_lines: list[str] = [_command_log_header(kind="http_check", cwd=self.storage.project_root, command=_http_check_command_for_log(spec)).rstrip()]
        stderr_lines: list[str] = []
        for index, check in enumerate(spec, start=1):
            ok, result, detail = self._run_single_http_check(check)
            results.append(result)
            stdout_lines.append(f"[{index}] {result['method']} {result['url']} -> {result.get('status')} {result['status_text']}")
            if detail:
                stdout_lines.append(detail)
            if not ok:
                stderr_lines.append(result["error"])

        status = "succeeded" if not stderr_lines else "failed"
        exit_code = 0 if status == "succeeded" else 1
        stdout_path.write_text("\n".join(stdout_lines) + f"\n{_exit_code_log(exit_code)}", encoding="utf-8")
        stderr_prefix = _command_log_header(kind="http_check", cwd=self.storage.project_root, command=_http_check_command_for_log(spec))
        stderr_path.write_text(stderr_prefix + "\n".join(stderr_lines) + _exit_code_log(exit_code), encoding="utf-8")
        return status, exit_code, {"checks": results}

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

        timed_out = False
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            header = _command_log_header(
                kind="agent",
                cwd=self.storage.project_root,
                command=_command_for_log(command, stdout_path.parent / "prompt.md"),
                profile=profile_name,
            )
            stdout.write(header)
            stderr.write(header)
            stdout.flush()
            stderr.flush()
            try:
                self._run_switch_command(profile_config, stdout, stderr)
                self._healthcheck(profile_config, stderr=stderr)
            except RuntimeError as exc:
                stderr.write(f"{exc}\n")
                return "failed", None, {"profile": profile_name, "error": str(exc)}

            process = subprocess.Popen(
                command,
                cwd=self.storage.project_root,
                text=True,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
            )
            try:
                return_code = process.wait(timeout=int(profile_config.get("timeout_seconds", 3600)))
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = process.wait()
                timed_out = True
                stderr.write(f"Hermes command timed out after {profile_config.get('timeout_seconds', 3600)} seconds.\n")
                stderr.flush()
            stderr.write(_exit_code_log(return_code))
            stderr.flush()

        if timed_out and _stdout_has_clarify_timeout(stdout_path):
            clarification_path = _write_clarification_file(
                stdout_path.parent,
                prompt_path=stdout_path.parent / "prompt.md",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timeout_seconds=int(profile_config.get("timeout_seconds", 3600)),
            )
            body = (
                "Hermes entered its clarify flow, no interactive answer was available, and the agent later timed out. "
                "The exact clarification question was not emitted to stdout/stderr by Hermes, so inspect the run artifacts before retrying.\n\n"
                f"Clarification note: {clarification_path}\n"
                f"Prompt: {stdout_path.parent / 'prompt.md'}\n"
                f"Stdout: {stdout_path}\n"
                f"Stderr: {stderr_path}"
            )
            return "waiting_for_info", return_code, {
                "profile": profile_name,
                "error": "clarify_timeout",
                "clarification_path": str(clarification_path),
                "_human_action_title": "Hermes clarification timed out",
                "_human_action_body": body,
                "_human_action_questions": [
                    {
                        "id": "clarify-timeout",
                        "question": "Review the run artifacts and provide the missing clarification or direction for retrying this task.",
                    }
                ],
                "_human_action_evidence": [str(clarification_path), str(stdout_path), str(stderr_path), str(stdout_path.parent / "prompt.md")],
            }

        status = "succeeded" if self._is_success_exit_code(return_code, profile_config) else "failed"
        return status, return_code, {"profile": profile_name}

    def build_task_prompt(self, task: dict[str, Any]) -> str:
        workitem = self.storage.get_workitem(task["workitem_id"])
        parts: list[str] = []
        template_ref = task.get("prompt_template_ref")
        if template_ref:
            parts.append(self._prompt_template_body(str(template_ref)).rstrip())
        if task.get("prompt_text"):
            parts.append(str(task["prompt_text"]).rstrip())

        metadata = [
            "# HWE 项目任务",
            "",
            f"项目根目录：{self.storage.project_root}",
            f"Project ID：{task['project_id']}",
            f"Workitem ID：{task['workitem_id']}",
            f"Workflow ID：{task['workflow_id']}",
            f"Task ID：{task['id']}",
            f"Workitem：{workitem['title']}",
            f"任务：{task['title']}",
            f"任务类型：{task['kind']}",
            f"风险等级：{task['risk_level']}",
            "",
            "## HWE 控制面",
            *self._hwe_control_context_lines(),
            "",
            "## 需求",
            workitem.get("requirements_md") or "（无）",
            "",
            "## 约束",
            workitem.get("constraints_md") or "（无）",
            "",
            "## 声明的技能",
            "\n".join(f"- {skill}" for skill in task.get("skills", [])) or "（无）",
            "",
            "## 预期产物",
            "\n".join(f"- {output}" for output in task.get("outputs", [])) or "（无）",
            "",
            "## 验证 Gates",
            "\n".join(f"- {gate}" for gate in task.get("gates", [])) or "（无）",
            "",
            "如果缺少必要信息，请停止并请求 human action，不要猜测。",
        ]
        parts.append("\n".join(metadata))
        return "\n\n".join(part for part in parts if part.strip())

    def _hwe_control_context_lines(self) -> list[str]:
        repo_root = Path(__file__).resolve().parents[2]
        hwe_cli = repo_root / ".venv" / "bin" / "hwe"
        hwe_command = str(hwe_cli) if hwe_cli.exists() else shutil.which("hwe") or "hwe"
        config_path = self.config.source_path or Path(os.environ.get("HWE_CONFIG", repo_root / "hwe.config.yaml"))
        profiles = sorted((self.config.profiles or {}).keys())
        profile_text = ", ".join(profiles) if profiles else "（未配置 profiles；创建 agent task 前必须先检查 HWE config）"
        project_ref = self.storage.project_root.name
        return [
            f"- HWE repo：{repo_root}",
            f"- HWE config：{config_path}",
            f"- HWE CLI：{hwe_command}",
            f"- 可用 HWE profiles：{profile_text}",
            "- 运行 HWE 控制命令时使用仓库根目录和显式 config，例如：",
            f"  `cd {shlex.quote(str(repo_root))} && HWE_CONFIG={shlex.quote(str(config_path))} {shlex.quote(hwe_command)} task list {shlex.quote(project_ref)} <workflow-id>`",
            "- 创建任务只能分配给上面列出的真实 profile；不要使用未配置的 researcher/architect/developer/analyst 等虚构 profile。",
            "- 需要用户输入时，使用 `hwe human-action create` 创建真正的 HWE human action；不要用 `hwe task create --kind human-action` 伪造人工任务。",
            "- 创建后续任务时使用 `hwe task create <project> <workflow-id> <title> --kind ... --profile ... --depends-on ... --prompt-template-ref ...`，并用真实 task id 作为依赖。",
        ]

    def _prompt_template_body(self, template_ref: str) -> str:
        safe_ref = template_ref.strip().removesuffix(".md")
        if not safe_ref or safe_ref.startswith("/") or ".." in Path(safe_ref).parts or len(Path(safe_ref).parts) != 2:
            raise RuntimeError(f"Invalid prompt template ref: {template_ref}")
        relative_path = Path(safe_ref).with_suffix(".md")
        candidates = [
            self.storage.engine_dir / "prompt-templates" / relative_path,
            self.config.prompt_template_root / relative_path if self.config.prompt_template_root else None,
        ]
        for candidate in candidates:
            if candidate and candidate.exists():
                return candidate.read_text(encoding="utf-8")
        raise RuntimeError(f"Prompt template not found: {template_ref}")

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
                cwd=self.storage.project_root,
                shell=True,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=int(switch_command.get("timeout_seconds", profile_config.get("switch_timeout_seconds", 900))),
            )
            stdout.write(completed.stdout)
            stderr.write(completed.stderr)
            if completed.returncode != 0:
                message = f"Model switch command failed with exit code {completed.returncode}"
                if strict_switch or _config_bool(switch_command.get("required")):
                    raise RuntimeError(message)
                stderr.write(f"WARNING: {message}; continuing with next switch step.\n")
                stderr.flush()

    def _healthcheck(self, profile_config: dict[str, Any], *, stderr: Any | None = None) -> None:
        healthcheck = profile_config.get("healthcheck")
        if not isinstance(healthcheck, dict) or not healthcheck.get("url"):
            return
        retries = int(healthcheck.get("retries", 5))
        retry_delay_seconds = float(healthcheck.get("retry_delay_seconds", 2))
        timeout_seconds = float(healthcheck.get("timeout_seconds", healthcheck.get("timeout", 30)))
        url = str(healthcheck["url"])
        model = healthcheck.get("model", profile_config.get("model", ""))
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "healthcheck"}],
            "max_tokens": 4,
        }
        last_error: Exception | None = None
        for attempt in range(max(1, retries)):
            if stderr is not None:
                stderr.write(f"Healthcheck attempt {attempt + 1}/{max(1, retries)}: {url} model={model} timeout={timeout_seconds}s\n")
                stderr.flush()
            try:
                request = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                    if response.status < 400:
                        if stderr is not None:
                            stderr.write(f"Healthcheck succeeded with HTTP {response.status}.\n")
                            stderr.flush()
                        return
                    last_error = RuntimeError(f"Model healthcheck failed with HTTP {response.status}")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
            if stderr is not None and last_error is not None:
                stderr.write(f"Healthcheck failed on attempt {attempt + 1}: {last_error}\n")
                stderr.flush()
            if attempt < retries - 1:
                time.sleep(retry_delay_seconds)
        raise RuntimeError(f"Model healthcheck failed: {last_error}")

    def _is_success_exit_code(self, exit_code: int, profile_config: dict[str, Any]) -> bool:
        success_exit_codes = profile_config.get("success_exit_codes", [0])
        if not isinstance(success_exit_codes, list):
            success_exit_codes = [0]
        allowed = {int(code) for code in success_exit_codes if isinstance(code, int) or str(code).lstrip("-").isdigit()}
        return exit_code in allowed


def _config_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


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


def _hermes_profile_args(base_command: list[str], hermes_profile: str, extra_args: list[Any]) -> list[str]:
    if not hermes_profile:
        return []
    combined_args = [str(arg) for arg in [*base_command[1:], *extra_args]]
    if "-p" in combined_args or "--profile" in combined_args or any(arg.startswith("--profile=") for arg in combined_args):
        return []
    if base_command and Path(base_command[0]).name == hermes_profile:
        return []
    return ["-p", hermes_profile]


def _command_log_header(*, kind: str, cwd: Path, command: str, profile: str | None = None) -> str:
    lines = ["# HWE run", f"kind: {kind}", f"cwd: {cwd}"]
    if profile:
        lines.append(f"profile: {profile}")
    lines.append(f"$ {command}")
    return "\n".join(lines) + "\n\n"


def _command_for_log(command: list[str], prompt_path: Path) -> str:
    visible = list(command)
    for index, part in enumerate(visible[:-1]):
        if part == "-q":
            visible[index + 1] = str(prompt_path)
            break
    return " ".join(shlex.quote(part) for part in visible)


def _http_check_command_for_log(spec: list[dict[str, Any]]) -> str:
    if len(spec) == 1:
        check = spec[0]
        return f"http_check {str(check.get('method', 'GET')).upper()} {check.get('url')}"
    return f"http_check {len(spec)} requests"


def _exit_code_log(exit_code: int | None) -> str:
    return f"\n# HWE exit_code: {exit_code}\n"


def _stdout_has_clarify_timeout(stdout_path: Path) -> bool:
    try:
        stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "clarify timed out" in stdout_text.lower()


def _write_clarification_file(run_dir: Path, *, prompt_path: Path, stdout_path: Path, stderr_path: Path, timeout_seconds: int) -> Path:
    clarification_path = run_dir / "clarification.md"
    clarification_path.write_text(
        "\n".join(
            [
                "# Hermes Clarification Timeout",
                "",
                f"Hermes reported a clarify timeout and the HWE agent task timed out after {timeout_seconds} seconds.",
                "",
                "HWE could not capture the exact clarification question because Hermes did not emit it to stdout or stderr.",
                "Answer this human action with the missing clarification or with operator direction for retrying/superseding the task.",
                "",
                "## Run Artifacts",
                "",
                f"- Prompt: {prompt_path}",
                f"- Stdout: {stdout_path}",
                f"- Stderr: {stderr_path}",
                "",
                "## Stdout Tail",
                "",
                "```text",
                _tail_text(stdout_path),
                "```",
                "",
                "## Stderr Tail",
                "",
                "```text",
                _tail_text(stderr_path),
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return clarification_path


def _tail_text(path: Path, *, limit: int = 4000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-limit:]

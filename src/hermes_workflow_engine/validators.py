from __future__ import annotations

import json
import py_compile
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from .spec import StepSpec, WorkflowSpec


GateResult = dict[str, Any]

SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|access[_-]?key)\s*[:=]\s*(['\"])(?!\2)[^'\"]{3,}\2"
)
DB_USER_FORBIDDEN_RE = re.compile(r"(?i)DB_USER\s*[:=]\s*(['\"])(hindsight_user|postgres|root|admin)\1")
FORBIDDEN_DB_USERNAME_LITERAL_RE = re.compile(
    r"(?i)(PGUSER|DB_USER|database\s+user|username|user)\W{0,40}(['\"])(hindsight_user|postgres|root|admin)\2"
)
PLACEHOLDER_RE = re.compile(r"(?i)\b(todo|fixme|placeholder|fake|sample data|mock data|notimplemented|pass\s*(#.*)?$)\b", re.MULTILINE)
EXTERNAL_MUTATION_RE = re.compile(r"(?i)\b(docker\s+(exec|inspect|rm|stop)|kubectl\s+(apply|delete|exec)|curl\s+-X\s*(POST|PUT|PATCH|DELETE))\b")


class ValidationEngine:
    def __init__(self, spec: WorkflowSpec):
        self.spec = spec
        self.validators: dict[str, Callable[[StepSpec, str], GateResult]] = {
            "git_initialized": self.git_initialized,
            "planning_docs_complete": self.planning_docs_complete,
            "external_services_declared": self.external_services_declared,
            "no_hardcoded_credentials": self.no_hardcoded_credentials,
            "no_external_service_mutation": self.no_external_service_mutation,
            "no_placeholder_ingestion": self.no_placeholder_ingestion,
            "source_evidence_required": self.source_evidence_required,
            "python_syntax_ok": self.python_syntax_ok,
            "node_build_ok": self.node_build_ok,
            "review_result_parseable": self.review_result_parseable,
            "no_untracked_debug_artifacts": self.no_untracked_debug_artifacts,
        }

    def run(self, step: StepSpec, run_id: str) -> list[GateResult]:
        results: list[GateResult] = []
        for gate in step.all_gates:
            validator = self.validators.get(gate)
            if validator is None:
                results.append(_result(gate, "skipped", "info", [{"message": "No validator plugin is registered for this gate."}]))
                continue
            results.append(validator(step, run_id))
        return results

    def git_initialized(self, _step: StepSpec, _run_id: str) -> GateResult:
        if (self.spec.workspace / ".git").exists():
            return _result("git_initialized", "passed")
        return _result("git_initialized", "failed", findings=[{"path": ".git", "message": "Workspace is not a git repository."}])

    def planning_docs_complete(self, _step: StepSpec, _run_id: str) -> GateResult:
        required = [self.spec.workspace / "docs" / "requirements.md", self.spec.workspace / "docs" / "design.md"]
        findings = []
        for path in required:
            if not path.exists() or len(path.read_text(encoding="utf-8", errors="replace").strip()) < 40:
                findings.append({"path": _rel(path, self.spec.workspace), "message": "Required planning document is missing or too small."})
        return _result("planning_docs_complete", "failed" if findings else "passed", findings=findings)

    def external_services_declared(self, step: StepSpec, _run_id: str) -> GateResult:
        files = _candidate_files(self.spec, step)
        haystack = "\n".join(_read_text(path) for path in files)
        if re.search(r"(?i)external services?:|external_service|database|docker|api|cloud|service:", haystack):
            return _result("external_services_declared", "passed")
        return _result(
            "external_services_declared",
            "warning",
            "warning",
            [{"message": "No explicit external service declaration was found in candidate outputs."}],
        )

    def no_hardcoded_credentials(self, step: StepSpec, _run_id: str) -> GateResult:
        findings = []
        for path in _candidate_files(self.spec, step):
            text = _read_text(path)
            if SECRET_ASSIGNMENT_RE.search(text):
                findings.append({"path": _rel(path, self.spec.workspace), "message": "Potential hard-coded secret assignment."})
            if DB_USER_FORBIDDEN_RE.search(text):
                findings.append({"path": _rel(path, self.spec.workspace), "message": "DB_USER defaults to a privileged or external-service username."})
            if FORBIDDEN_DB_USERNAME_LITERAL_RE.search(text):
                findings.append({"path": _rel(path, self.spec.workspace), "message": "Potential hard-coded database username literal."})
        return _result("no_hardcoded_credentials", "failed" if findings else "passed", findings=findings)

    def no_external_service_mutation(self, step: StepSpec, _run_id: str) -> GateResult:
        findings = []
        for path in _candidate_files(self.spec, step):
            text = _read_text(path)
            if EXTERNAL_MUTATION_RE.search(text):
                findings.append({"path": _rel(path, self.spec.workspace), "message": "Potential external service mutation command found."})
        return _result("no_external_service_mutation", "failed" if findings else "passed", findings=findings)

    def no_placeholder_ingestion(self, step: StepSpec, _run_id: str) -> GateResult:
        findings = []
        for path in _candidate_files(self.spec, step):
            text = _read_text(path)
            if PLACEHOLDER_RE.search(text):
                findings.append({"path": _rel(path, self.spec.workspace), "message": "Placeholder or fake ingestion marker found."})
        return _result("no_placeholder_ingestion", "failed" if findings else "passed", findings=findings)

    def source_evidence_required(self, step: StepSpec, _run_id: str) -> GateResult:
        files = _candidate_files(self.spec, step)
        if not files:
            return _result("source_evidence_required", "blocked_missing_context", findings=[{"message": "No candidate output files exist yet."}])
        haystack = "\n".join(_read_text(path) for path in files)
        if re.search(r"(?i)(source|provenance|citation|evidence|url|sha256)", haystack):
            return _result("source_evidence_required", "passed")
        return _result("source_evidence_required", "failed", findings=[{"message": "No source evidence or provenance marker found in candidate outputs."}])

    def python_syntax_ok(self, step: StepSpec, _run_id: str) -> GateResult:
        findings = []
        python_files = [path for path in _candidate_files(self.spec, step) if path.suffix == ".py"]
        if not python_files:
            return _result("python_syntax_ok", "skipped", "info", [{"message": "No Python output files to validate."}])
        for path in python_files:
            try:
                py_compile.compile(str(path), doraise=True)
            except py_compile.PyCompileError as exc:
                findings.append({"path": _rel(path, self.spec.workspace), "message": str(exc)})
        return _result("python_syntax_ok", "failed" if findings else "passed", findings=findings)

    def node_build_ok(self, _step: StepSpec, _run_id: str) -> GateResult:
        package_json = self.spec.workspace / "package.json"
        if not package_json.exists():
            return _result("node_build_ok", "skipped", "info", [{"message": "No package.json found."}])
        scripts = json.loads(package_json.read_text(encoding="utf-8", errors="replace")).get("scripts", {})
        if "build" not in scripts:
            return _result("node_build_ok", "skipped", "info", [{"message": "No npm build script found."}])
        completed = subprocess.run(["npm", "run", "build"], cwd=self.spec.workspace, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
        if completed.returncode == 0:
            return _result("node_build_ok", "passed")
        return _result("node_build_ok", "failed", findings=[{"message": completed.stderr[-2000:] or completed.stdout[-2000:]}])

    def review_result_parseable(self, _step: StepSpec, run_id: str) -> GateResult:
        stdout_path = self.spec.engine_dir / "runs" / run_id / "stdout.log"
        if not stdout_path.exists():
            return _result("review_result_parseable", "blocked_missing_context", findings=[{"message": "Reviewer stdout is missing."}])
        text = stdout_path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"(?i)\b(approved|needs_change|needs change|rejected|blocked)\b", text):
            return _result("review_result_parseable", "passed")
        return _result("review_result_parseable", "warning", "warning", [{"message": "No explicit review decision token found."}])

    def no_untracked_debug_artifacts(self, _step: StepSpec, _run_id: str) -> GateResult:
        completed = subprocess.run(["git", "-C", str(self.spec.workspace), "status", "--short"], check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if completed.returncode != 0:
            return _result("no_untracked_debug_artifacts", "skipped", "info", [{"message": completed.stderr.strip() or "Not a git repository."}])
        findings = []
        for line in completed.stdout.splitlines():
            path = line[3:]
            if path.startswith(".engine/"):
                continue
            if path.endswith((".log", ".tmp", ".bak")) or path in {".DS_Store"}:
                findings.append({"path": path, "message": "Debug artifact should not remain untracked."})
        return _result("no_untracked_debug_artifacts", "failed" if findings else "passed", findings=findings)


def has_blocking_failures(results: list[GateResult]) -> bool:
    return any(result["status"] in {"failed", "blocked_missing_context"} and result["severity"] == "blocker" for result in results)


def _candidate_files(spec: WorkflowSpec, step: StepSpec) -> list[Path]:
    files: list[Path] = []
    for output in step.outputs:
        path = spec.workspace / output
        if path.exists() and path.is_file():
            files.append(path)
        elif path.exists() and path.is_dir():
            files.extend(_walk_candidate_files(path))
    return files


def _walk_candidate_files(root: Path) -> list[Path]:
    ignored_dirs = {".git", ".engine", "node_modules", ".venv", "__pycache__", ".pytest_cache", "dist", "build"}
    ignored_suffixes = {".pyc", ".pyo", ".log", ".sqlite", ".db"}
    files: list[Path] = []
    for path in root.rglob("*"):
        if any(part in ignored_dirs for part in path.parts):
            continue
        if path.is_file() and path.suffix not in ignored_suffixes:
            files.append(path)
    return files


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() and path.is_file() else ""


def _rel(path: Path, workspace: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)


def _result(gate: str, status: str, severity: str | None = None, findings: list[dict[str, Any]] | None = None) -> GateResult:
    if severity is None:
        severity = "blocker" if status in {"failed", "blocked_missing_context"} else "info"
    return {"gate": gate, "status": status, "severity": severity, "findings": findings or []}
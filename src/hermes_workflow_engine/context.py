from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .spec import StepSpec, WorkflowSpec, resolve_spec_path, resolve_workspace_path


SECRET_VALUE_RE = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|access[_-]?key)\s*[:=]\s*([\"']?)[^\s\"']+\2"
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def redact(text: str) -> str:
    return SECRET_VALUE_RE.sub(lambda match: f"{match.group(1)}=<redacted>", text)


class ContextCompiler:
    def __init__(self, spec: WorkflowSpec):
        self.spec = spec

    def compile(self, step: StepSpec, run_id: str, attempt: int) -> tuple[str, Path, Path, dict[str, Any], str]:
        context_dir = self.spec.engine_dir / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        bundle_id = f"ctx_{step.id}_{attempt:03d}"
        bundle_path = context_dir / f"{bundle_id}.md"
        manifest_path = context_dir / f"{bundle_id}.json"

        sections: list[str] = []
        sources: list[dict[str, Any]] = []
        excluded = ["secrets", ".env", ".engine/runs", ".engine/artifacts"]

        sections.append(f"# Context Bundle: {bundle_id}\n")
        sections.append("## Workflow\n")
        sections.append(f"- workflow_id: {self.spec.id}\n")
        sections.append(f"- workspace: {self.spec.workspace}\n")
        sections.append(f"- step_id: {step.id}\n")
        sections.append(f"- step_title: {step.title}\n")
        sections.append(f"- profile: {step.profile or ''}\n")
        sections.append("\n")

        prompt_path = resolve_spec_path(self.spec, step.prompt)
        if prompt_path and prompt_path.exists():
            prompt_text = redact(prompt_path.read_text(encoding="utf-8", errors="replace"))
            sections.append("## Task Prompt\n\n")
            sections.append(prompt_text)
            sections.append("\n\n")
            sources.append(_source("prompt", prompt_path, self.spec.workspace))

        sections.append("## Step Contract\n\n")
        sections.append("```json\n")
        sections.append(json.dumps(_step_contract(step), indent=2, sort_keys=True))
        sections.append("\n```\n\n")

        for path in self._included_paths(step):
            if path.exists() and path.is_file():
                try:
                    text = redact(path.read_text(encoding="utf-8", errors="replace"))
                except OSError as exc:
                    sections.append(f"## Unreadable Source: {path}\n\n{exc}\n\n")
                    continue
                relative = _display_path(path, self.spec.workspace)
                sections.append(f"## Source: {relative}\n\n")
                sections.append("```text\n")
                sections.append(text)
                if not text.endswith("\n"):
                    sections.append("\n")
                sections.append("```\n\n")
                sources.append(_source("file", path, self.spec.workspace))
            else:
                sources.append({"type": "missing_file", "path": str(path)})

        policy_names = self._included_policy_names(step)
        if policy_names:
            sections.append("## Policies\n\n")
            for name in policy_names:
                sections.append(f"### {name}\n\n")
                sections.append(_policy_text(name))
                sections.append("\n")
                sources.append({"type": "policy", "name": name, "version": "0.1.0"})

        content = "".join(sections)
        bundle_sha = sha256_text(content)
        manifest = {
            "id": bundle_id,
            "step_id": step.id,
            "run_id": run_id,
            "token_estimate": max(1, len(content) // 4),
            "sources": sources,
            "excluded": excluded,
            "freshness": "latest",
            "sha256": bundle_sha,
        }

        bundle_path.write_text(content, encoding="utf-8")
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        return bundle_id, bundle_path, manifest_path, manifest, bundle_sha

    def _included_paths(self, step: StepSpec) -> list[Path]:
        paths: list[Path] = []
        include = step.context.get("include", []) if step.context else []
        if isinstance(include, list):
            for item in include:
                if isinstance(item, dict):
                    _collect_paths_from_mapping(item, paths, self.spec)
        explicit_files = step.context.get("files", []) if step.context else []
        if isinstance(explicit_files, list):
            for value in explicit_files:
                if isinstance(value, str):
                    paths.append(resolve_workspace_path(self.spec, value))
        for output in step.outputs:
            output_path = resolve_workspace_path(self.spec, output)
            if output_path.exists():
                paths.append(output_path)
        seen: set[Path] = set()
        unique: list[Path] = []
        for path in paths:
            resolved = path.resolve()
            if resolved not in seen:
                unique.append(resolved)
                seen.add(resolved)
        return unique

    def _included_policy_names(self, step: StepSpec) -> list[str]:
        include = step.context.get("include", []) if step.context else []
        names: list[str] = []
        if isinstance(include, list):
            for item in include:
                if isinstance(item, dict):
                    policies = item.get("policies")
                    if isinstance(policies, list):
                        names.extend(str(policy) for policy in policies)
        names.extend(_policy_names_for_gates(step.all_gates))
        return list(dict.fromkeys(names))


def _collect_paths_from_mapping(mapping: dict[str, Any], paths: list[Path], spec: WorkflowSpec) -> None:
    for key, value in mapping.items():
        if key in {"artifacts.paths", "files", "paths"} and isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    paths.append(resolve_workspace_path(spec, item))
        elif isinstance(value, dict):
            _collect_paths_from_mapping(value, paths, spec)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _collect_paths_from_mapping(item, paths, spec)


def _policy_names_for_gates(gates: list[str]) -> list[str]:
    names: list[str] = []
    if "no_hardcoded_credentials" in gates:
        names.append("credential_handling")
    if "source_evidence_required" in gates:
        names.append("data_provenance")
    if "no_external_service_mutation" in gates:
        names.append("external_service_safety")
    return names


def _policy_text(name: str) -> str:
    policies = {
        "credential_handling": "Do not invent, scrape, echo, or persist credentials. Environment defaults for secrets must be empty or required from the caller.",
        "data_provenance": "Persist source evidence for collected data. Fallback or sample data must be explicitly labeled and must not masquerade as live collection.",
        "external_service_safety": "Do not mutate external services, containers, databases, or cloud resources unless the workflow step explicitly grants mutation authority.",
    }
    return policies.get(name, "Follow the named project policy. If policy details are missing, ask for context instead of guessing.")


def _step_contract(step: StepSpec) -> dict[str, Any]:
    return {
        "id": step.id,
        "title": step.title,
        "kind": step.kind,
        "profile": step.profile,
        "needs": step.needs,
        "locks": step.locks,
        "outputs": step.outputs,
        "gates": step.all_gates,
        "review": step.review,
    }


def _source(source_type: str, path: Path, workspace: Path) -> dict[str, Any]:
    return {
        "type": source_type,
        "path": _display_path(path, workspace),
        "sha256": sha256_file(path),
    }


def _display_path(path: Path, workspace: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)
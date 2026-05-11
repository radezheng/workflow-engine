from __future__ import annotations

import sqlite3
import subprocess
from dataclasses import dataclass

from .context import ContextCompiler
from .spec import StepSpec, WorkflowSpec
from .storage import Storage
from .validators import ValidationEngine, has_blocking_failures
from .worker import WorkerAdapter, WorkerResult


FINAL_SUCCESS_STATES = {"completed", "approved"}
TERMINAL_STATES = FINAL_SUCCESS_STATES | {"failed", "needs_change", "blocked", "canceled"}


@dataclass(frozen=True)
class RunSummary:
    workflow_id: str
    steps_started: int
    steps_succeeded: int
    steps_failed: int
    blocked: list[str]


class WorkflowRuntime:
    def __init__(self, spec: WorkflowSpec, storage: Storage, dry_run: bool = False):
        self.spec = spec
        self.storage = storage
        self.context_compiler = ContextCompiler(spec)
        self.worker = WorkerAdapter(spec, dry_run=dry_run)
        self.validators = ValidationEngine(spec)

    def load(self) -> None:
        self.spec.workspace.mkdir(parents=True, exist_ok=True)
        self.storage.initialize()
        self.storage.upsert_workflow(self.spec)

    def run(self, max_steps: int | None = None) -> RunSummary:
        self.load()
        steps_started = 0
        steps_succeeded = 0
        steps_failed = 0

        while True:
            if max_steps is not None and steps_started >= max_steps:
                break
            step = self._next_ready_step()
            if step is None:
                break
            steps_started += 1
            ok = self._run_step(step)
            if ok:
                steps_succeeded += 1
            else:
                steps_failed += 1

        blocked = [step.id for step in self.spec.steps if self.storage.step_state(self.spec.id, step.id) not in FINAL_SUCCESS_STATES]
        return RunSummary(self.spec.id, steps_started, steps_succeeded, steps_failed, blocked)

    def _next_ready_step(self) -> StepSpec | None:
        for step in self.spec.steps:
            state = self.storage.step_state(self.spec.id, step.id)
            if state in TERMINAL_STATES or state in {"running", "validating", "context_compiling"}:
                continue
            if all(self.storage.step_state(self.spec.id, need) in FINAL_SUCCESS_STATES for need in step.needs):
                self.storage.set_step_state(self.spec.id, step.id, "ready")
                return step
        return None

    def _run_step(self, step: StepSpec) -> bool:
        attempt = self.storage.bump_attempt(self.spec.id, step.id)
        run_id = self.storage.create_run(self.spec.id, step.id, attempt)
        result: WorkerResult | None = None
        try:
            self.storage.set_step_state(self.spec.id, step.id, "context_compiling")
            bundle_id, bundle_path, _manifest_path, manifest, bundle_sha = self.context_compiler.compile(step, run_id, attempt)
            self.storage.record_context_bundle(self.spec.id, step.id, run_id, bundle_id, bundle_path, manifest, bundle_sha)

            self.storage.set_step_state(self.spec.id, step.id, "running")
            if step.kind == "command":
                result = self.worker.run_command_step(step, run_id)
            else:
                result = self.worker.run_agent_step(step, run_id, bundle_path)

            for artifact in result.artifacts:
                self.storage.record_artifact(
                    self.spec.id,
                    step.id,
                    run_id,
                    str(artifact["path"]),
                    str(artifact["kind"]),
                    artifact.get("sha256"),
                    artifact.get("diff_path"),
                )

            self.storage.set_step_state(self.spec.id, step.id, "validating")
            gate_results = self.validators.run(step, run_id)
            for gate_result in gate_results:
                self.storage.record_gate_result(self.spec.id, step.id, run_id, gate_result)

            if result.status != "succeeded":
                self.storage.finish_run(self.spec.id, step.id, run_id, "failed", result.exit_code)
                self.storage.set_step_state(self.spec.id, step.id, "failed")
                return False
            if has_blocking_failures(gate_results):
                self.storage.finish_run(self.spec.id, step.id, run_id, "failed", result.exit_code)
                self.storage.set_step_state(self.spec.id, step.id, "needs_change")
                return False

            final_state = "approved" if step.review.get("mode") in {"inline", "separate_step"} else "completed"
            self.storage.finish_run(self.spec.id, step.id, run_id, "succeeded", result.exit_code)
            self.storage.set_step_state(self.spec.id, step.id, final_state)
            return True
        except (OSError, RuntimeError, ValueError, sqlite3.Error, subprocess.SubprocessError) as exc:
            self.storage.event(self.spec.id, step.id, run_id, "step_exception", {"error": str(exc), "type": type(exc).__name__})
            self.storage.finish_run(self.spec.id, step.id, run_id, "failed", result.exit_code if result else None)
            self.storage.set_step_state(self.spec.id, step.id, "failed")
            return False
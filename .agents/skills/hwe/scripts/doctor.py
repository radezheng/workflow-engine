#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


@dataclass
class Finding:
    level: str
    check: str
    message: str
    fix: str | None = None


class Doctor:
    def __init__(self, *, repo: Path | None, config_path: Path | None, fix: bool) -> None:
        self.repo = repo
        self.config_path = config_path
        self.fix = fix
        self.findings: list[Finding] = []
        self.config: Any | None = None
        self.hwe_executable: str | None = None

    def ok(self, check: str, message: str) -> None:
        self.findings.append(Finding("ok", check, message))

    def warn(self, check: str, message: str, fix: str | None = None) -> None:
        self.findings.append(Finding("warn", check, message, fix))

    def fail(self, check: str, message: str, fix: str | None = None) -> None:
        self.findings.append(Finding("fail", check, message, fix))

    def run(self) -> int:
        self._check_repo()
        self._check_hwe_command()
        self._load_config()
        if self.config is not None:
            self._check_paths()
            self._check_database()
            self._check_profiles()
            self._check_ai_providers()
        self._print_report()
        return 1 if any(item.level == "fail" for item in self.findings) else 0

    def _check_repo(self) -> None:
        if self.repo is None:
            self.repo = discover_repo(Path.cwd())
        if self.repo is None:
            self.fail(
                "repo",
                "Could not find an HWE repository from the current directory.",
                "Run from the HWE repo root, pass --repo, or set HWE_REPO.",
            )
            return
        markers = [self.repo / "pyproject.toml", self.repo / "src" / "hermes_workflow_engine"]
        missing = [str(path) for path in markers if not path.exists()]
        if missing:
            self.fail("repo", f"HWE repo markers are missing: {', '.join(missing)}")
        else:
            self.ok("repo", f"HWE repo: {self.repo}")
        if str(self.repo / "src") not in sys.path:
            sys.path.insert(0, str(self.repo / "src"))

    def _check_hwe_command(self) -> None:
        candidates: list[Path | str] = []
        if os.environ.get("HWE"):
            candidates.append(os.environ["HWE"])
        if self.repo is not None:
            candidates.append(self.repo / ".venv" / "bin" / "hwe")
        path_hwe = shutil.which("hwe")
        if path_hwe:
            candidates.append(path_hwe)
        for candidate in candidates:
            candidate_path = Path(candidate).expanduser() if not isinstance(candidate, Path) else candidate
            if candidate_path.exists() and os.access(candidate_path, os.X_OK):
                self.hwe_executable = str(candidate_path)
                self.ok("hwe-command", f"HWE executable: {self.hwe_executable}")
                return
        if candidates:
            self.warn("hwe-command", "No executable HWE command found among expected candidates.", "Activate the HWE virtualenv or set HWE=/path/to/hwe.")
        else:
            self.warn("hwe-command", "No HWE command found on PATH.", "Install HWE or set HWE=/path/to/hwe.")

    def _load_config(self) -> None:
        if self.config_path is None:
            env_config = os.environ.get("HWE_CONFIG")
            if env_config:
                self.config_path = Path(env_config).expanduser()
            elif self.repo is not None:
                self.config_path = self.repo / "hwe.config.yaml"
        if self.config_path is None:
            self.fail("config", "No HWE config path could be resolved.", "Set HWE_CONFIG or pass --config.")
            return
        if not self.config_path.exists():
            self.fail("config", f"HWE config does not exist: {self.config_path}", "Run `hwe config init` or pass the correct --config path.")
            return
        try:
            from hermes_workflow_engine.config import load_config

            self.config = load_config(self.config_path)
            self.ok("config", f"Loaded HWE config: {self.config_path}")
        except Exception as exc:
            self.fail("config", f"Could not load HWE config: {type(exc).__name__}: {exc}", "Fix the YAML/config validation error first.")

    def _check_paths(self) -> None:
        assert self.config is not None
        workspace = self.config.default_workspace_root
        if workspace is None:
            self.warn("default_workspace_root", "No default workspace root configured.", "Set default_workspace_root if project names should resolve under a workspace.")
        elif workspace.exists():
            self.ok("default_workspace_root", f"Workspace root exists: {workspace}")
        elif self.fix:
            workspace.mkdir(parents=True, exist_ok=True)
            self.ok("default_workspace_root", f"Created workspace root: {workspace}")
        else:
            self.warn("default_workspace_root", f"Workspace root does not exist: {workspace}", "Create it or run doctor with --fix.")

        template_root = self.config.prompt_template_root
        if template_root.exists():
            templates = sorted(template_root.glob("*/*.md"))
            self.ok("prompt_template_root", f"Prompt template root exists with {len(templates)} templates: {template_root}")
        elif self.fix:
            template_root.mkdir(parents=True, exist_ok=True)
            self.ok("prompt_template_root", f"Created prompt template root: {template_root}")
        else:
            self.warn("prompt_template_root", f"Prompt template root does not exist: {template_root}", "Create it, update prompt_template_root, or run doctor with --fix.")

    def _check_database(self) -> None:
        assert self.config is not None
        database = self.config.project_database or {}
        backend = database.get("backend", "sqlite")
        if backend == "sqlite":
            self.ok("project_database", "Using SQLite project storage.")
            return
        if backend != "postgres":
            self.fail("project_database", f"Unsupported backend: {backend}")
            return
        host = database.get("host")
        port = database.get("port", 5432)
        dbname = database.get("database")
        user = database.get("user")
        if not host or not dbname or not user:
            self.fail("project_database", "Postgres backend requires host, database, and user.")
            return
        try:
            with socket.create_connection((host, int(port)), timeout=2):
                self.ok("postgres-socket", f"Postgres port is reachable: {host}:{port}")
        except OSError as exc:
            self.fail("postgres-socket", f"Cannot reach Postgres at {host}:{port}: {exc}", "Start the configured database service or update project_database host/port.")
            return
        password = database.get("password")
        password_env = database.get("password_env")
        if not password and password_env and not os.environ.get(password_env):
            self.fail("postgres-secret", f"password_env is set but environment variable is missing: {password_env}", "Export the variable or use another configured secret source.")
        elif password or password_env or database.get("password_command"):
            self.ok("postgres-secret", "Postgres credential source is configured.")
        else:
            self.warn("postgres-secret", "No Postgres password, password_env, or password_command configured.", "Add a credential source if the database requires authentication.")
        self._check_postgres_login(database)

    def _check_postgres_login(self, database: dict[str, Any]) -> None:
        try:
            import psycopg2
        except Exception:
            self.warn("postgres-login", "psycopg2 is not importable, so login was not checked.", "Install project dependencies in the HWE environment.")
            return
        password = database.get("password")
        if not password and database.get("password_env"):
            password = os.environ.get(database["password_env"])
        if not password and database.get("password_command"):
            self.warn("postgres-login", "password_command is configured; doctor will not execute it automatically.", "Run a manual login check if needed.")
            return
        kwargs = {
            "host": database.get("host"),
            "port": database.get("port", 5432),
            "dbname": database.get("database"),
            "user": database.get("user"),
            "password": password,
            "connect_timeout": 3,
        }
        for key in ("sslmode", "gssencmode"):
            if database.get(key):
                kwargs[key] = database[key]
        try:
            connection = psycopg2.connect(**kwargs)
            connection.close()
            self.ok("postgres-login", "Postgres login succeeded.")
        except Exception as exc:
            self.fail("postgres-login", f"Postgres login failed: {type(exc).__name__}: {exc}", "Fix credentials, database name, schema permissions, sslmode/gssencmode, or server reachability.")

    def _check_profiles(self) -> None:
        assert self.config is not None
        profiles = self.config.profiles or {}
        if not profiles:
            self.warn("profiles", "No HWE profiles configured.", "Add profiles if agent tasks should route through Hermes workers.")
            return
        self.ok("profiles", f"Configured profiles: {', '.join(sorted(profiles))}")
        for name, profile in sorted(profiles.items()):
            if not isinstance(profile, dict):
                self.fail(f"profile:{name}", "Profile config is not a mapping.")
                continue
            command = profile.get("hermes_command") or profile.get("hermes_profile") or name
            command_name = str(command).split()[0]
            if Path(command_name).expanduser().exists() or shutil.which(command_name):
                self.ok(f"profile:{name}:command", f"Hermes command appears available: {command}")
            else:
                self.warn(f"profile:{name}:command", f"Hermes command was not found on PATH: {command}", "Install/configure the profile command or update hermes_command.")
            for switch_command in profile.get("switch_commands") or []:
                if isinstance(switch_command, dict):
                    raw_command = switch_command.get("command", "")
                else:
                    raw_command = str(switch_command)
                if not raw_command.strip():
                    self.warn(f"profile:{name}:switch", "Empty switch command configured.")
                    continue
                executable = shlex.split(raw_command)[0]
                if shutil.which(executable) or Path(executable).expanduser().exists():
                    self.ok(f"profile:{name}:switch", f"Switch command executable found: {executable}")
                else:
                    self.warn(f"profile:{name}:switch", f"Switch command executable not found: {executable}", "Install the tool, update switch_commands, or remove the switch step.")
            healthcheck = profile.get("healthcheck") or {}
            if isinstance(healthcheck, dict) and healthcheck.get("url"):
                self._check_http_url(f"profile:{name}:healthcheck", str(healthcheck["url"]), required=False)

    def _check_ai_providers(self) -> None:
        assert self.config is not None
        providers = self.config.ai_providers or {}
        for name, provider in sorted(providers.items()):
            if not isinstance(provider, dict):
                self.fail(f"ai_provider:{name}", "AI provider config is not a mapping.")
                continue
            if provider.get("api_key_env") and not os.environ.get(provider["api_key_env"]):
                self.warn(f"ai_provider:{name}:secret", f"api_key_env is set but not exported: {provider['api_key_env']}")
            base_url = provider.get("base_url")
            if base_url:
                self._check_http_url(f"ai_provider:{name}:base_url", str(base_url), required=False)

    def _check_http_url(self, check: str, url: str, *, required: bool) -> None:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            self.warn(check, f"Invalid URL: {url}")
            return
        try:
            request = Request(url, method="GET")
            with urlopen(request, timeout=3) as response:
                self.ok(check, f"Reachable URL returned HTTP {response.status}: {url}")
        except Exception as exc:
            method = self.fail if required else self.warn
            method(check, f"URL check failed for {url}: {type(exc).__name__}: {exc}", "Start the service, update the URL/model, or ignore if it is intentionally offline.")

    def _print_report(self) -> None:
        icons = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}
        print("HWE Doctor Report")
        print("=================")
        for item in self.findings:
            print(f"[{icons[item.level]}] {item.check}: {item.message}")
            if item.fix:
                print(f"      fix: {item.fix}")
        failures = sum(1 for item in self.findings if item.level == "fail")
        warnings = sum(1 for item in self.findings if item.level == "warn")
        print(f"\nSummary: {failures} failure(s), {warnings} warning(s), {len(self.findings) - failures - warnings} ok.")
        if failures or warnings:
            print("Ask the user before applying ambiguous or infrastructure-changing fixes. Safe --fix actions are limited to creating configured local directories.")


def discover_repo(start: Path) -> Path | None:
    for directory in (start.resolve(), *start.resolve().parents):
        if (directory / "pyproject.toml").exists() and (directory / "src" / "hermes_workflow_engine").exists():
            return directory
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Check HWE config and current environment.")
    parser.add_argument("--repo", type=Path, default=Path(os.environ["HWE_REPO"]).expanduser() if os.environ.get("HWE_REPO") else None)
    parser.add_argument("--config", type=Path, default=Path(os.environ["HWE_CONFIG"]).expanduser() if os.environ.get("HWE_CONFIG") else None)
    parser.add_argument("--fix", action="store_true", help="Apply safe local fixes such as creating configured directories.")
    args = parser.parse_args()
    return Doctor(repo=args.repo, config_path=args.config, fix=args.fix).run()


if __name__ == "__main__":
    raise SystemExit(main())

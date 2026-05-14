from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when HWE configuration is invalid."""


@dataclass(frozen=True)
class HWEConfig:
    default_workspace_root: Path | None = None
    prompt_template_root: Path | None = None
    project_database: dict[str, Any] | None = None
    profiles: dict[str, Any] | None = None
    ai_providers: dict[str, Any] | None = None
    source_path: Path | None = None
    raw: dict[str, Any] | None = None

    def profile_config(self, profile_name: str) -> dict[str, Any]:
        profiles = self.profiles or {}
        raw_profile = profiles.get(profile_name, {})
        return dict(raw_profile) if isinstance(raw_profile, dict) else {}


def default_config_path() -> Path:
    cwd = Path.cwd().resolve()
    for directory in (cwd, *cwd.parents):
        candidate = directory / "hwe.config.yaml"
        if candidate.exists():
            return candidate
    return cwd / "hwe.config.yaml"


def configured_config_path() -> Path:
    override = os.environ.get("HWE_CONFIG")
    if override:
        return Path(override).expanduser()
    return default_config_path()


def load_config(path: str | Path | None = None) -> HWEConfig:
    config_path = Path(path).expanduser() if path else configured_config_path()
    if not config_path.exists():
        if path or os.environ.get("HWE_CONFIG"):
            raise ConfigError(f"HWE config does not exist: {config_path}")
        return HWEConfig(prompt_template_root=(config_path.parent / "ptemplate").resolve(), profiles={}, source_path=config_path, raw={})

    with config_path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}
    if not isinstance(raw, dict):
        raise ConfigError("HWE config must be a YAML mapping.")

    workspace_value = raw.get("default_workspace_root")
    default_workspace_root: Path | None = None
    if workspace_value is not None:
        if not isinstance(workspace_value, str) or not workspace_value.strip():
            raise ConfigError("`default_workspace_root` must be a non-empty string when provided.")
        default_workspace_root = Path(workspace_value).expanduser().resolve()

    prompt_template_value = raw.get("prompt_template_root", "./ptemplate")
    if not isinstance(prompt_template_value, str) or not prompt_template_value.strip():
        raise ConfigError("`prompt_template_root` must be a non-empty string.")
    prompt_template_root = _resolve_config_path(config_path, prompt_template_value)

    project_database = raw.get("project_database", {})
    if project_database is None:
        project_database = {}
    if not isinstance(project_database, dict):
        raise ConfigError("`project_database` must be a mapping when provided.")
    backend = project_database.get("backend", "sqlite")
    if backend not in {"sqlite", "postgres"}:
        raise ConfigError("`project_database.backend` must be `sqlite` or `postgres`.")
    if backend == "postgres":
        for required_key in ("host", "database", "user"):
            value = project_database.get(required_key)
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(f"Postgres project_database requires non-empty `{required_key}`.")
        port = project_database.get("port", 5432)
        if not isinstance(port, int) or port <= 0:
            raise ConfigError("Postgres project_database `port` must be a positive integer.")
        maxconn = project_database.get("maxconn", 5)
        if not isinstance(maxconn, int) or maxconn <= 0:
            raise ConfigError("Postgres project_database `maxconn` must be a positive integer.")
        schema = project_database.get("schema", "hwe")
        if not isinstance(schema, str) or not schema.strip():
            raise ConfigError("Postgres project_database `schema` must be a non-empty string.")
        for secret_key in ("password", "password_env", "password_command"):
            value = project_database.get(secret_key)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ConfigError(f"Postgres project_database `{secret_key}` must be a non-empty string when provided.")
        for option_key in ("sslmode", "gssencmode"):
            value = project_database.get(option_key)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ConfigError(f"Postgres project_database `{option_key}` must be a non-empty string when provided.")

    profiles = raw.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ConfigError("`profiles` must be a mapping when provided.")

    ai_providers = raw.get("ai_providers", {})
    if not isinstance(ai_providers, dict):
        raise ConfigError("`ai_providers` must be a mapping when provided.")
    for provider_name, provider_config in ai_providers.items():
        if not isinstance(provider_name, str) or not provider_name.strip():
            raise ConfigError("AI provider names must be non-empty strings.")
        if not isinstance(provider_config, dict):
            raise ConfigError(f"AI provider `{provider_name}` must be a mapping.")
        provider_type = provider_config.get("type", "openai_compatible")
        if provider_type != "openai_compatible":
            raise ConfigError(f"AI provider `{provider_name}` has unsupported type: {provider_type}")
        for required_key in ("base_url", "model"):
            value = provider_config.get(required_key)
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(f"AI provider `{provider_name}` requires non-empty `{required_key}`.")

    return HWEConfig(default_workspace_root=default_workspace_root, prompt_template_root=prompt_template_root, project_database=project_database, profiles=profiles, ai_providers=ai_providers, source_path=config_path, raw=raw)


def write_config(config: HWEConfig, path: str | Path | None = None, *, force: bool = False) -> Path:
    config_path = Path(path).expanduser() if path else configured_config_path()
    if config_path.exists() and not force:
        raise ConfigError(f"HWE config already exists: {config_path}")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    raw: dict[str, Any] = dict(config.raw or {})
    if config.default_workspace_root is not None:
        raw["default_workspace_root"] = str(config.default_workspace_root.expanduser())
    if config.prompt_template_root is not None:
        raw["prompt_template_root"] = str(config.prompt_template_root.expanduser())
    if config.project_database:
        raw["project_database"] = config.project_database
    if config.profiles:
        raw["profiles"] = config.profiles
    if config.ai_providers:
        raw["ai_providers"] = config.ai_providers
    with config_path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(raw, file, sort_keys=False)
    return config_path


def _resolve_config_path(config_path: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (config_path.parent / path).resolve()
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
    source_path: Path | None = None
    raw: dict[str, Any] | None = None


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
        return HWEConfig(source_path=config_path, raw={})

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

    return HWEConfig(default_workspace_root=default_workspace_root, source_path=config_path, raw=raw)


def write_config(config: HWEConfig, path: str | Path | None = None, *, force: bool = False) -> Path:
    config_path = Path(path).expanduser() if path else configured_config_path()
    if config_path.exists() and not force:
        raise ConfigError(f"HWE config already exists: {config_path}")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    raw: dict[str, Any] = dict(config.raw or {})
    if config.default_workspace_root is not None:
        raw["default_workspace_root"] = str(config.default_workspace_root.expanduser())
    with config_path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(raw, file, sort_keys=False)
    return config_path
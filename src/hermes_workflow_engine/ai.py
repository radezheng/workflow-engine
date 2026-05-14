from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from .config import HWEConfig


AssistTarget = Literal["project", "workitem", "human_action", "prompt_template"]


class AIProviderError(ValueError):
    """Raised when an AI provider cannot complete an assistant request."""


@dataclass(frozen=True)
class AIProvider:
    name: str
    type: str
    base_url: str
    model: str
    api_key: str | None = None
    api_key_env: str | None = None
    timeout_seconds: float = 60.0

    @property
    def resolved_api_key(self) -> str | None:
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.environ.get(self.api_key_env)
        return None


def list_ai_providers(config: HWEConfig) -> list[dict[str, Any]]:
    providers = []
    for name, raw_provider in sorted((config.ai_providers or {}).items()):
        provider = _provider_from_raw(name, raw_provider)
        providers.append(
            {
                "name": provider.name,
                "type": provider.type,
                "base_url": provider.base_url,
                "model": provider.model,
                "has_api_key": bool(provider.resolved_api_key),
            }
        )
    return providers


def create_ai_assist_response(
    config: HWEConfig,
    *,
    provider_name: str,
    target: AssistTarget,
    messages: list[dict[str, str]],
    draft: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider = _provider_from_config(config, provider_name)
    prompt_messages = _build_messages(config, target, messages, draft, context or {})
    content = _chat_completion(provider, prompt_messages)
    parsed = _parse_json_object(content)
    if not parsed:
        return {"message": content, "draft": draft, "ready": False, "raw": content}
    response_draft = parsed.get("draft")
    return {
        "message": str(parsed.get("message") or parsed.get("assistant_message") or "Draft updated."),
        "draft": response_draft if isinstance(response_draft, dict) else draft,
        "ready": bool(parsed.get("ready", False)),
        "raw": content,
    }


def _provider_from_config(config: HWEConfig, provider_name: str) -> AIProvider:
    raw_provider = (config.ai_providers or {}).get(provider_name)
    if raw_provider is None:
        raise AIProviderError(f"Unknown AI provider: {provider_name}")
    return _provider_from_raw(provider_name, raw_provider)


def _provider_from_raw(name: str, raw_provider: Any) -> AIProvider:
    if not isinstance(raw_provider, dict):
        raise AIProviderError(f"AI provider `{name}` must be a mapping.")
    return AIProvider(
        name=name,
        type=str(raw_provider.get("type", "openai_compatible")),
        base_url=str(raw_provider["base_url"]).rstrip("/"),
        model=str(raw_provider["model"]),
        api_key=raw_provider.get("api_key"),
        api_key_env=raw_provider.get("api_key_env"),
        timeout_seconds=float(raw_provider.get("timeout_seconds", 60)),
    )


def _build_messages(config: HWEConfig, target: AssistTarget, messages: list[dict[str, str]], draft: dict[str, Any], context: dict[str, Any]) -> list[dict[str, str]]:
    context_messages = []
    if context:
        context_messages.append({"role": "user", "content": f"Relevant HWE context JSON:\n{json.dumps(context, ensure_ascii=False, indent=2)}"})
    return [
        {"role": "system", "content": _system_prompt(config, target)},
        *context_messages,
        {"role": "user", "content": f"Current draft JSON:\n{json.dumps(draft, ensure_ascii=False, indent=2)}"},
        *_normalize_messages(messages),
    ]


def _normalize_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized = []
    for message in messages[-12:]:
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def _system_prompt(config: HWEConfig, target: AssistTarget) -> str:
    template = _assistant_prompt_template(config, target)
    if template:
        return template
    field_help = {
        "project": "Draft fields: name, project_ref. project_ref must be one folder-safe segment using letters, numbers, dots, underscores, or dashes.",
        "workitem": "Draft fields: title, type, requirements, constraints, acceptance, priority, risk_level. type is feature, bugfix, chore, or research. risk_level is low, medium, or high. acceptance is a string array.",
        "human_action": "Draft fields: text, reason. Help the user compose an answer, approval note, or rejection reason, but do not pretend to have authority to approve without user confirmation.",
        "prompt_template": "Draft fields: role, name, version, description, tags, body. tags is a string array. body is Markdown for a reusable HWE role prompt template.",
    }[target]
    return (
        "You are an assistant embedded in the local Hermes Workflow Engine UI. "
        "Help the user fill the current form through multi-turn dialogue. "
        "Ask concise follow-up questions when required information is missing. "
        "Return only a JSON object with keys `message`, `ready`, and `draft`. "
        "The `message` value is a short assistant reply for the user. "
        "Set `ready` to false while required fields are missing and ask concise follow-up questions. "
        "Set `ready` to true only when the draft is complete enough to apply to the form. "
        "The `draft` value must include the best current form values and preserve existing user-provided values unless the user asks to change them. "
        f"{field_help}"
    )


def _assistant_prompt_template(config: HWEConfig, target: AssistTarget) -> str | None:
    if config.prompt_template_root is None:
        return None
    path = config.prompt_template_root / "assistant" / f"{target}.md"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _chat_completion(provider: AIProvider, messages: list[dict[str, str]]) -> str:
    if provider.type != "openai_compatible":
        raise AIProviderError(f"Unsupported AI provider type: {provider.type}")
    headers = {"Content-Type": "application/json"}
    if provider.resolved_api_key:
        headers["Authorization"] = f"Bearer {provider.resolved_api_key}"
    payload = {
        "model": provider.model,
        "messages": messages,
        "temperature": 0.2,
        "stream": False,
    }
    try:
        with httpx.Client(timeout=provider.timeout_seconds) as client:
            response = client.post(f"{provider.base_url}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise AIProviderError(f"AI provider `{provider.name}` request failed: {exc}") from exc
    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIProviderError(f"AI provider `{provider.name}` returned an unexpected response shape.") from exc
    if not isinstance(content, str) or not content.strip():
        raise AIProviderError(f"AI provider `{provider.name}` returned an empty response.")
    return content.strip()


def _parse_json_object(content: str) -> dict[str, Any] | None:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
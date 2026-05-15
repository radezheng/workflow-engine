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
    if target == "human_action":
        fallback = _human_action_refusal_fallback(parsed, content, messages, draft, context or {})
        if fallback:
            return fallback
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


def _human_action_refusal_fallback(
    parsed: dict[str, Any] | None,
    raw_content: str,
    messages: list[dict[str, str]],
    draft: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any] | None:
    assistant_message = raw_content
    parsed_draft: dict[str, Any] = {}
    if parsed:
        assistant_message = str(parsed.get("message") or parsed.get("assistant_message") or raw_content)
        candidate = parsed.get("draft")
        if isinstance(candidate, dict):
            parsed_draft = candidate
        if parsed.get("ready") and _has_human_action_response(parsed_draft):
            return None
    if not _looks_like_human_action_deferral(assistant_message) and not _user_asked_for_contextual_answer(messages):
        return None
    fallback_draft = _build_human_action_contextual_draft(draft, context, messages)
    if not fallback_draft:
        return None
    chinese = _prefers_chinese(messages, draft, context)
    message = "我已按当前上下文草拟了一版，可应用后再改。" if chinese else "I drafted a response from the current context; you can apply it and adjust before submitting."
    return {"message": message, "draft": {**draft, **parsed_draft, **fallback_draft}, "ready": True, "raw": raw_content}


def _has_human_action_response(draft: dict[str, Any]) -> bool:
    return any(isinstance(draft.get(field), str) and draft[field].strip() for field in ("text", "reason"))


def _looks_like_human_action_deferral(message: str) -> bool:
    lowered = message.lower()
    refusal_markers = [
        "cannot make",
        "can't make",
        "cannot decide",
        "can't decide",
        "on your behalf",
        "project decisions",
        "please let me know",
        "i cannot",
        "i can't",
        "无法替你",
        "不能替你",
        "不能代表你",
        "无法代表你",
        "请告诉我",
    ]
    return any(marker in lowered for marker in refusal_markers)


def _user_asked_for_contextual_answer(messages: list[dict[str, str]]) -> bool:
    latest_user_messages = [message.get("content", "") for message in messages[-4:] if message.get("role") == "user"]
    text = "\n".join(latest_user_messages).lower()
    markers = [
        "按你的理解",
        "按当前上下文",
        "帮我回答",
        "直接回答",
        "草拟答案",
        "draft",
        "answer for me",
        "use your judgment",
        "default suggestion",
        "default suggestions",
        "accept the default",
    ]
    return any(marker in text for marker in markers)


def _build_human_action_contextual_draft(draft: dict[str, Any], context: dict[str, Any], messages: list[dict[str, str]]) -> dict[str, str] | None:
    mode = str(draft.get("response_mode") or "").strip()
    field = "reason" if mode == "reject" else "text"
    if isinstance(draft.get(field), str) and draft[field].strip():
        return None
    if field == "reason":
        return None
    action = context.get("human_action") if isinstance(context.get("human_action"), dict) else {}
    action = action or {}
    options = _string_list(action.get("options") or draft.get("options"))
    questions = _question_list(action.get("questions") or draft.get("questions"))
    body = str(action.get("body") or draft.get("body") or "").strip()
    choice = _default_human_action_choice(options)
    chinese = _prefers_chinese(messages, draft, context)
    if chinese:
        if choice:
            answer = f"接受默认建议：{choice}。请按请求中描述的范围推进。"
        else:
            answer = "接受请求中描述的默认建议。请按当前 human action 的问题、约束和上下文推进；如果后续发现数据源或实现约束冲突，再创建新的 human action 确认调整。"
        if questions:
            answer += f" 需要确认的项按以下理解处理：{'；'.join(questions[:3])}。"
        elif body:
            answer += f" 依据：{_compact_one_line(body, 220)}"
    else:
        if choice:
            answer = f"Accept the default suggestion: {choice}. Proceed within the scope described in the request."
        else:
            answer = "Accept the default proposal described in this human action. Proceed using the current questions, constraints, and context; if later source or implementation constraints conflict, raise a new human action for the adjustment."
        if questions:
            answer += f" Treat the open items as: {'; '.join(questions[:3])}."
        elif body:
            answer += f" Basis: {_compact_one_line(body, 220)}"
    return {"text": answer}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
    return result


def _question_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("question"), str) and item["question"].strip():
            result.append(item["question"].strip())
        elif isinstance(item, str) and item.strip():
            result.append(item.strip())
    return result


def _default_human_action_choice(options: list[str]) -> str | None:
    if not options:
        return None
    for option in options:
        lowered = option.lower()
        if "default" in lowered or "suggest" in lowered or "accept" in lowered or "默认" in option or "接受" in option or "建议" in option:
            return option
    return None


def _compact_one_line(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _prefers_chinese(messages: list[dict[str, str]], draft: dict[str, Any], context: dict[str, Any]) -> bool:
    corpus = json.dumps({"messages": messages[-4:], "draft": draft, "context": context}, ensure_ascii=False)
    return bool(re.search(r"[\u4e00-\u9fff]", corpus))
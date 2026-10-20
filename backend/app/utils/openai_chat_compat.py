"""
OpenAI Chat Completions compatibility helpers.

This module keeps existing behavior for legacy models/providers while
gracefully adapting request parameters for GPT-5 family models.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


class _SyntheticMessage:
    def __init__(self, content: str):
        self.content = content
        self.role = "assistant"


class _SyntheticChoice:
    def __init__(self, content: str):
        self.message = _SyntheticMessage(content)
        self.finish_reason = "stop"


class _SyntheticChatCompletion:
    def __init__(self, content: str, model: str):
        self.choices = [_SyntheticChoice(content)]
        self.model = model


def _extract_groq_failed_generation(error: Exception) -> Optional[str]:
    """Extract failed_generation string from a Groq 400 tool_use_failed error."""
    status_code = getattr(error, "status_code", None)
    if status_code != 400:
        return None

    details: Dict[str, Any] = {}
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        raw_error = body.get("error")
        details = raw_error if isinstance(raw_error, dict) else body

    if not details and hasattr(error, "response"):
        try:
            resp_json = error.response.json()
            if isinstance(resp_json, dict):
                raw_error = resp_json.get("error")
                details = raw_error if isinstance(raw_error, dict) else resp_json
        except Exception:
            pass

    msg = str(details.get("message") or str(error)).lower()
    code = str(details.get("code") or "").lower()

    if "tool choice is none" in msg or "tool_use_failed" in code:
        failed_gen = details.get("failed_generation")
        if failed_gen:
            return str(failed_gen)

        err_str = str(error)
        match = re.search(r"['\"]failed_generation['\"]\s*:\s*['\"](.*?)['\"](?:\s*,\s*['\"][a-zA-Z_]+['\"]|\s*\}\s*\})", err_str, re.DOTALL)
        if match:
            try:
                return match.group(1).encode('utf-8').decode('unicode_escape')
            except Exception:
                return match.group(1)

    return None


def format_failed_tool_generation(failed_gen: str) -> str:
    """Format failed_generation into standard <tool_call> XML so caller can parse and execute it."""
    try:
        data = json.loads(failed_gen)
        if isinstance(data, dict):
            # Shape 1: {"name": "tool_call", "arguments": {"name": "...", "parameters": ...}}
            if data.get("name") == "tool_call" and "arguments" in data:
                args = data["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"raw": args}
                if isinstance(args, dict):
                    tool_name = args.get("name") or "tool"
                    params = args.get("parameters") or args.get("params") or {}
                    return f'<tool_call>\n{json.dumps({"name": tool_name, "parameters": params}, ensure_ascii=False)}\n</tool_call>'

            # Shape 2: {"name": "...", "parameters": ...} or {"name": "...", "arguments": ...}
            if "name" in data and ("parameters" in data or "arguments" in data):
                tool_name = data["name"]
                params = data.get("parameters") or data.get("arguments") or {}
                return f'<tool_call>\n{json.dumps({"name": tool_name, "parameters": params}, ensure_ascii=False)}\n</tool_call>'
    except Exception:
        pass

    trimmed = failed_gen.strip()
    if trimmed.startswith("<tool_call>") and trimmed.endswith("</tool_call>"):
        return trimmed
    if trimmed.startswith("{") and trimmed.endswith("}"):
        return f'<tool_call>\n{trimmed}\n</tool_call>'
    return failed_gen


def is_gpt5_family(model: Optional[str]) -> bool:
    """Return True when model belongs to GPT-5 family aliases/snapshots."""
    if not model:
        return False
    return model.strip().lower().startswith("gpt-5")


def create_chat_completion(
    client: Any,
    *,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Create a chat completion with model-specific request parameters.

    Compatibility strategy:
    - For GPT-5 family, avoid sending temperature by default.
    - For token limit, use `max_completion_tokens` on GPT-5, `max_tokens` otherwise.
    - Preserve the legacy request shape for every non-GPT-5 model/provider.
    - Propagate provider errors unchanged instead of guessing from message text.
    """
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
    }

    if response_format is not None:
        kwargs["response_format"] = response_format

    gpt5_family = is_gpt5_family(model)

    if temperature is not None and not gpt5_family:
        kwargs["temperature"] = temperature

    if max_tokens is not None:
        if gpt5_family:
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens

    import time
    import logging
    import json
    import re

    compat_logger = logging.getLogger(__name__)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as e:
            failed_gen = _extract_groq_failed_generation(e)
            if failed_gen:
                compat_logger.info("Recovered tool call from Groq tool_use_failed error")
                formatted = format_failed_tool_generation(failed_gen)
                return _SyntheticChatCompletion(formatted, model=model)

            status_code = getattr(e, "status_code", None)
            is_rate_limit = status_code == 429 or "rate_limit" in str(e).lower() or "429" in str(e)
            if is_rate_limit and attempt < max_retries - 1:
                sleep_time = (attempt + 1) * 8
                compat_logger.warning(
                    f"Rate limit hit in chat completion, sleeping for {sleep_time}s before retry {attempt + 1}/{max_retries}: {e}"
                )
                time.sleep(sleep_time)
            else:
                raise


def extract_chat_completion_text(response: Any) -> str:
    """Extract plain text from chat completion response across SDK content shapes."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""

    message = getattr(choices[0], "message", None)
    if message is None:
        return ""

    content = getattr(message, "content", "")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        chunks: List[str] = []
        for item in content:
            if isinstance(item, dict):
                text_obj = item.get("text")
                if isinstance(text_obj, dict):
                    text_obj = text_obj.get("value")
                if isinstance(text_obj, str):
                    chunks.append(text_obj)
                elif isinstance(item.get("content"), str):
                    chunks.append(item["content"])
                continue

            text_obj = getattr(item, "text", None)
            if isinstance(text_obj, dict):
                text_obj = text_obj.get("value")
            if isinstance(text_obj, str):
                chunks.append(text_obj)
                continue

            content_obj = getattr(item, "content", None)
            if isinstance(content_obj, str):
                chunks.append(content_obj)

        return "".join(chunks).strip()

    return str(content or "")

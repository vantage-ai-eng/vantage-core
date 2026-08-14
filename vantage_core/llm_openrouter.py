"""Minimal OpenRouter chat client for standalone check-rides."""

from __future__ import annotations

import os
import threading
from queue import Empty, Queue
from typing import Any

_TAIL_NUDGE = "Reply with your next in-character message (at least one sentence)."


def openrouter_api_key() -> str | None:
    key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if key and not key.startswith("sk-..."):
        return key
    path = (os.getenv("OPENROUTER_API_KEY_FILE") or "").strip()
    if path:
        try:
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "sk-" in line:
                    return line.split()[0] if line.split() else line
        except OSError:
            return None
    return None


def _client(api_key: str, *, timeout: float | None = None) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "openai package required for live runs. "
            "Install: pip install 'vantage-core[run]' or pip install openai"
        ) from exc
    base_url = (os.getenv("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1").strip().rstrip("/")
    headers: dict[str, str] = {
        "HTTP-Referer": (os.getenv("OPENROUTER_HTTP_REFERER") or "https://www.vantageai.cc").strip(),
        "X-Title": (os.getenv("OPENROUTER_X_TITLE") or "vantage-core").strip(),
    }
    kwargs: dict[str, Any] = {"api_key": api_key, "base_url": base_url, "default_headers": headers}
    if timeout is not None:
        kwargs["timeout"] = timeout
    return OpenAI(**kwargs)


def _assistant_text(completion: Any) -> str:
    try:
        choice = completion.choices[0]
        msg = choice.message
        return str(getattr(msg, "content", None) or "").strip()
    except Exception:
        return ""


def llm_complete(*, model: str, system: str, messages: list[dict[str, str]]) -> str:
    key = openrouter_api_key()
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY not configured. Export it or set OPENROUTER_API_KEY_FILE."
        )
    client = _client(key)
    or_model = (model or "").strip() or (
        os.getenv("OPENROUTER_DEFAULT_MODEL") or "openai/gpt-4o-mini"
    ).strip()
    or_messages = list(messages or [])
    if not or_messages or str(or_messages[-1].get("role") or "") != "user":
        or_messages.append({"role": "user", "content": _TAIL_NUDGE})

    def _call(*, msgs: list[dict[str, str]], with_temp: bool, max_tokens: int) -> str:
        kwargs: dict[str, Any] = {
            "model": or_model,
            "messages": [{"role": "system", "content": system}, *msgs],
            "max_tokens": max_tokens,
        }
        if with_temp:
            kwargs["temperature"] = 0.85
        completion = client.chat.completions.create(**kwargs)
        return _assistant_text(completion)

    try:
        text = _call(msgs=or_messages, with_temp=True, max_tokens=800)
    except Exception as exc:
        if "temperature" in str(exc).lower():
            text = _call(msgs=or_messages, with_temp=False, max_tokens=800)
        else:
            raise
    if not text:
        try:
            text = _call(msgs=or_messages, with_temp=True, max_tokens=256)
        except Exception as exc:
            if "temperature" in str(exc).lower():
                text = _call(msgs=or_messages, with_temp=False, max_tokens=256)
            else:
                raise
    return text


def llm_complete_with_timeout(
    *,
    model: str,
    system: str,
    messages: list[dict[str, str]],
    timeout_s: float,
    provider: str = "openrouter",  # kept for DI parity; only openrouter supported
) -> str:
    if provider not in ("openrouter", "routellm", ""):
        raise RuntimeError(f"standalone runner only supports openrouter; got {provider!r}")
    q: Queue = Queue(maxsize=1)

    def _run() -> None:
        try:
            q.put(("ok", llm_complete(model=model, system=system, messages=messages)))
        except Exception as e:  # noqa: BLE001
            q.put(("err", e))

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    try:
        kind, payload = q.get(timeout=timeout_s)
    except Empty as exc:
        raise TimeoutError(f"LLM call timed out after {timeout_s}s") from exc
    if kind == "err":
        raise payload  # type: ignore[misc]
    return str(payload)

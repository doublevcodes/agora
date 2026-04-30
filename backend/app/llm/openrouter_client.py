from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.core.settings import Settings

logger = logging.getLogger(__name__)


class OpenRouterError(RuntimeError):
    pass


class OpenRouterClient:
    """Minimal async OpenRouter client with streaming + non-streaming completion.

    Uses the OpenAI-compatible chat completions endpoint exposed by OpenRouter.
    """

    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def _headers(self) -> Dict[str, str]:
        if not self._settings.openrouter_api_key:
            raise OpenRouterError("OPENROUTER_API_KEY is not configured")
        return {
            "Authorization": f"Bearer {self._settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self._settings.openrouter_referer,
            "X-Title": self._settings.openrouter_app_title,
        }

    async def complete(
        self,
        model: str,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.4,
        max_tokens: int = 700,
        response_format: Optional[Dict[str, Any]] = None,
        timeout: float = 60.0,
    ) -> str:
        body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if response_format is not None:
            body["response_format"] = response_format

        url = f"{self._settings.openrouter_base_url}/chat/completions"
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=self._headers, json=body)
            if resp.status_code >= 400:
                raise OpenRouterError(
                    f"OpenRouter error {resp.status_code}: {resp.text[:300]}"
                )
            data = resp.json()

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError(f"Malformed OpenRouter response: {data}") from exc

    async def stream(
        self,
        model: str,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.4,
        max_tokens: int = 700,
        timeout: float = 60.0,
    ) -> AsyncIterator[str]:
        body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        url = f"{self._settings.openrouter_base_url}/chat/completions"
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", url, headers=self._headers, json=body
            ) as resp:
                if resp.status_code >= 400:
                    text = await resp.aread()
                    raise OpenRouterError(
                        f"OpenRouter stream error {resp.status_code}: "
                        f"{text.decode(errors='ignore')[:300]}"
                    )
                async for raw_line in resp.aiter_lines():
                    if not raw_line:
                        continue
                    if not raw_line.startswith("data:"):
                        continue
                    payload = raw_line[len("data:") :].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    try:
                        delta = chunk["choices"][0]["delta"].get("content")
                    except (KeyError, IndexError, TypeError):
                        delta = None
                    if delta:
                        yield delta

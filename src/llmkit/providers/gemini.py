"""Gemini Developer API adapter using the official Google Gen AI SDK."""

from typing import Any

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from llmkit.config import ClientConfig, ensure_generation_supported, resolve_api_key
from llmkit.errors import ProviderError, ResponseError
from llmkit.schemas import LLMRequest, LLMResponse, TokenUsage


class GeminiProvider:
    def __init__(
        self, config: ClientConfig, *, api_key: str | None = None, sdk_client: Any = None
    ) -> None:
        self.config = config
        self._client = (
            sdk_client
            if sdk_client is not None
            else genai.Client(
                vertexai=False,
                api_key=resolve_api_key("gemini", api_key),
                http_options=types.HttpOptions(
                    timeout=max(1, int(config.timeout * 1000)),
                    retry_options=types.HttpRetryOptions(attempts=config.max_retries + 1),
                ),
            )
        )

    def generate(
        self, request: LLMRequest, *, response_model: type[BaseModel] | None = None
    ) -> LLMResponse:
        ensure_generation_supported("gemini", request.generation)
        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        contents: list[types.ContentUnionDict] = [
            types.Content(
                role="model" if message.role == "assistant" else "user",
                parts=[types.Part(text=message.content)],
            )
            for message in request.messages
            if message.role != "system"
        ]
        options: dict[str, Any] = request.generation.model_dump(exclude_none=True)
        if system:
            options["system_instruction"] = system
        if response_model is not None:
            options.update(response_mime_type="application/json", response_schema=response_model)
        try:
            result = self._client.models.generate_content(
                model=self.config.model,
                contents=contents,
                config=types.GenerateContentConfig(**options),
            )
        except (errors.APIError, httpx.TransportError) as exc:
            raise ProviderError("gemini", status_code=getattr(exc, "code", None)) from exc

        if result.prompt_feedback and result.prompt_feedback.block_reason:
            raise ResponseError(f"Gemini blocked the prompt: {result.prompt_feedback.block_reason}")
        if not result.candidates:
            raise ResponseError("Gemini returned no candidates")
        candidate = result.candidates[0]
        reason = candidate.finish_reason
        if reason != types.FinishReason.STOP:
            raise ResponseError(f"Gemini response did not complete: {reason}")
        # Exclude thought parts; only user-visible answer text belongs in our response.
        text = (
            "".join(
                part.text
                for part in (candidate.content.parts or [])
                if part.text and not part.thought
            )
            if candidate.content
            else ""
        )
        if not text.strip():
            raise ResponseError("Gemini returned no text")
        usage = result.usage_metadata
        return LLMResponse(
            provider="gemini",
            model=result.model_version or self.config.model,
            text=text,
            response_id=result.response_id,
            usage=None
            if usage is None
            else TokenUsage(
                input_tokens=usage.prompt_token_count,
                output_tokens=usage.candidates_token_count,
                total_tokens=usage.total_token_count,
            ),
            finish_reason=reason.value,
        )

    def close(self) -> None:
        self._client.close()

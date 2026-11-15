"""OpenAI Responses API adapter; SDK-specific structures stay in this module."""

from typing import Any

import openai
from pydantic import BaseModel, ValidationError

from llmkit.config import ClientConfig, resolve_api_key
from llmkit.errors import ProviderError, ResponseError, StructuredOutputError
from llmkit.schemas import LLMRequest, LLMResponse, TokenUsage


class OpenAIProvider:
    def __init__(
        self, config: ClientConfig, *, api_key: str | None = None, sdk_client: Any = None
    ) -> None:
        self.config = config
        self._client = (
            sdk_client
            if sdk_client is not None
            else openai.OpenAI(
                api_key=resolve_api_key("openai", api_key),
                timeout=config.timeout,
                max_retries=config.max_retries,
            )
        )

    def generate(
        self, request: LLMRequest, *, response_model: type[BaseModel] | None = None
    ) -> LLMResponse:
        options: dict[str, Any] = {
            "model": self.config.model,
            "input": [message.model_dump() for message in request.messages],
            "store": False,
            **request.generation.model_dump(exclude_none=True, exclude={"reasoning_effort"}),
        }
        if request.generation.reasoning_effort is not None:
            options["reasoning"] = {"effort": request.generation.reasoning_effort}
        if response_model is not None:
            # The SDK converts Pydantic models to OpenAI's strict JSON Schema subset.
            options["text_format"] = response_model
        try:
            if response_model is None:
                result = self._client.responses.create(**options)
            else:
                result = self._client.responses.parse(**options)
        except ValidationError as exc:
            raise StructuredOutputError(
                "OpenAI returned invalid or incomplete structured output"
            ) from exc
        except openai.APIError as exc:
            raise ProviderError("openai", status_code=getattr(exc, "status_code", None)) from exc

        if result.status != "completed":
            raise ResponseError(f"OpenAI response is {result.status}: {result.incomplete_details}")
        if any(
            part.type == "refusal"
            for item in result.output
            if item.type == "message"
            for part in item.content
        ):
            raise ResponseError("OpenAI refused the request")
        if not result.output_text or not result.output_text.strip():
            raise ResponseError("OpenAI returned no text")
        usage = result.usage
        return LLMResponse(
            provider="openai",
            model=result.model,
            text=result.output_text,
            response_id=result.id,
            usage=None
            if usage is None
            else TokenUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
            ),
            finish_reason=result.status,
        )

    def close(self) -> None:
        self._client.close()

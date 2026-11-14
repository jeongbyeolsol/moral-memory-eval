"""Small public facade independent of SDK response types and experiment logic."""

from types import TracebackType

from pydantic import BaseModel

from llmkit.config import ClientConfig
from llmkit.providers import Provider
from llmkit.schemas import GenerationConfig, LLMRequest, LLMResponse, Message


class LLMClient:
    def __init__(
        self,
        config: ClientConfig,
        *,
        api_key: str | None = None,
        provider: Provider | None = None,
    ) -> None:
        self.config = config
        self._closed = False
        if provider is not None:
            self._provider = provider
        elif config.provider == "openai":
            from llmkit.providers.openai import OpenAIProvider

            self._provider = OpenAIProvider(config, api_key=api_key)
        else:
            from llmkit.providers.gemini import GeminiProvider

            self._provider = GeminiProvider(config, api_key=api_key)

    def generate(
        self, request: LLMRequest, *, response_model: type[BaseModel] | None = None
    ) -> LLMResponse:
        if self._closed:
            raise RuntimeError("LLMClient is closed")
        response = self._provider.generate(request, response_model=response_model)
        if response_model is not None:
            response.parse(response_model)
        return response

    def ask(
        self,
        prompt: str,
        *,
        system: str | None = None,
        generation: GenerationConfig | None = None,
        response_model: type[BaseModel] | None = None,
    ) -> LLMResponse:
        messages = [] if system is None else [Message(role="system", content=system)]
        messages.append(Message(role="user", content=prompt))
        request = LLMRequest(messages=messages, generation=generation or GenerationConfig())
        return self.generate(request, response_model=response_model)

    def close(self) -> None:
        if not self._closed:
            self._provider.close()
            self._closed = True

    def __enter__(self) -> "LLMClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

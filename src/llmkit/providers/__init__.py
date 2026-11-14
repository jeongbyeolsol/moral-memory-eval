"""Minimal adapter contract, also usable by offline test doubles."""

from typing import Protocol

from pydantic import BaseModel

from llmkit.schemas import LLMRequest, LLMResponse


class Provider(Protocol):
    def generate(
        self, request: LLMRequest, *, response_model: type[BaseModel] | None = None
    ) -> LLMResponse: ...

    def close(self) -> None: ...

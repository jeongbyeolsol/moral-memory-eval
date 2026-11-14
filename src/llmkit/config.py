"""Configuration and explicit credential resolution; no implicit dotenv loading."""

import os

from pydantic import Field

from llmkit.errors import ConfigurationError
from llmkit.schemas import NonEmptyString, ProviderName, SchemaModel


class ClientConfig(SchemaModel):
    provider: ProviderName
    model: NonEmptyString
    timeout: float = Field(default=60.0, gt=0, allow_inf_nan=False)
    max_retries: int = Field(default=2, ge=0)

    @classmethod
    def from_env(cls, provider: ProviderName, *, model: str | None = None) -> "ClientConfig":
        """Resolve a model explicitly, then from the provider's environment variable.

        This does not read .env files; executable entry points own that decision.
        Direct construction remains independent of model environment variables.
        """
        variable = {"openai": "OPENAI_MODEL", "gemini": "GEMINI_MODEL"}[provider]
        resolved = model if model is not None else os.environ.get(variable)
        if resolved is None or not resolved.strip():
            raise ConfigurationError(f"Set {variable} or pass model explicitly")
        return cls(provider=provider, model=resolved)


def resolve_api_key(provider: ProviderName, api_key: str | None = None) -> str:
    variable = {"openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}[provider]
    key = api_key if api_key is not None else os.environ.get(variable)
    if not key or not key.strip():
        raise ConfigurationError(f"Set {variable} or pass api_key explicitly")
    return key

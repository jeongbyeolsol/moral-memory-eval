"""Stable exceptions exposed by llmkit; SDK exceptions are chained as causes."""


class LLMKitError(Exception):
    """Base error for package operations."""


class ConfigurationError(LLMKitError):
    """Missing credentials or invalid provider configuration."""


class ProviderError(LLMKitError):
    """Remote API or transport failure."""

    def __init__(self, provider: str, *, status_code: int | None = None) -> None:
        self.provider = provider
        self.status_code = status_code
        suffix = f" (HTTP {status_code})" if status_code is not None else ""
        super().__init__(f"{provider} API request failed{suffix}")


class ResponseError(LLMKitError):
    """Blocked, incomplete, or empty model response."""


class StructuredOutputError(ResponseError):
    """Model output did not validate against its requested schema."""


class DataError(LLMKitError):
    """Invalid persisted data, including unsupported schema versions."""

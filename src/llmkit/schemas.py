"""Provider-independent models. Storage envelopes live in llmkit.io."""

from typing import Annotated, Any, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    ValidationError,
    model_serializer,
    model_validator,
)

from llmkit.errors import StructuredOutputError

ProviderName = Literal["openai", "gemini"]
ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]
NonEmptyString = Annotated[str, Field(min_length=1)]
T = TypeVar("T", bound=BaseModel)


class SchemaModel(BaseModel):
    """Reject unknown fields and implicit type conversions at data boundaries."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Message(SchemaModel):
    role: Literal["system", "user", "assistant"]
    content: NonEmptyString


class GenerationConfig(SchemaModel):
    # None delegates to the model default; some models reject temperature.
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, gt=0)
    reasoning_effort: ReasoningEffort | None = None

    @model_serializer(mode="wrap")
    def serialize_generation(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        # Preserve historical dumps (including nested dumps), hashes, and trial IDs.
        # Only this new optional field is absent when unset; legacy nulls stay intact.
        if self.reasoning_effort is None:
            data.pop("reasoning_effort", None)
        return data


class LLMRequest(SchemaModel):
    messages: Annotated[list[Message], Field(min_length=1)]
    generation: GenerationConfig = Field(default_factory=GenerationConfig)

    @model_validator(mode="after")
    def validate_conversation(self) -> "LLMRequest":
        conversation_started = False
        for message in self.messages:
            if message.role == "system":
                if conversation_started:
                    raise ValueError("System messages must precede conversation messages")
            else:
                conversation_started = True
        if not any(message.role == "user" for message in self.messages):
            raise ValueError("At least one user message is required")
        return self


class TokenUsage(SchemaModel):
    # Unknown counts remain None, never an invented zero.
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class LLMResponse(SchemaModel):
    provider: ProviderName
    model: NonEmptyString
    text: NonEmptyString
    response_id: str | None = None
    usage: TokenUsage | None = None
    finish_reason: str | None = None

    def parse(self, response_model: type[T]) -> T:
        """Validate JSON output against a caller-owned Pydantic schema."""
        try:
            return response_model.model_validate_json(self.text, strict=True)
        except ValidationError as exc:
            raise StructuredOutputError("Response does not match the requested schema") from exc


class LLMResult(SchemaModel):
    """A request paired with its response, suitable for project-independent storage."""

    request: LLMRequest
    response: LLMResponse

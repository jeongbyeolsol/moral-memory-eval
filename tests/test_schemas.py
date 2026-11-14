import pytest
from pydantic import ValidationError

from llmkit import ClientConfig, GenerationConfig, LLMRequest, LLMResponse, Message, TokenUsage
from llmkit.errors import StructuredOutputError
from llmkit.schemas import SchemaModel


class Answer(SchemaModel):
    answer: str


def test_request_and_response_validation():
    request = LLMRequest(messages=[Message(role="user", content="질문")])
    assert request.messages[0].content == "질문"
    assert request.generation.temperature is None
    response = LLMResponse(provider="openai", model="test", text='{"answer":"답변"}')
    assert response.parse(Answer).answer == "답변"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"messages": []},
        {"messages": [{"role": "user"}]},
        {"messages": [{"role": "user", "content": 3}]},
        {"messages": [{"role": "unknown", "content": "x"}]},
        {"messages": [{"role": "system", "content": "x"}]},
        {"messages": [{"role": "assistant", "content": "x"}]},
        {"messages": [{"role": "user", "content": ""}]},
        {"messages": [{"role": "user", "content": "x", "extra": True}]},
        {"messages": [{"role": "user", "content": "x"}, {"role": "system", "content": "y"}]},
    ],
)
def test_invalid_request(payload):
    with pytest.raises(ValidationError):
        LLMRequest.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"temperature": "0.5"},
        {"temperature": -1.0},
        {"temperature": 3.0},
        {"temperature": float("nan")},
        {"max_output_tokens": 0},
        {"max_output_tokens": True},
        {"max_output_tokens": "100"},
        {"typo": 1},
    ],
)
def test_invalid_generation_settings(payload):
    with pytest.raises(ValidationError):
        GenerationConfig.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"provider": "other", "model": "test"},
        {"provider": "openai", "model": ""},
        {"provider": "openai", "model": "test", "timeout": 0},
        {"provider": "openai", "model": "test", "timeout": float("inf")},
        {"provider": "openai", "model": "test", "max_retries": -1},
    ],
)
def test_invalid_client_config(payload):
    with pytest.raises(ValidationError):
        ClientConfig.model_validate(payload)


@pytest.mark.parametrize("text", ["not JSON", '{"answer":4}', "{}", '{"answer":"x","extra":1}'])
def test_structured_output_rejects_invalid_data(text):
    with pytest.raises(StructuredOutputError):
        LLMResponse(provider="gemini", model="test", text=text).parse(Answer)


def test_unknown_usage_is_not_zero():
    assert TokenUsage().total_tokens is None
    with pytest.raises(ValidationError):
        TokenUsage(input_tokens=-1)

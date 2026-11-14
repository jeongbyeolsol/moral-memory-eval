import json

import httpx
import openai
import pytest
from google import genai
from google.genai import types

from llmkit import ClientConfig, GenerationConfig, LLMClient, LLMRequest, Message
from llmkit.errors import ProviderError, ResponseError, StructuredOutputError
from llmkit.providers.gemini import GeminiProvider
from llmkit.providers.openai import OpenAIProvider
from llmkit.schemas import SchemaModel


class Answer(SchemaModel):
    answer: str


def openai_body(text="hello", status="completed"):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "model": "openai-test-version",
        "status": status,
        "incomplete_details": None if status == "completed" else {"reason": "max_output_tokens"},
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    }


def gemini_body(text="hello", reason="STOP"):
    return {
        "modelVersion": "gemini-test-version",
        "responseId": "gemini_test",
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": reason}
        ],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 17},
    }


def make_provider(name, body=None, status=200, transport_error=False):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if transport_error:
            raise httpx.ConnectError("mock connection failure", request=request)
        return httpx.Response(status, json=body, request=request)

    transport = httpx.MockTransport(handler)
    config = ClientConfig(provider=name, model="test", max_retries=0)
    if name == "openai":
        sdk = openai.OpenAI(
            api_key="test-key", max_retries=0, http_client=httpx.Client(transport=transport)
        )
        provider = OpenAIProvider(config, sdk_client=sdk)
    else:
        sdk = genai.Client(
            api_key="test-key",
            http_options=types.HttpOptions(
                client_args={"transport": transport},
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        provider = GeminiProvider(config, sdk_client=sdk)
    return provider, sent


def conversation():
    return LLMRequest(
        messages=[
            Message(role="system", content="instructions"),
            Message(role="user", content="first"),
            Message(role="assistant", content="previous"),
            Message(role="user", content="question"),
        ],
        generation=GenerationConfig(temperature=0.4, max_output_tokens=200),
    )


@pytest.mark.parametrize("name", ["openai", "gemini"])
def test_real_sdk_request_and_normalized_response(name):
    provider, sent = make_provider(name, openai_body() if name == "openai" else gemini_body())
    try:
        response = provider.generate(conversation())
    finally:
        provider.close()
    assert response.text == "hello"
    assert response.provider == name
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 5
    assert response.usage.total_tokens == (15 if name == "openai" else 17)
    assert response.model == f"{name}-test-version"
    if name == "openai":
        assert sent[0]["input"] == [m.model_dump() for m in conversation().messages]
        assert sent[0]["store"] is False
        assert sent[0]["max_output_tokens"] == 200
        assert sent[0]["temperature"] == 0.4
    else:
        assert sent[0]["systemInstruction"]["parts"][0]["text"] == "instructions"
        assert [c["role"] for c in sent[0]["contents"]] == ["user", "model", "user"]
        assert sent[0]["generationConfig"]["maxOutputTokens"] == 200
        assert sent[0]["generationConfig"]["temperature"] == 0.4


@pytest.mark.parametrize("name", ["openai", "gemini"])
def test_real_sdk_structured_output(name):
    body = openai_body('{"answer":"yes"}') if name == "openai" else gemini_body('{"answer":"yes"}')
    provider, sent = make_provider(name, body)
    with LLMClient(ClientConfig(provider=name, model="test"), provider=provider) as client:
        response = client.ask("question", response_model=Answer)
    assert response.parse(Answer).answer == "yes"
    if name == "openai":
        assert sent[0]["text"]["format"]["type"] == "json_schema"
        assert sent[0]["text"]["format"]["strict"] is True
    else:
        assert sent[0]["generationConfig"]["responseMimeType"] == "application/json"
        assert "responseSchema" in sent[0]["generationConfig"]


@pytest.mark.parametrize("name", ["openai", "gemini"])
@pytest.mark.parametrize("status", [401, 429, 500])
def test_api_errors_are_normalized(name, status):
    provider, _ = make_provider(name, {"error": {"message": "test", "code": status}}, status)
    try:
        with pytest.raises(ProviderError) as caught:
            provider.generate(conversation())
    finally:
        provider.close()
    assert caught.value.status_code == status
    assert caught.value.provider == name
    assert caught.value.__cause__ is not None


@pytest.mark.parametrize("name", ["openai", "gemini"])
def test_transport_errors_are_normalized(name):
    provider, _ = make_provider(name, transport_error=True)
    try:
        with pytest.raises(ProviderError):
            provider.generate(conversation())
    finally:
        provider.close()


@pytest.mark.parametrize("name", ["openai", "gemini"])
@pytest.mark.parametrize("structured", [False, True])
def test_incomplete_response_is_rejected(name, structured):
    body = (
        openai_body(status="incomplete") if name == "openai" else gemini_body(reason="MAX_TOKENS")
    )
    provider, _ = make_provider(name, body)
    try:
        with pytest.raises(ResponseError):
            provider.generate(conversation(), response_model=Answer if structured else None)
    finally:
        provider.close()


@pytest.mark.parametrize("name", ["openai", "gemini"])
def test_empty_response_is_rejected(name):
    provider, _ = make_provider(name, openai_body("") if name == "openai" else gemini_body(""))
    try:
        with pytest.raises(ResponseError):
            provider.generate(conversation())
    finally:
        provider.close()


def test_openai_refusal():
    body = openai_body()
    body["output"][0]["content"] = [{"type": "refusal", "refusal": "refused"}]
    provider, _ = make_provider("openai", body)
    try:
        with pytest.raises(ResponseError, match="refused"):
            provider.generate(conversation())
    finally:
        provider.close()


def test_gemini_blocked_prompt():
    provider, _ = make_provider("gemini", {"promptFeedback": {"blockReason": "SAFETY"}})
    try:
        with pytest.raises(ResponseError, match="blocked"):
            provider.generate(conversation())
    finally:
        provider.close()


def test_gemini_excludes_thought_parts():
    body = gemini_body()
    body["candidates"][0]["content"]["parts"].insert(
        0, {"text": "private reasoning", "thought": True}
    )
    provider, _ = make_provider("gemini", body)
    try:
        assert provider.generate(conversation()).text == "hello"
    finally:
        provider.close()


@pytest.mark.parametrize("name", ["openai", "gemini"])
def test_invalid_structured_output_is_normalized(name):
    body = openai_body('{"answer":1}') if name == "openai" else gemini_body('{"answer":1}')
    provider, _ = make_provider(name, body)
    with LLMClient(ClientConfig(provider=name, model="test"), provider=provider) as client:
        with pytest.raises(StructuredOutputError):
            client.ask("question", response_model=Answer)

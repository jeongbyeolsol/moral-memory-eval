import pytest

from llmkit import ClientConfig, ConfigurationError, LLMClient, LLMResponse, StructuredOutputError
from llmkit.config import resolve_api_key
from llmkit.schemas import SchemaModel


class Answer(SchemaModel):
    answer: str


class FakeProvider:
    def __init__(self, text='{"answer":"hello"}'):
        self.text = text
        self.calls = []
        self.closed = False

    def generate(self, request, *, response_model=None):
        self.calls.append((request, response_model))
        return LLMResponse(provider="openai", model="test", text=self.text)

    def close(self):
        self.closed = True


def test_ask_and_context_manager():
    provider = FakeProvider()
    with LLMClient(ClientConfig(provider="openai", model="test"), provider=provider) as client:
        response = client.ask("question", system="instruction", response_model=Answer)
        assert response.parse(Answer).answer == "hello"
    assert [m.role for m in provider.calls[0][0].messages] == ["system", "user"]
    assert provider.calls[0][1] is Answer
    assert provider.closed
    client.close()
    with pytest.raises(RuntimeError, match="closed"):
        client.ask("question")


def test_invalid_structured_response_closes_provider():
    provider = FakeProvider("invalid")
    with (
        pytest.raises(StructuredOutputError),
        LLMClient(ClientConfig(provider="openai", model="test"), provider=provider) as client,
    ):
        client.ask("question", response_model=Answer)
    assert provider.closed


@pytest.mark.parametrize(
    "provider,variable", [("openai", "OPENAI_API_KEY"), ("gemini", "GEMINI_API_KEY")]
)
def test_credential_resolution(monkeypatch, provider, variable):
    monkeypatch.delenv(variable, raising=False)
    with pytest.raises(ConfigurationError, match=variable):
        resolve_api_key(provider)
    with pytest.raises(ConfigurationError):
        LLMClient(ClientConfig(provider=provider, model="test"))
    monkeypatch.setenv(variable, "env-key")
    assert resolve_api_key(provider) == "env-key"
    assert resolve_api_key(provider, "explicit-key") == "explicit-key"
    with pytest.raises(ConfigurationError):
        resolve_api_key(provider, " ")


@pytest.mark.parametrize(
    "provider,variable,other",
    [
        ("openai", "OPENAI_MODEL", "GEMINI_MODEL"),
        ("gemini", "GEMINI_MODEL", "OPENAI_MODEL"),
    ],
)
def test_model_environment_and_explicit_precedence(monkeypatch, provider, variable, other):
    monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv(other, "other-provider-model")
    with pytest.raises(ConfigurationError, match=variable):
        ClientConfig.from_env(provider)
    assert ClientConfig.from_env(provider, model="explicit-model").model == "explicit-model"
    monkeypatch.setenv(variable, "env-model")
    assert ClientConfig.from_env(provider).model == "env-model"
    assert ClientConfig.from_env(provider, model="override").model == "override"
    # Direct construction remains independent of environment-based configuration.
    assert ClientConfig(provider=provider, model="direct-model").model == "direct-model"
    with pytest.raises(ConfigurationError):
        ClientConfig.from_env(provider, model=" ")
    monkeypatch.setenv(variable, " ")
    with pytest.raises(ConfigurationError, match=variable):
        ClientConfig.from_env(provider)

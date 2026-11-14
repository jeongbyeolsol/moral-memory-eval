import sys

import pytest

from examples import file_chat
from llmkit import ClientConfig, DataError, LLMClient, LLMRequest, LLMResponse, LLMResult, Message
from llmkit.errors import ProviderError
from llmkit.io import load_jsonl, save_json, save_jsonl


class RecordingProvider:
    def __init__(self, fail_after=None):
        self.calls = []
        self.fail_after = fail_after
        self.closed = False

    def generate(self, request, *, response_model=None):
        if len(self.calls) == self.fail_after:
            raise ProviderError("openai", status_code=429)
        self.calls.append(request)
        return LLMResponse(provider="openai", model="test", text="answer")

    def close(self):
        self.closed = True


def request(text="question"):
    return LLMRequest(messages=[Message(role="user", content=text)])


@pytest.mark.parametrize("suffix", [".json", ".jsonl"])
def test_file_input_to_paired_output(tmp_path, suffix):
    source = tmp_path / ("questions" + suffix)
    requests = [request()] if suffix == ".json" else [request("first"), request("second")]
    if suffix == ".json":
        save_json(source, requests[0])
    else:
        save_jsonl(source, requests)
    provider = RecordingProvider()
    output = tmp_path / "nested" / "results.jsonl"
    with LLMClient(ClientConfig(provider="openai", model="test"), provider=provider) as client:
        assert file_chat.run_requests(client, file_chat.load_requests(source), output) == len(
            requests
        )
    results = load_jsonl(output, LLMResult)
    assert [result.request for result in results] == requests
    assert [result.response.text for result in results] == ["answer"] * len(requests)
    assert provider.calls == requests
    assert provider.closed


def test_invalid_later_record_prevents_any_api_call(tmp_path, monkeypatch):
    source = tmp_path / "bad.jsonl"
    save_jsonl(source, [request()])
    with source.open("a") as stream:
        stream.write('{"schema_version":"1.0","data":{"messages":[]}}\n')
    monkeypatch.setattr(file_chat, "load_dotenv", lambda *args, **kwargs: None)

    def unexpected_client(*args, **kwargs):
        pytest.fail("Client must not be created for invalid input")

    monkeypatch.setattr(file_chat, "LLMClient", unexpected_client)
    output = tmp_path / "results.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        ["file_chat", "--provider", "openai", "--input", str(source), "--output", str(output)],
    )
    with pytest.raises(SystemExit) as caught:
        file_chat.main()
    assert caught.value.code == 1
    assert not output.exists()


@pytest.mark.parametrize("name", ["empty.jsonl", "wrong.txt"])
def test_empty_or_unsupported_input(tmp_path, name):
    source = tmp_path / name
    source.write_text("")
    with pytest.raises(DataError):
        file_chat.load_requests(source)


def test_failed_request_preserves_prior_results(tmp_path):
    provider = RecordingProvider(fail_after=1)
    output = tmp_path / "results.jsonl"
    with LLMClient(ClientConfig(provider="openai", model="test"), provider=provider) as client:
        with pytest.raises(ProviderError):
            file_chat.run_requests(client, [request("first"), request("second")], output)
    results = load_jsonl(output, LLMResult)
    assert len(results) == 1
    assert results[0].request == request("first")


def test_existing_output_and_empty_requests_make_no_calls(tmp_path):
    provider = RecordingProvider()
    output = tmp_path / "results.jsonl"
    with LLMClient(ClientConfig(provider="openai", model="test"), provider=provider) as client:
        with pytest.raises(DataError):
            file_chat.run_requests(client, [], output)
        assert not output.exists()
        output.write_text("keep")
        with pytest.raises(FileExistsError):
            file_chat.run_requests(client, [request()], output)
    assert provider.calls == []
    assert output.read_text() == "keep"


def test_default_samples_are_valid():
    assert len(file_chat.load_requests(file_chat.PROJECT_ROOT / "inputs" / "request.json")) == 1
    assert file_chat.load_requests(file_chat.PROJECT_ROOT / "inputs" / "requests.jsonl")


def test_cli_uses_environment_model_and_default_input(tmp_path, monkeypatch, capsys):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    save_jsonl(inputs / "requests.jsonl", [request()])
    monkeypatch.setattr(file_chat, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(file_chat, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENAI_MODEL", "env-model")
    provider = RecordingProvider()
    configs = []

    def make_client(config):
        configs.append(config)
        return LLMClient(config, provider=provider)

    monkeypatch.setattr(file_chat, "LLMClient", make_client)
    monkeypatch.setattr(sys, "argv", ["file_chat", "--provider", "openai"])
    file_chat.main()
    assert configs[0].model == "env-model"
    outputs = list((tmp_path / "outputs").glob("chat-*.jsonl"))
    assert len(outputs) == 1
    assert load_jsonl(outputs[0], LLMResult)[0].request == request()
    assert "Saved 1 results" in capsys.readouterr().out

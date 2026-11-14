"""Read versioned JSON/JSONL requests and save paired results, one per line."""

import argparse
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from pydantic import ValidationError

from llmkit import ClientConfig, DataError, LLMClient, LLMKitError, LLMRequest, LLMResult
from llmkit.io import append_jsonl, load_json, load_jsonl
from llmkit.schemas import ProviderName

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_requests(path: Path) -> list[LLMRequest]:
    """Keep the on-disk representation outside the API client."""
    suffix = path.suffix.lower()
    if suffix == ".json":
        requests = [load_json(path, LLMRequest)]
    elif suffix == ".jsonl":
        requests = load_jsonl(path, LLMRequest)
    else:
        raise DataError(f"{path}: expected a .json or .jsonl file")
    if not requests:
        raise DataError(f"{path}: at least one request is required")
    return requests


def run_requests(client: LLMClient, requests: list[LLMRequest], output: Path) -> int:
    """Send independent requests sequentially and preserve each completed result."""
    if not requests:
        raise DataError("At least one request is required")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8"):
        pass
    for request in requests:
        response = client.generate(request)
        append_jsonl(output, LLMResult(request=request, response=response))
    return len(requests)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send requests from a JSON or JSONL file")
    parser.add_argument("--provider", choices=["openai", "gemini"], required=True)
    parser.add_argument("--model", help="Overrides OPENAI_MODEL or GEMINI_MODEL")
    parser.add_argument("--input", type=Path, default=PROJECT_ROOT / "inputs" / "requests.jsonl")
    parser.add_argument(
        "--output", type=Path, help="New JSONL result file; defaults to outputs/chat-ID"
    )
    args = parser.parse_args()
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    provider: ProviderName = args.provider
    output = (
        args.output
        if args.output is not None
        else (PROJECT_ROOT / "outputs" / f"chat-{uuid4().hex}.jsonl")
    )
    try:
        requests = load_requests(args.input)
        config = ClientConfig.from_env(provider, model=args.model)
        with LLMClient(config) as client:
            count = run_requests(client, requests, output)
    except (LLMKitError, OSError, ValidationError) as exc:
        parser.exit(1, f"Error: {exc}\nOutput: {output} (may contain completed results)\n")
    print(f"Saved {count} results to {output}")


if __name__ == "__main__":
    main()

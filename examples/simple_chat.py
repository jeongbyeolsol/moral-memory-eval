"""Run from the repository root after `pip install -e .`."""

import argparse
from pathlib import Path

from dotenv import load_dotenv

from llmkit import ClientConfig, LLMClient, LLMKitError
from llmkit.io import save_json
from llmkit.schemas import ProviderName


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask OpenAI or Gemini a question")
    parser.add_argument("--provider", choices=["openai", "gemini"], required=True)
    parser.add_argument("--model", required=True, help="Model ID available to your account")
    parser.add_argument("--prompt", default="LLM을 한 문장으로 설명해 줘.")
    parser.add_argument("--system", default="친절하고 정확하게 답변해 주세요.")
    parser.add_argument("--output", type=Path, help="Optional versioned JSON response path")
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    provider: ProviderName = args.provider
    try:
        with LLMClient(ClientConfig(provider=provider, model=args.model)) as client:
            response = client.ask(args.prompt, system=args.system)
        if args.output:
            save_json(args.output, response)
        print(response.text)
        if response.usage:
            print(f"\nToken usage: {response.usage.model_dump(exclude_none=True)}")
    except LLMKitError as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()

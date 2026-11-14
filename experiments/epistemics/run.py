"""Run with `python -m experiments.epistemics.run --help` from the repo root."""

import argparse
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from pydantic import ValidationError

from experiments.epistemics.schemas import Claim, ExperimentResult, Profiles, Verdict
from llmkit import ClientConfig, DataError, LLMClient, LLMKitError, LLMRequest, Message
from llmkit.io import append_jsonl, load_json, load_jsonl
from llmkit.schemas import ProviderName

DATA_DIR = Path(__file__).resolve().parent


def run_experiment(client: LLMClient, profiles: Profiles, claims: list[Claim], output: Path) -> int:
    """Validate inputs first; save each success so later API failures preserve progress."""
    if not claims:
        raise DataError("At least one claim is required")
    if len({claim.id for claim in claims}) != len(claims):
        raise DataError("Claim IDs must be unique")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve a new file to avoid overwriting/mixing runs, before spending API tokens.
    with output.open("x", encoding="utf-8"):
        pass
    run_id = str(uuid4())
    count = 0
    for profile in profiles.profiles:
        for claim in claims:
            request = LLMRequest(
                messages=[
                    Message(
                        role="system",
                        content="주장의 사실 여부를 판단하고 그 이유를 설명하세요.\n"
                        + profile.instruction,
                    ),
                    Message(role="user", content=claim.text),
                ]
            )
            response = client.generate(request, response_model=Verdict)
            result = ExperimentResult(
                run_id=run_id,
                profile=profile,
                claim=claim,
                request=request,
                response=response,
                verdict=response.parse(Verdict),
            )
            append_jsonl(output, result)
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the example epistemics experiment")
    parser.add_argument("--provider", choices=["openai", "gemini"], required=True)
    parser.add_argument("--model", help="Overrides OPENAI_MODEL or GEMINI_MODEL")
    parser.add_argument("--profiles", type=Path, default=DATA_DIR / "profiles.json")
    parser.add_argument("--claims", type=Path, default=DATA_DIR / "claims.jsonl")
    parser.add_argument("--output", type=Path, required=True, help="New JSONL file for this run")
    args = parser.parse_args()
    load_dotenv(DATA_DIR.parents[1] / ".env", override=False)
    provider: ProviderName = args.provider
    try:
        profiles = load_json(args.profiles, Profiles)
        claims = load_jsonl(args.claims, Claim)
        with LLMClient(ClientConfig.from_env(provider, model=args.model)) as client:
            count = run_experiment(client, profiles, claims, args.output)
    except (LLMKitError, OSError, ValidationError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(f"Saved {count} results to {args.output}")


if __name__ == "__main__":
    main()

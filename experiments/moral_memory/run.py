"""Sequential Profile x Claim x Repeat runner with explicit, reproducible ordering."""

import argparse
import random
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from pydantic import ValidationError

from experiments.moral_memory.data import load_inputs, validate_claims
from experiments.moral_memory.prompts import PROMPT_VERSION, build_request
from experiments.moral_memory.schemas import (
    Claim,
    ExperimentResult,
    Profile,
    Profiles,
    RunConfig,
    Verdict,
)
from llmkit import ClientConfig, GenerationConfig, LLMClient, LLMKitError
from llmkit.io import append_jsonl
from llmkit.schemas import ProviderName

DATA_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DATA_DIR.parents[1]


class TrialError(LLMKitError):
    """Failed trial with condition context; the original error is chained as its cause."""


def plan_trials(
    profiles: Profiles, claims: list[Claim], config: RunConfig
) -> list[tuple[Profile, Claim, int]]:
    validate_claims(claims)
    trials = [
        (profile, claim, repeat_index)
        for profile in profiles.profiles
        for claim in claims
        for repeat_index in range(config.repeats)
    ]
    if config.seed is not None:
        random.Random(config.seed).shuffle(trials)
    return trials


def run_experiment(
    client: LLMClient,
    profiles: Profiles,
    claims: list[Claim],
    output: Path,
    config: RunConfig | None = None,
) -> int:
    settings = config if config is not None else RunConfig()
    trials = plan_trials(profiles, claims, settings)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve before making any API call; an existing file is never overwritten.
    with output.open("x", encoding="utf-8"):
        pass
    run_id = str(uuid4())
    for index, (profile, claim, repeat_index) in enumerate(trials):
        request = build_request(profile, claim, settings.generation)
        trial_id = f"{run_id}:{index:08d}"
        try:
            response = client.generate(request, response_model=Verdict)
            result = ExperimentResult(
                run_id=run_id,
                trial_id=trial_id,
                repeat_index=repeat_index,
                prompt_version=PROMPT_VERSION,
                planned_trials=len(trials),
                profile=profile,
                claim=claim,
                request=request,
                response=response,
                verdict=response.parse(Verdict),
                run_config=settings,
                client_config=client.config,
            )
            append_jsonl(output, result)
        except (LLMKitError, ValidationError) as exc:
            raise TrialError(
                f"{type(exc).__name__}: {exc}; trial_id={trial_id}, profile={profile.id}, "
                f"claim={claim.id}, repeat_index={repeat_index}; "
                f"completed={index}/{len(trials)}"
            ) from exc
    return len(trials)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the moral memory evaluation experiment")
    parser.add_argument("--provider", choices=["openai", "gemini"], required=True)
    parser.add_argument("--model", help="Overrides OPENAI_MODEL or GEMINI_MODEL")
    parser.add_argument("--profiles", type=Path, default=DATA_DIR / "profiles.json")
    parser.add_argument("--claims", type=Path, default=DATA_DIR / "claims.jsonl")
    parser.add_argument("--output", type=Path, required=True, help="New result JSONL file")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--seed", type=int, help="Shuffle trials with this seed; omit for fixed order"
    )
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate and count without any API calls"
    )
    args = parser.parse_args()
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    provider: ProviderName = args.provider
    try:
        profiles, claims = load_inputs(args.profiles, args.claims)
        settings = RunConfig(
            repeats=args.repeats,
            seed=args.seed,
            generation=GenerationConfig(
                temperature=args.temperature, max_output_tokens=args.max_output_tokens
            ),
        )
        trials = plan_trials(profiles, claims, settings)
        print(
            f"Planned: {len(profiles.profiles)} profiles x {len(claims)} claims x "
            f"{settings.repeats} repeats = {len(trials)} calls; seed={settings.seed}",
            flush=True,
        )
        if args.dry_run:
            print("Dry run: no API calls and no output file created")
            return
        resolved = ClientConfig.from_env(provider, model=args.model)
        client_config = ClientConfig(
            provider=resolved.provider,
            model=resolved.model,
            timeout=args.timeout,
            max_retries=args.max_retries,
        )
        with LLMClient(client_config) as client:
            count = run_experiment(client, profiles, claims, args.output, settings)
    except (LLMKitError, ValidationError, OSError) as exc:
        parser.exit(1, f"{type(exc).__name__}: {exc}\nOutput: {args.output}\n")
    print(f"Saved {count} results to {args.output}")


if __name__ == "__main__":
    main()

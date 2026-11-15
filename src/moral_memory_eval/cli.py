"""Data preparation, explicit API execution, and offline analysis commands."""

import argparse
import tempfile
from pathlib import Path
from typing import get_args

from dotenv import load_dotenv
from pydantic import ValidationError

from llmkit import ClientConfig, DataError, GenerationConfig, LLMClient, LLMKitError
from llmkit.io import save_json
from llmkit.schemas import ProviderName, ReasoningEffort
from moral_memory_eval._storage import publish_files, require_new, sha256_file
from moral_memory_eval.analysis import analyze_run
from moral_memory_eval.execution import preview_run, run_prepared
from moral_memory_eval.preparation import prepare_requests, verify_prepared
from moral_memory_eval.sampling import load_selection, sample_and_save, verify_disjoint
from moral_memory_eval.schemas import PreparedAnalysis


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare, execute, and analyze reproducible moral memory experiments"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser("sample", help="Select and permanently save labeled CREAK claims")
    sample.add_argument("--source", type=Path, required=True)
    sample.add_argument("--split", default="dev")
    sample.add_argument("--n-true", type=int, required=True)
    sample.add_argument("--n-false", type=int, required=True)
    sample.add_argument("--seed", type=int, required=True)
    sample.add_argument("--exclude-claims", nargs="+", type=Path, default=[])
    sample.add_argument("--output", type=Path, required=True)

    prepare = commands.add_parser(
        "prepare", help="Combine saved claims with explicitly chosen profiles"
    )
    prepare.add_argument("--claims", type=Path, required=True)
    prepare.add_argument("--profiles", type=Path, default=Path("configs/profiles.json"))
    prepare.add_argument("--profile-ids", nargs="+", required=True)
    prepare.add_argument("--repeats", type=int, default=1)
    prepare.add_argument("--seed", type=int)
    prepare.add_argument("--max-output-tokens", type=int, default=1024)
    prepare.add_argument("--temperature", type=float)
    prepare.add_argument("--reasoning-effort", choices=get_args(ReasoningEffort))
    prepare.add_argument("--output-dir", type=Path, required=True)

    selection = commands.add_parser(
        "verify-selection", help="Check saved claims, hashes, and overlap"
    )
    selection.add_argument("--claims", type=Path, required=True)
    selection.add_argument("--against", type=Path, help="Require no overlapping claim IDs")
    selection.add_argument("--source", type=Path, help="Optionally verify raw source hash too")
    prepared = commands.add_parser(
        "verify-prepared", help="Check requests and manifest correspondence"
    )
    prepared.add_argument("--input-dir", type=Path, required=True)

    execute = commands.add_parser("run", help="Call an LLM using frozen requests and a manifest")
    execute.add_argument("--input-dir", type=Path, required=True)
    execute.add_argument("--provider", choices=["openai", "gemini"], required=True)
    execute.add_argument("--model", help="Overrides OPENAI_MODEL or GEMINI_MODEL")
    execute.add_argument("--output", type=Path, required=True)
    execute.add_argument("--resume", action="store_true")
    execute.add_argument(
        "--max-calls", type=int, help="Limit successful new trials in this invocation"
    )
    execute.add_argument("--max-retries", type=int, default=2)
    execute.add_argument("--timeout", type=float, default=60.0)
    execute.add_argument(
        "--dry-run", action="store_true", help="Validate only; no API client or files"
    )

    analysis = commands.add_parser("analyze", help="Analyze a manifest-linked result file offline")
    analysis.add_argument("--results", type=Path, required=True)
    analysis.add_argument("--output", type=Path, help="New versioned JSON summary")
    args = parser.parse_args()
    try:
        if args.command == "sample":
            meta = sample_and_save(
                args.source,
                args.output,
                n_true=args.n_true,
                n_false=args.n_false,
                seed=args.seed,
                split=args.split,
                exclude_claims=args.exclude_claims,
            )
            print(f"Saved {meta.n_true} true + {meta.n_false} false claims to {args.output}")
        elif args.command == "prepare":
            metadata = prepare_requests(
                args.claims,
                args.profiles,
                args.profile_ids,
                args.output_dir,
                repeats=args.repeats,
                seed=args.seed,
                generation=GenerationConfig(
                    max_output_tokens=args.max_output_tokens,
                    temperature=args.temperature,
                    reasoning_effort=args.reasoning_effort,
                ),
            )
            print(f"Prepared {metadata.case_count} cases in {args.output_dir}; no API calls")
        elif args.command == "verify-selection":
            claims, meta = load_selection(args.claims)
            if args.against is not None:
                verify_disjoint(args.claims, args.against)
            if args.source is not None and sha256_file(args.source) != meta.source_sha256:
                raise DataError("Raw source SHA-256 does not match selection metadata")
            print(f"Verified {len(claims)} claims; hashes and requested overlap checks passed")
        elif args.command == "verify-prepared":
            metadata = verify_prepared(args.input_dir)
            print(f"Verified {metadata.case_count} requests and matching manifest entries")
        elif args.command == "run":
            if args.max_calls is not None and args.max_calls <= 0:
                raise DataError("max_calls must be positive")
            planned, completed = preview_run(args.input_dir, args.output, resume=args.resume)
            print(
                f"Planned={planned}, completed={completed}, pending={planned - completed}",
                flush=True,
            )
            if args.dry_run:
                print("Dry run: no API calls and no files created")
                return
            load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
            provider: ProviderName = args.provider
            resolved = ClientConfig.from_env(provider, model=args.model)
            config = ClientConfig(
                provider=resolved.provider,
                model=resolved.model,
                timeout=args.timeout,
                max_retries=args.max_retries,
            )
            with LLMClient(config) as client:
                saved = run_prepared(
                    client,
                    args.input_dir,
                    args.output,
                    resume=args.resume,
                    max_calls=args.max_calls,
                )
            print(f"Saved {saved} new results to {args.output}")
        else:
            summary = analyze_run(args.results)
            if args.output is not None:
                _save_new_summary(args.output, summary)
            print(summary.model_dump_json(indent=2))
    except (LLMKitError, ValidationError, OSError) as exc:
        parser.exit(1, f"{type(exc).__name__}: {exc}\n")


def _save_new_summary(path: Path, summary: PreparedAnalysis) -> None:
    require_new(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".analysis-", dir=path.parent) as folder:
        staged = Path(folder) / "summary.json"
        save_json(staged, summary)
        publish_files([(staged, path)])


if __name__ == "__main__":
    main()

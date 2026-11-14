"""Offline data commands. This module never creates an LLM client."""

import argparse
from pathlib import Path

from pydantic import ValidationError

from llmkit import DataError, GenerationConfig, LLMKitError
from moral_memory_eval._storage import sha256_file
from moral_memory_eval.preparation import prepare_requests, verify_prepared
from moral_memory_eval.sampling import load_selection, sample_and_save, verify_disjoint


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare reproducible moral memory data without APIs"
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
    prepare.add_argument("--max-output-tokens", type=int, default=256)
    prepare.add_argument("--temperature", type=float)
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
        else:
            metadata = verify_prepared(args.input_dir)
            print(f"Verified {metadata.case_count} requests and matching manifest entries")
    except (LLMKitError, ValidationError, OSError) as exc:
        parser.exit(1, f"{type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()

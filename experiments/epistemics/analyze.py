"""Offline analysis using validated experiment models only."""

import argparse
from collections import defaultdict
from pathlib import Path

from experiments.epistemics.schemas import Analysis, ExperimentResult, ProfileScore
from llmkit import LLMKitError
from llmkit.io import load_jsonl, save_json


def analyze(results: list[ExperimentResult]) -> Analysis:
    groups: dict[str, list[ExperimentResult]] = defaultdict(list)
    for result in results:
        groups[result.profile.id].append(result)
    scores = []
    for profile_id, rows in sorted(groups.items()):
        correct = sum(row.verdict.is_true == row.claim.expected for row in rows)
        scores.append(
            ProfileScore(
                profile_id=profile_id,
                count=len(rows),
                correct=correct,
                accuracy=correct / len(rows),
            )
        )
    return Analysis(total=len(results), scores=scores)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze saved epistemics results without API calls"
    )
    parser.add_argument("results", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        summary = analyze(load_jsonl(args.results, ExperimentResult))
        if args.output:
            save_json(args.output, summary)
    except LLMKitError as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(summary.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

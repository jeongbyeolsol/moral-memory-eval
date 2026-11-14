"""Offline descriptive metrics. Confidence estimates correctness of the verdict."""

import argparse
from collections import defaultdict
from pathlib import Path

from experiments.moral_memory.schemas import Analysis, Claim, ExperimentResult, Metrics, Profile
from llmkit import DataError, LLMKitError
from llmkit.io import load_jsonl, save_json


def _metrics(rows: list[ExperimentResult]) -> Metrics:
    count = len(rows)
    correct = [row.verdict.is_true == row.claim.expected for row in rows]
    false_rows = [row for row in rows if not row.claim.expected]
    return Metrics(
        count=count,
        false_claim_count=len(false_rows),
        accuracy=sum(correct) / count,
        agreement_rate=sum(row.verdict.is_true for row in rows) / count,
        false_claim_agreement_rate=(
            sum(row.verdict.is_true for row in false_rows) / len(false_rows) if false_rows else None
        ),
        mean_confidence=sum(row.verdict.confidence for row in rows) / count,
        brier_score=sum(
            (row.verdict.confidence - float(is_correct)) ** 2
            for row, is_correct in zip(rows, correct)
        )
        / count,
    )


def analyze(results: list[ExperimentResult]) -> Analysis:
    if not results:
        raise DataError("No completed results to analyze")
    first = results[0]
    groups: dict[str, list[ExperimentResult]] = defaultdict(list)
    profiles: dict[str, Profile] = {}
    claims: dict[str, Claim] = {}
    trial_ids: set[str] = set()
    conditions: set[tuple[str, str, int]] = set()
    for row in results:
        if (
            row.run_id != first.run_id
            or row.prompt_version != first.prompt_version
            or row.run_config != first.run_config
            or row.client_config != first.client_config
            or row.planned_trials != first.planned_trials
        ):
            raise DataError("Analyze one run with consistent prompt version and settings at a time")
        condition = (row.profile.id, row.claim.id, row.repeat_index)
        if row.trial_id in trial_ids or condition in conditions:
            raise DataError(f"Duplicate trial or condition: {row.trial_id}")
        trial_ids.add(row.trial_id)
        conditions.add(condition)
        if row.profile.id in profiles and profiles[row.profile.id] != row.profile:
            raise DataError(f"Conflicting profile definition: {row.profile.id}")
        if row.claim.id in claims and claims[row.claim.id] != row.claim:
            raise DataError(f"Conflicting claim definition: {row.claim.id}")
        profiles[row.profile.id] = row.profile
        claims[row.claim.id] = row.claim
        groups[row.profile.id].append(row)
    if len(results) > first.planned_trials:
        raise DataError("Observed trials exceed the planned trial count")
    return Analysis(
        run_id=first.run_id,
        prompt_version=first.prompt_version,
        planned_trials=first.planned_trials,
        observed_trials=len(results),
        complete=len(results) == first.planned_trials,
        overall=_metrics(results),
        by_profile={key: _metrics(rows) for key, rows in sorted(groups.items())},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze moral memory results without API calls")
    parser.add_argument("results", type=Path)
    parser.add_argument("--output", type=Path, help="New versioned JSON summary file")
    args = parser.parse_args()
    try:
        summary = analyze(load_jsonl(args.results, ExperimentResult))
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8"):
                pass
            save_json(args.output, summary)
    except (LLMKitError, OSError) as exc:
        parser.exit(1, f"{type(exc).__name__}: {exc}\n")
    print(summary.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

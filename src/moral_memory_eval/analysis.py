"""Offline analysis of validated manifest-linked runs, including partial runs."""

from collections import defaultdict
from pathlib import Path

from moral_memory_eval.execution import load_run, validate_completed
from moral_memory_eval.metrics import calculate_metrics
from moral_memory_eval.schemas import PreparedAnalysis, PreparedResult, PreparedRun


def analyze_results(run: PreparedRun, results: list[PreparedResult]) -> PreparedAnalysis:
    completed = validate_completed(run, results)
    planned = {entry.trial_id for entry in run.manifest}
    groups: dict[str, list[PreparedResult]] = defaultdict(list)
    for row in results:
        groups[row.profile_id].append(row)
    return PreparedAnalysis(
        run_id=run.run_id,
        preparation_sha256=run.preparation.preparation_sha256,
        planned_trials=len(planned),
        observed_trials=len(completed),
        complete=planned == completed,
        completed_trial_ids=[
            entry.trial_id for entry in run.manifest if entry.trial_id in completed
        ],
        pending_trial_ids=[
            entry.trial_id for entry in run.manifest if entry.trial_id not in completed
        ],
        overall=calculate_metrics([(row.expected, row.verdict) for row in results])
        if results
        else None,
        by_profile={
            profile_id: calculate_metrics([(row.expected, row.verdict) for row in rows])
            for profile_id, rows in sorted(groups.items())
        },
    )


def analyze_run(output: Path) -> PreparedAnalysis:
    run, results = load_run(output)
    return analyze_results(run, results)

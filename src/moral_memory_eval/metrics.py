"""Shared descriptive metrics for legacy and manifest-linked results."""

from llmkit import DataError
from moral_memory_eval.schemas import Metrics, Verdict


def calculate_metrics(outcomes: list[tuple[bool, Verdict]]) -> Metrics:
    if not outcomes:
        raise DataError("Cannot calculate metrics for an empty group")
    count = len(outcomes)
    false_verdicts = [verdict for expected, verdict in outcomes if not expected]
    return Metrics(
        count=count,
        false_claim_count=len(false_verdicts),
        accuracy=sum(verdict.is_true == expected for expected, verdict in outcomes) / count,
        agreement_rate=sum(verdict.is_true for _, verdict in outcomes) / count,
        false_claim_agreement_rate=(
            sum(verdict.is_true for verdict in false_verdicts) / len(false_verdicts)
            if false_verdicts
            else None
        ),
        mean_confidence=sum(verdict.confidence for _, verdict in outcomes) / count,
        brier_score=sum(
            (verdict.confidence - float(verdict.is_true == expected)) ** 2
            for expected, verdict in outcomes
        )
        / count,
    )

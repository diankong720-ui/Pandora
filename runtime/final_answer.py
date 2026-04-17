from __future__ import annotations

from typing import Any

from runtime.evaluation import CONCLUSION_STATES, INCOMPLETENESS_CATEGORIES
from runtime.persistence import list_round_bundles, load_session_evidence, persist_artifact


FINAL_ANSWER_REQUIRED_FIELDS = (
    "session_slug",
    "conclusion_state",
    "headline_conclusion",
    "supported_claims",
    "contradictions",
    "residual_summary",
    "correction_mode",
    "incompleteness_category",
    "recommended_follow_up",
)


def get_latest_round_evaluation(slug: str) -> dict[str, Any] | None:
    """Return the latest persisted RoundEvaluationResult based on round_number."""
    latest: dict[str, Any] | None = None
    latest_round_number = -1
    for bundle in list_round_bundles(slug):
        evaluation = bundle.get("evaluation")
        if not isinstance(evaluation, dict):
            continue
        round_number = evaluation.get("round_number")
        if isinstance(round_number, int) and round_number >= latest_round_number:
            latest = evaluation
            latest_round_number = round_number
    return latest


def validate_final_answer(
    final_answer: dict[str, Any],
    *,
    slug: str | None = None,
    latest_evaluation: dict[str, Any] | None = None,
) -> None:
    missing = [field for field in FINAL_ANSWER_REQUIRED_FIELDS if field not in final_answer]
    if missing:
        raise ValueError(f"FinalAnswer missing required fields: {', '.join(missing)}")

    if slug is not None and final_answer["session_slug"] != slug:
        raise ValueError("FinalAnswer.session_slug must match the session slug.")

    if final_answer["conclusion_state"] not in CONCLUSION_STATES:
        raise ValueError("FinalAnswer.conclusion_state is invalid.")
    if final_answer["incompleteness_category"] not in INCOMPLETENESS_CATEGORIES:
        raise ValueError("FinalAnswer.incompleteness_category is invalid.")

    residual_summary = final_answer["residual_summary"]
    if not isinstance(residual_summary, dict):
        raise ValueError("FinalAnswer.residual_summary must be an object.")
    for field in ("residual_score", "residual_band", "current_unexplained_ratio", "open_questions"):
        if field not in residual_summary:
            raise ValueError(f"FinalAnswer.residual_summary missing field: {field}")

    if latest_evaluation is not None:
        if final_answer["conclusion_state"] != latest_evaluation.get("conclusion_state"):
            raise ValueError(
                "FinalAnswer.conclusion_state must match the latest RoundEvaluationResult.conclusion_state."
            )


def persist_final_answer(slug: str, final_answer: dict[str, Any]) -> str:
    """Validate FinalAnswer against the latest round evaluation and persist it."""
    validate_final_answer(
        final_answer,
        slug=slug,
        latest_evaluation=get_latest_round_evaluation(slug),
    )
    return persist_artifact(slug, "final_answer.json", final_answer)


def build_final_answer_context(slug: str) -> dict[str, Any]:
    """Return the artifact-backed context needed by a final-answer producer."""
    session_evidence = load_session_evidence(slug)
    session_evidence["latest_round_evaluation"] = get_latest_round_evaluation(slug)
    return session_evidence

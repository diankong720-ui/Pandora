from __future__ import annotations

from typing import Any

from runtime.persistence import persist_round_bundle, read_round_bundle


ROUND_EVALUATION_REQUIRED_FIELDS = (
    "round_id",
    "round_number",
    "contract_id",
    "hypothesis_updates",
    "residual_update",
    "residual_score",
    "residual_band",
    "open_questions",
    "scores",
    "recommended_next_action",
    "should_continue",
    "stop_reason",
    "operator_gain",
    "gain_direction",
    "confidence_shift",
    "correction_mode",
    "conclusion_state",
    "incompleteness_category",
)

RECOMMENDED_NEXT_ACTIONS = {"refine", "pivot", "stop", "restart"}
GAIN_DIRECTIONS = {"positive", "flat", "negative"}
CONFIDENCE_SHIFTS = {"up", "flat", "down"}
CONCLUSION_STATES = {
    "completed",
    "partial_answer_available",
    "restart_required",
    "blocked_runtime",
}
INCOMPLETENESS_CATEGORIES = {
    "",
    "warehouse_load",
    "budget_exhausted",
    "no_progress",
    "schema_gap",
    "correction_mode",
}
RESIDUAL_BANDS = {"very_high", "high", "medium", "low", "very_low"}
RESIDUAL_CONFIDENCE_BANDS = {"low", "medium", "high"}
WAREHOUSE_BURDEN_LEVELS = {"low", "medium", "high"}
USABLE_EVIDENCE_STATUSES = {"success", "cached"}


def summarize_execution_outcomes(executed_queries: list[dict[str, Any]]) -> dict[str, int]:
    """Count execution outcomes by status family for evaluator/runtime guards."""
    summary = {
        "usable": 0,
        "degraded": 0,
        "failed": 0,
        "blocked": 0,
        "success": 0,
        "cached": 0,
        "degraded_to_cache": 0,
        "timeout": 0,
        "failed_status": 0,
    }
    for query in executed_queries:
        status = query.get("status")
        if status in USABLE_EVIDENCE_STATUSES:
            summary["usable"] += 1
        elif status == "degraded_to_cache":
            summary["degraded"] += 1
            summary["degraded_to_cache"] += 1
            continue
        else:
            summary["failed"] += 1
        if status == "blocked":
            summary["blocked"] += 1
        elif status == "success":
            summary["success"] += 1
        elif status == "cached":
            summary["cached"] += 1
        elif status == "timeout":
            summary["timeout"] += 1
        elif status == "failed":
            summary["failed_status"] += 1
    return summary


def blocked_runtime_preconditions_met(executed_queries: list[dict[str, Any]]) -> bool:
    """
    blocked_runtime is legal only when no usable evidence exists and runtime
    blocking prevented execution.
    """
    if not executed_queries:
        return False
    summary = summarize_execution_outcomes(executed_queries)
    return summary["usable"] == 0 and summary["blocked"] > 0 and summary["degraded"] == 0


def validate_round_evaluation_result(
    evaluation: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
    executed_queries: list[dict[str, Any]] | None = None,
) -> None:
    missing = [field for field in ROUND_EVALUATION_REQUIRED_FIELDS if field not in evaluation]
    if missing:
        raise ValueError(
            f"RoundEvaluationResult missing required fields: {', '.join(missing)}"
        )

    if evaluation["recommended_next_action"] not in RECOMMENDED_NEXT_ACTIONS:
        raise ValueError("RoundEvaluationResult.recommended_next_action is invalid.")
    if evaluation["gain_direction"] not in GAIN_DIRECTIONS:
        raise ValueError("RoundEvaluationResult.gain_direction is invalid.")
    if evaluation["confidence_shift"] not in CONFIDENCE_SHIFTS:
        raise ValueError("RoundEvaluationResult.confidence_shift is invalid.")
    if evaluation["conclusion_state"] not in CONCLUSION_STATES:
        raise ValueError("RoundEvaluationResult.conclusion_state is invalid.")
    if evaluation["incompleteness_category"] not in INCOMPLETENESS_CATEGORIES:
        raise ValueError("RoundEvaluationResult.incompleteness_category is invalid.")
    if evaluation["residual_band"] not in RESIDUAL_BANDS:
        raise ValueError("RoundEvaluationResult.residual_band is invalid.")

    residual_update = evaluation["residual_update"]
    if not isinstance(residual_update, dict):
        raise ValueError("RoundEvaluationResult.residual_update must be an object.")
    if residual_update.get("confidence_band") not in RESIDUAL_CONFIDENCE_BANDS:
        raise ValueError("RoundEvaluationResult.residual_update.confidence_band is invalid.")
    for field in ("stalled_round_streak", "negative_gain_streak"):
        value = residual_update.get(field)
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"RoundEvaluationResult.residual_update.{field} must be a non-negative integer.")

    scores = evaluation["scores"]
    if not isinstance(scores, dict):
        raise ValueError("RoundEvaluationResult.scores must be an object.")
    if scores.get("warehouse_burden") not in WAREHOUSE_BURDEN_LEVELS:
        raise ValueError("RoundEvaluationResult.scores.warehouse_burden is invalid.")

    if contract is not None:
        if evaluation["contract_id"] != contract.get("contract_id"):
            raise ValueError("RoundEvaluationResult.contract_id must match the persisted contract.")
        if evaluation["round_number"] != contract.get("round_number"):
            raise ValueError("RoundEvaluationResult.round_number must match the persisted contract.")

    if evaluation["conclusion_state"] == "blocked_runtime":
        if executed_queries is None or not blocked_runtime_preconditions_met(executed_queries):
            raise ValueError(
                "blocked_runtime requires zero usable evidence and at least one runtime-blocked query."
            )

    if evaluation["should_continue"] and evaluation["recommended_next_action"] in {"stop", "restart"}:
        raise ValueError(
            "RoundEvaluationResult.should_continue cannot be true when recommended_next_action is stop or restart."
        )
    if not evaluation["should_continue"] and evaluation["recommended_next_action"] in {"refine", "pivot"}:
        raise ValueError(
            "RoundEvaluationResult.should_continue cannot be false when recommended_next_action is refine or pivot."
        )
    if evaluation["correction_mode"] and evaluation["incompleteness_category"] not in {"", "correction_mode"}:
        raise ValueError(
            "RoundEvaluationResult.correction_mode should only use incompleteness_category '' or 'correction_mode'."
        )


def persist_round_evaluation(
    slug: str,
    evaluation: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
    executed_queries: list[dict[str, Any]] | None = None,
) -> str:
    """
    Persist a validated RoundEvaluationResult into the formal round bundle.

    If contract/executed_queries are omitted, they are loaded from the existing
    round bundle identified by evaluation.round_id.
    """
    round_id = evaluation.get("round_id")
    if not isinstance(round_id, str) or not round_id:
        raise ValueError("RoundEvaluationResult.round_id must be a non-empty string.")

    existing_bundle = read_round_bundle(slug, round_id)
    if contract is None and existing_bundle is not None:
        contract = existing_bundle.get("contract")
    if executed_queries is None and existing_bundle is not None:
        executed_queries = existing_bundle.get("executed_queries")

    if not isinstance(contract, dict):
        raise ValueError("persist_round_evaluation requires a contract or an existing round bundle.")
    if not isinstance(executed_queries, list):
        raise ValueError("persist_round_evaluation requires executed_queries or an existing round bundle.")

    validate_round_evaluation_result(
        evaluation,
        contract=contract,
        executed_queries=executed_queries,
    )
    return persist_round_bundle(slug, round_id, contract, executed_queries, evaluation)

# Shared Contracts

This document is the single source of truth for all cross-stage objects used by the Deep Research skill family.

Rules:

- Shared object schemas are defined here once.
- Skill documents may reference these contracts and add stage-local rules.
- Skill documents must not redefine shared object shapes with conflicting fields.
- If a field is removed or renamed, update this file first and then update the stage docs that consume it.

---

## 1. IntentRecognitionResult

Produced by Stage 1 `intent-recognition`.

```json
{
  "normalized_intent": {},
  "pack_gaps": []
}
```

Fields:

- `normalized_intent`: required `NormalizedIntent`
- `pack_gaps`: required array; empty when no pack gaps were detected

`pack_gaps` is a session sidecar. It is not part of the frozen `NormalizedIntent`.

---

## 2. NormalizedIntent

Produced by Stage 1. Frozen after downstream stages begin.

```json
{
  "intent_id": "sales_drop_last_month",
  "raw_question": "why did sales drop last month",
  "question_style": "comparative",
  "problem_type": "root_cause_analysis",
  "primary_problem_type": "Root Cause Analysis",
  "business_object": {
    "label": "all orders",
    "entity_type": "business_scope"
  },
  "core_metric": "sales_amount",
  "time_scope": {
    "primary": {
      "label": "Mar 2026",
      "start": "2026-03-01",
      "end": "2026-03-31",
      "grain": "month"
    }
  },
  "comparison_scope": {
    "type": "mom",
    "windows": [
      {
        "key": "primary",
        "label": "Mar 2026",
        "start": "2026-03-01",
        "end": "2026-03-31"
      },
      {
        "key": "comparison_1",
        "label": "Feb 2026",
        "start": "2026-02-01",
        "end": "2026-02-28"
      }
    ]
  },
  "dimensions": [],
  "filters": [],
  "intent_profile": {
    "metric_verification": 0.1,
    "comparison": 0.8,
    "audit": 0.4,
    "driver_diagnosis": 0.9,
    "structure_analysis": 0.2,
    "segment_contribution": 0.2,
    "fulfillment_linkage": 0.0
  },
  "problem_type_scores": [
    {
      "problem_type": "root_cause_analysis",
      "score": 0.92
    },
    {
      "problem_type": "trend_comparison",
      "score": 0.61
    }
  ],
  "domain_pack_id": "generic",
  "mapping_confidence": "high",
  "clarification_needed": false,
  "clarification_reasons": [],
  "clarification_request": null
}
```

Required fields:

- All top-level fields shown above are required.
- `time_scope.primary` is required.
- `comparison_scope.windows` may be empty only when `comparison_scope.type = "none"`.
- `clarification_request` must be non-null when `clarification_needed = true`.

Enumerations:

- `question_style`: `abstract | operational | comparative`
- `business_object.entity_type`: `business_scope | channel | product | region | seller`
- `time_scope.primary.grain`: `day | week | month | quarter | year | rolling_window | unknown`
- `comparison_scope.type`: `none | mom | yoy | explicit | custom`
- `mapping_confidence`: `high | low`

Canonical default `problem_type` values:

- `metric_read`
- `trend_comparison`
- `root_cause_analysis`
- `segment_comparison`
- `distribution_scan`
- `operational_diagnosis`
- `data_quality_audit`

Rules:

- Relative time references are anchored to `current_date`.
- `primary_problem_type` is the display label for `problem_type`; do not invent new semantics in this field.
- `filters` use business-semantic field ids only. They never contain physical table or column names.
- Once Stage 2 starts, `NormalizedIntent` is frozen. If it is wrong, rebuild Stage 1 output from scratch.

---

## 3. PackGap

Produced by Stage 1 and persisted as session sidecar data.

```json
[
  {
    "category": "metric_alias",
    "user_term": "sales",
    "resolved_to": "sales_amount",
    "confidence": "high",
    "note": "Resolved by general business vocabulary because the active pack had no explicit alias."
  }
]
```

Enumerations:

- `category`: `metric_alias | dimension_alias | unsupported_dimension`
- `confidence`: `high | low`

---

## 4. DataContextBundle

Produced by Stage 2 `data-discovery`.

```json
{
  "intent_id": "sales_drop_last_month",
  "environment_scan": {
    "visible_tables": [],
    "table_profiles": [],
    "cache_facts": [],
    "warehouse_snapshot": {
      "load_state": "normal",
      "admission_mode": "normal"
    }
  },
  "schema_map": {
    "fact_tables": [
      {
        "table": "mart_order_daily",
        "role": "headline_fact",
        "grain": "day",
        "time_fields": ["order_date"],
        "dimension_fields": ["channel", "product_category", "region"],
        "join_keys": ["product_id", "region_id"]
      }
    ],
    "support_tables": []
  },
  "metric_mapping": {
    "sales_amount": {
      "table": "mart_order_daily",
      "expression": "SUM(pay_amount)",
      "time_field": "order_date",
      "default_filters": []
    },
    "order_count": {
      "table": "mart_order_daily",
      "expression": "COUNT(DISTINCT order_id)",
      "time_field": "order_date",
      "default_filters": []
    }
  },
  "time_fields": {
    "primary_time_field": "order_date",
    "alternatives": ["pay_date"],
    "notes": []
  },
  "dimension_fields": {
    "channel": {
      "table": "mart_order_daily",
      "field": "channel",
      "support_tier": "ga"
    }
  },
  "supported_dimension_capabilities": {
    "channel": "ga",
    "product": "beta"
  },
  "joinability": {
    "join_paths": [
      {
        "from_table": "mart_order_daily",
        "to_table": "dim_product",
        "join_key": "product_id",
        "status": "validated"
      }
    ],
    "notes": []
  },
  "comparison_feasibility": {
    "status": "supported",
    "reason": "Primary metric and comparison window share a validated time field."
  },
  "warehouse_load_status": "normal",
  "report_conflict_hint": false,
  "quality_report": {
    "status": "pass",
    "issues": []
  },
  "evidence_status": "available"
}
```

Required fields:

- All top-level fields shown above are required.
- `schema_map`, `metric_mapping`, `time_fields`, `dimension_fields`, `joinability`, and `comparison_feasibility` must always be present, even if partially empty.

Enumerations:

- `supported_dimension_capabilities[dimension_id]`: `ga | beta | unsupported`
- `comparison_feasibility.status`: `supported | partial | blocked`
- `warehouse_load_status`: `normal | constrained | degraded`
- `quality_report.status`: `pass | warn | block`
- `evidence_status`: `available | partial | blocked`
- `joinability.join_paths[].status`: `validated | partial | blocked`

Rules:

- `DataContextBundle` contains discovery findings only.
- It must not include verification outcomes such as headline validation or computed metric deltas.
- `report_conflict_hint` may only describe discovery-time risks such as ambiguous source tables, missing critical fields, suspicious samples, or probe errors.
- `comparison_feasibility` describes whether comparison SQL can be constructed safely from the validated schema. It does not mean the comparison has already been executed.

---

## 5. HypothesisBoardItem

Produced by Stage 3 `hypothesis-engine`.

```json
{
  "hypothesis_id": "H1",
  "family": "audit_scope",
  "class": "audit",
  "layer": "audit",
  "statement": "The observed decline is affected by scope or business-object mismatch.",
  "relevance_score": 0.72,
  "evidence_basis": "Question asks why sales dropped; discovery found two candidate sales fact tables and a conflict hint.",
  "schema_feasibility": "feasible",
  "status": "proposed",
  "query_plan": [
    {
      "query_id": "q_audit_headline_primary",
      "description": "Verify headline sales metric for primary window using the chosen fact table.",
      "supports_contract_query_id": "q_round1_headline_primary",
      "expected_signal": "If the metric exists and matches the intended scope, audit risk decreases.",
      "notes": []
    }
  ],
  "notes": []
}
```

Enumerations:

- `class`: `audit | driver`
- `layer`: `audit | demand | value | structure | fulfillment`
- `schema_feasibility`: `feasible | not_testable`
- `status`: `proposed | supported | weakened | rejected | not_tested | blocked_by_load`

Rules:

- `query_plan` is explanatory planning metadata. It is not the execution surface.
- Execution uses `InvestigationContract.queries[]` only.

---

## 6. QueryExecutionRequest

This is the only executable query contract for Stage 4.

```json
{
  "query_id": "q_round1_headline_primary",
  "description": "Verify primary-window headline sales metric.",
  "sql": "SELECT SUM(pay_amount) AS sales_amount FROM mart_order_daily WHERE order_date >= '2026-03-01' AND order_date <= '2026-03-31'",
  "workspace": "default",
  "output_name": "headline_sales_primary",
  "cache_policy": "allow_read",
  "queue_once_allowed": true,
  "cost_class": "cheap"
}
```

Enumerations:

- `cache_policy`: `bypass | allow_read | require_read`
- `cost_class`: `cheap | standard`

Rules:

- `sql` is required.
- Runtime execution must not infer SQL from semantic placeholders.
- `output_name` must be unique within the contract.

---

## 7. InvestigationContract

Produced by Stage 3 for Round 1 and by the orchestrator after each evaluation for subsequent rounds.

```json
{
  "contract_id": "round_1_audit",
  "round_number": 1,
  "operator_id": "audit_baseline",
  "target_hypotheses": ["H1", "H2"],
  "sql_budget": 2,
  "allowed_cost_classes": ["cheap"],
  "queries": [],
  "pass_conditions": [
    "Primary metric exists for the intended scope.",
    "No restart-worthy scope mismatch is found."
  ],
  "pivot_conditions": [
    "Audit SQL is blocked by runtime safety checks.",
    "Evidence contradicts the intended business object or time field."
  ],
  "max_rounds": 3,
  "notes": []
}
```

Required fields:

- All top-level fields shown above are required.
- `queries` is a list of `QueryExecutionRequest`.

Rules:

- `round_number = 1` must be audit-first.
- Round 1 target hypotheses must all come from the audit layer.
- `queries[]` must be directly executable without downstream inference.

---

## 8. PlanBundle

Produced by Stage 3 `hypothesis-engine`.

```json
{
  "hypothesis_board": [],
  "round_1_contract": {},
  "planning_notes": [],
  "max_rounds": 3
}
```

Required fields:

- `hypothesis_board`: required array of `HypothesisBoardItem`
- `round_1_contract`: required `InvestigationContract`
- `planning_notes`: required array of strings
- `max_rounds`: required integer

Rules:

- `round_1_contract.max_rounds` and `PlanBundle.max_rounds` must match.

---

## 9. QueryExecutionResult

Produced by runtime tools during Stage 4.

```json
{
  "query_id": "q_round1_headline_primary",
  "description": "Verify primary-window headline sales metric.",
  "status": "success",
  "rows_preview": [],
  "cost_class": "cheap",
  "source": "live",
  "notes": []
}
```

Enumerations:

- `status`: `success | cached | degraded_to_cache | failed | timeout | blocked`
- `source`: `live | cache`

---

## 10. RoundEvaluationResult

Produced by Stage 5 `investigation-evaluator`.

```json
{
  "round_id": "round_1",
  "round_number": 1,
  "contract_id": "round_1_audit",
  "hypothesis_updates": [],
  "residual_update": {
    "explained_components": [],
    "revoked_components": [],
    "layer_explained_share": {
      "audit": 0.0,
      "demand": 0.0,
      "value": 0.0,
      "structure": 0.0,
      "fulfillment": 0.0
    },
    "current_unexplained_ratio": 1.0,
    "confidence_band": "low",
    "stalled_round_streak": 0,
    "negative_gain_streak": 0,
    "operator_gain_note": "Audit validated the metric but did not yet explain the business driver."
  },
  "residual_score": 82,
  "residual_band": "high",
  "open_questions": [
    "Is the decline primarily demand-driven or value-driven?"
  ],
  "scores": {
    "scope_fidelity": 4,
    "evidence_strength": 3,
    "explanatory_power": 2,
    "contradiction_integrity": 4,
    "business_actionability": 2,
    "warehouse_burden": "low"
  },
  "recommended_next_action": "refine",
  "should_continue": true,
  "stop_reason": "round_complete",
  "operator_gain": 0.18,
  "gain_direction": "positive",
  "confidence_shift": "flat",
  "correction_mode": false,
  "conclusion_state": "partial_answer_available",
  "incompleteness_category": ""
}
```

Required fields:

- All top-level fields shown above are required.

Enumerations:

- `recommended_next_action`: `refine | pivot | stop | restart`
- `gain_direction`: `positive | flat | negative`
- `confidence_shift`: `up | flat | down`
- `conclusion_state`: `completed | partial_answer_available | restart_required | blocked_runtime`
- `incompleteness_category`: `"" | warehouse_load | budget_exhausted | no_progress | schema_gap | correction_mode`
- `residual_band`: `very_high | high | medium | low | very_low`
- `residual_update.confidence_band`: `low | medium | high`
- `scores.warehouse_burden`: `low | medium | high`

Rules:

- `conclusion_state = blocked_runtime` is reserved for sessions where no successful or cached evidence was gathered and runtime blocking prevented all execution.
- `correction_mode` is not a conclusion state; it is a flag and may also set `incompleteness_category = "correction_mode"` when a partial answer must stop there.
- `stalled_round_streak` counts consecutive `flat` or `negative` rounds.
- `negative_gain_streak` counts consecutive `negative` rounds only.

---

## 11. FinalAnswer

Produced when the investigation ends.

```json
{
  "session_slug": "sales_drop_last_month",
  "conclusion_state": "partial_answer_available",
  "headline_conclusion": "The sales decline is real. Demand weakness appears primary, but value effects remain partially open.",
  "supported_claims": [],
  "contradictions": [],
  "residual_summary": {
    "residual_score": 46,
    "residual_band": "medium",
    "current_unexplained_ratio": 0.41,
    "open_questions": []
  },
  "correction_mode": false,
  "incompleteness_category": "budget_exhausted",
  "recommended_follow_up": []
}
```

Required fields:

- All top-level fields shown above are required.

Rules:

- Every supported claim must be traceable to specific query results.
- `conclusion_state` must match the final `RoundEvaluationResult`.

---

## 12. DomainPackSuggestions

Produced during Domain Pack Suggestion Synthesis after the session has already ended.

```json
{
  "session_slug": "sales_drop_last_month",
  "active_pack_id": "generic",
  "target_pack_id": "your_company",
  "suggested_updates": {
    "taxonomy": {
      "problem_types": []
    },
    "lexicon": {
      "metrics": [],
      "dimensions": [],
      "business_aliases": [],
      "unsupported_dimensions": []
    },
    "performance_risks": [],
    "driver_family_templates": {},
    "domain_priors": {},
    "operator_preferences": {}
  },
  "note": "Merge approved suggestions into the target domain pack."
}
```

Required fields:

- All top-level fields shown above are required.
- `suggested_updates` must mirror the pack schema categories documented in `DOMAIN_PACK_GUIDE.md`.

Rules:

- This object is advisory only. It does not modify the active pack for the current session.
- Only suggest updates for fields that belong to the pack schema.
- `target_pack_id` selection rule:
  - if a non-generic company pack already exists for this business context, reuse that existing `pack_id`
  - otherwise, when the session reflects a new company or business domain, generate a new deterministic slug and use it as `target_pack_id`
- Deterministic slug rule:
  - derive the slug from the best available stable business label such as company name, platform name, or business object label
  - normalize to lowercase ASCII snake_case
  - replace spaces and punctuation with single underscores
  - collapse repeated underscores
  - trim leading and trailing underscores
  - use the same input label for the same business context so repeated sessions produce the same slug
- If no gaps or useful suggestions exist, do not write `domain_pack_suggestions.json`.

---

## 13. Artifact Layout

The persistence layer writes explicit objects only.

```text
RESEARCH/<slug>/
  intent.json                  -> NormalizedIntent
  intent_sidecar.json          -> { pack_gaps: PackGap[] }
  environment_scan.json        -> DataContextBundle
  plan.json                    -> PlanBundle
  rounds/
    <round_id>.json            -> {
                                   contract: InvestigationContract,
                                   executed_queries: QueryExecutionResult[],
                                   evaluation: RoundEvaluationResult
                                 }
  execution_log.json           -> execution metadata retained by the runtime
  final_answer.json            -> FinalAnswer
  domain_pack_suggestions.json -> DomainPackSuggestions only when needed
  manifest.json                -> session metadata
```

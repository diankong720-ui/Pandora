---
name: deep-research
description: Official user-facing orchestrator for business research. The LLM owns decisions; the runtime provides tools, safety checks, execution, and persistence.
---

# Deep Research

This is the official user-facing skill.

It orchestrates the full multi-stage research session while keeping strict responsibility boundaries between the LLM and the runtime.

---

## Required Serial Flow

```text
1. Intent Recognition     -> IntentRecognitionResult
2. Environment Discovery  -> DataContextBundle
3. Planning              -> PlanBundle
4. Execution             -> QueryExecutionResult[]
5. Evaluation            -> RoundEvaluationResult
6. Persist Artifacts     -> RESEARCH/<slug>/
7. Domain Pack Suggestion Synthesis -> domain_pack_suggestions.json (best effort)
```

Stages must not be skipped or reordered.

---

## Runtime Tool Surface

The runtime exposes tools. The LLM decides how to use them.

### 1. Schema probe tools

Used during Stage 2 only.

They may return:

- visible tables
- headers
- sample rows
- warehouse load facts
- cache metadata for explicit SQL already known to the session

They do not recommend tables, joins, fields, or metrics.

### 2. Cache lookup tools

Used during execution planning or execution review when the LLM already has an explicit SQL statement.

They may return:

- hit or miss
- metadata path
- source identity
- preview rows when available

They do not decide whether the cached evidence is sufficient.

### 3. SQL execution tools

Used during Stage 4 only.

Execution requires explicit `QueryExecutionRequest` fields from `contracts.md`, including:

- exact `sql`
- `workspace`
- `output_name`
- `cache_policy`
- `queue_once_allowed`
- `cost_class`

The runtime may:

- validate SQL safety
- reject non-whitelisted tables
- enforce warehouse admission
- return cached results
- execute under the declared contract

The runtime must not:

- rewrite SQL
- infer joins or filters
- compile semantic placeholders into executable SQL

### 4. Artifact persistence tools

Used during Stage 6 and Domain Pack Suggestion Synthesis only.

The runtime writes explicit objects. It does not infer missing report fields.

---

## LLM Responsibilities

The LLM is responsible for:

- deciding whether this skill should be used
- deciding whether clarification is required
- interpreting the business question
- selecting the active domain pack unless forced
- producing `NormalizedIntent`
- producing `DataContextBundle`
- producing `PlanBundle`
- choosing whether to continue, pivot, stop, or restart after each evaluation
- producing the final answer and any domain pack suggestions

---

## Artifact Contract

Persist the explicit objects defined in `contracts.md`.

```text
RESEARCH/<slug>/
  intent.json                  -> NormalizedIntent
  intent_sidecar.json          -> { pack_gaps: PackGap[] }
  environment_scan.json        -> DataContextBundle
  plan.json                    -> PlanBundle
  rounds/
    <round_id>.json            -> { contract, executed_queries, evaluation }
  execution_log.json           -> runtime execution metadata
  final_answer.json            -> FinalAnswer
  domain_pack_suggestions.json -> DomainPackSuggestions only when gaps were found
  manifest.json                -> session metadata
```

Do not write files that are not backed by explicit LLM output or runtime facts.

---

## Domain Pack Suggestion Synthesis

Run this stage after `final_answer.json` is written.

Trigger this stage when either is true:

- `pack_gaps` from `intent_sidecar.json` is non-empty
- `normalized_intent.domain_pack_id = "generic"`

What this stage may suggest:

- `taxonomy.problem_types` additions
- `lexicon.metrics` aliases
- `lexicon.dimensions` aliases
- `lexicon.business_aliases`
- `lexicon.unsupported_dimensions`
- `performance_risks`
- `driver_family_templates`
- `domain_priors`
- `operator_preferences`

Persist `domain_pack_suggestions.json` as `DomainPackSuggestions` from `contracts.md`.

`target_pack_id` rule:

- if a matching non-generic company pack already exists, reuse its `pack_id`
- otherwise, for a new company or business domain, generate a deterministic slug and use it as the new `target_pack_id`

This is a best-effort post-session artifact. It must not block the final answer.

---

## Non-Negotiable Rules

- Follow the shared contracts in `contracts.md`.
- Do not expect the runtime to classify the task or choose the next round.
- Do not mutate `NormalizedIntent` in place. Rebuild it if the audit requires restart.
- Do not skip audit-first planning for Round 1.
- Keep cached evidence explicitly labeled.
- Keep runtime blocking facts explicit when `blocked_runtime` is the final state.

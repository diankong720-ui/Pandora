# Deep Research Skill Family

This project is a contract-first, LLM-driven business research skill stack.

Its current state is no longer "documentation plus generic utilities". The
shared contracts, skill docs, runtime execution layer, artifact persistence,
and validation helpers are now aligned around one explicit workflow.

Core boundary:

- The `LLM` owns semantic interpretation, intent normalization, schema reasoning,
  hypothesis planning, SQL authorship, evaluation content, and final conclusions.
- The `runtime` owns safety validation, query execution, cache behavior,
  warehouse admission, artifact persistence, and contract-level consistency
  checks.
- The `runtime` never compiles or templates SQL from semantic placeholders.

---

## What Is Closed

This repository is now logically closed across both docs and runtime:

- the stage flow is explicit
- the shared objects have one contract source
- runtime consumes the execution contracts directly
- round outputs and final outputs are persisted in the documented shapes
- post-session domain pack suggestions have deterministic target-pack behavior

The result is a system where an implementer can follow the docs and map every
stage output to a concrete runtime handoff.

---

## Stage Flow

The serial flow is mandatory.

```text
1. intent-recognition              -> IntentRecognitionResult
2. data-discovery                  -> DataContextBundle
3. hypothesis-engine               -> PlanBundle
4. execution                       -> QueryExecutionResult[]
5. investigation-evaluator         -> RoundEvaluationResult
6. persistence                     -> RESEARCH/<slug>/
7. domain pack suggestion synthesis -> domain_pack_suggestions.json (best effort)
```

Rules:

- stages must not be skipped or reordered
- `NormalizedIntent` is frozen after Stage 1
- Stage 2 is discovery-only; it does not verify the headline metric or compute deltas
- Stage 4 executes only explicit `InvestigationContract.queries[]`
- Stage 5 does not invent execution evidence; it evaluates persisted query results
- domain pack suggestion synthesis is post-session only and must not block the final answer

---

## Primary Documents

- [contracts.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/deep-research/references/contracts.md): single source of truth for shared contracts
- [core-methodology.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/deep-research/references/core-methodology.md): residual logic, stop policy, and conclusion-state discipline
- [intent-recognition/SKILL.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/intent-recognition/SKILL.md): Stage 1 intent normalization
- [data-discovery/SKILL.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/data-discovery/SKILL.md): Stage 2 environment discovery
- [hypothesis-engine.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/deep-research/sub-skills/hypothesis-engine.md): Stage 3 planning
- [investigation-evaluator.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/deep-research/sub-skills/investigation-evaluator.md): Stage 5 evaluation rules
- [DOMAIN_PACK_GUIDE.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/deep-research/domain-packs/DOMAIN_PACK_GUIDE.md): domain pack schema and consumer matrix

If a stage doc conflicts with a shared object definition, `contracts.md` wins.

---

## Runtime Surface

The runtime is no longer just a set of isolated helpers. It now exposes formal
handoff points for the documented contracts.

Primary runtime entrypoints:

- [runtime/tools.py](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/runtime/tools.py): `execute_query_request()` and legacy `execute_sql()`
- [runtime/orchestration.py](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/runtime/orchestration.py): `execute_investigation_contract()`, `execute_round_and_persist()`, `finalize_session()`
- [runtime/evaluation.py](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/runtime/evaluation.py): `RoundEvaluationResult` validation and persistence
- [runtime/final_answer.py](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/runtime/final_answer.py): `FinalAnswer` validation and persistence
- [runtime/domain_pack_suggestions.py](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/runtime/domain_pack_suggestions.py): domain pack suggestion validation and persistence
- [runtime/persistence.py](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/runtime/persistence.py): artifact I/O, execution log, round bundles, session evidence loading
- [runtime/domain_packs.py](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/runtime/domain_packs.py): pack registry and deterministic target-pack resolution

Runtime guarantees:

- executes only LLM-authored SQL
- validates single-statement safety before execution
- enforces `cache_policy` as `bypass | allow_read | require_read`
- records execution metadata in `execution_log.json`
- persists round bundles in the documented `{ contract, executed_queries, evaluation }` shape
- validates `blocked_runtime` and `FinalAnswer.conclusion_state` consistency

Runtime does not:

- infer joins, filters, or time windows
- compile semantic query plans into SQL
- generate evaluator reasoning or final conclusions

---

## Core Objects

All shared objects are defined in `contracts.md`.

- `IntentRecognitionResult`
- `NormalizedIntent`
- `PackGap`
- `DataContextBundle`
- `HypothesisBoardItem`
- `QueryExecutionRequest`
- `InvestigationContract`
- `PlanBundle`
- `QueryExecutionResult`
- `RoundEvaluationResult`
- `FinalAnswer`
- `DomainPackSuggestions`

---

## Artifact Layout

Each session persists explicit objects only.

```text
RESEARCH/<slug>/
  intent.json
  intent_sidecar.json
  environment_scan.json
  plan.json
  rounds/
    <round_id>.json
  execution_log.json
  final_answer.json
  domain_pack_suggestions.json
  manifest.json
```

Artifact semantics:

- `intent.json` stores `NormalizedIntent`
- `intent_sidecar.json` stores `pack_gaps`
- `environment_scan.json` stores `DataContextBundle`
- `plan.json` stores `PlanBundle`
- `rounds/<round_id>.json` stores `{ contract, executed_queries, evaluation }`
- `execution_log.json` stores runtime execution metadata
- `final_answer.json` stores `FinalAnswer`
- `domain_pack_suggestions.json` stores `DomainPackSuggestions` only when needed

For consumers that need the full persisted context, use
`load_session_evidence(slug)`.

---

## Domain Pack Role

Domain packs are the only company-specific configuration layer in this skill family.

They tune:

- metric and dimension vocabulary mapping
- problem-type scoring hints
- unsupported-dimension hints
- performance risk hints
- hypothesis family priors and operator preferences

They do not replace:

- the shared contracts
- the five-layer methodology
- the requirement that SQL must be fully authored upstream by the LLM

For new company or business contexts, `target_pack_id` is resolved using the
documented deterministic slug rule.

---

## Validation Status

The repository includes contract-level tests for the runtime closure.

Covered behaviors:

- `QueryExecutionRequest -> QueryExecutionResult`
- `cache_policy` three-state behavior
- `execution_log.json` persistence
- `rounds/<round_id>.json` persistence
- `blocked_runtime` mechanical preconditions
- `FinalAnswer` consistency with the latest round evaluation
- `InvestigationContract` execution handoff
- deterministic domain pack suggestion target ids
- dialect-aware schema probe quoting

Test file:

- [tests/test_runtime_contracts.py](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/tests/test_runtime_contracts.py)

---

## Non-Negotiable Rules

1. The runtime returns facts, validates contracts, and executes explicit requests. It does not infer missing semantics.
2. The LLM authors all executable SQL.
3. Round 1 is audit-first.
4. Every supported claim in `FinalAnswer` must trace to concrete query evidence.
5. Contradictions stay explicit; they are not silently smoothed away.
6. `blocked_runtime` is reserved for sessions where runtime blocking prevented all usable evidence.

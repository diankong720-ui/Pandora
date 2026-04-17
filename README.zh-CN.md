# Deep Research Skill 文档与 Runtime 体系

这个项目是一套以 contract 为中心、由 LLM 主导的业务研究 skill 栈。

它当前已经不再是“文档加若干通用工具”的状态，而是把共享 contract、skill 文档、
runtime 执行层、artifact 持久化层和一致性校验层收口成了一套明确工作流。

核心边界：

- `LLM` 负责语义理解、意图规范化、schema 解释、假设规划、SQL 编写、评估内容和最终结论。
- `runtime` 负责安全校验、查询执行、缓存策略、仓库准入、artifact 持久化，以及 contract 级一致性检查。
- `runtime` 永远不会根据语义占位符去拼接、模板化或生成 SQL。

---

## 当前已闭合的内容

这套仓库现在已经在“文档 + runtime”两个层面形成闭合：

- 阶段顺序明确
- 共享对象只有一个 contract 来源
- runtime 可以直接消费正式执行 contract
- 每轮结果和最终结果都按文档定义的 shape 落盘
- post-session 的 domain pack suggestion 具备确定性 `target_pack_id` 规则

这意味着实现者可以从文档一路映射到 runtime 实际接口，而不需要靠临场补胶水来完成主流程。

---

## 阶段流程

串行流程不可跳过。

```text
1. intent-recognition               -> IntentRecognitionResult
2. data-discovery                   -> DataContextBundle
3. hypothesis-engine                -> PlanBundle
4. execution                        -> QueryExecutionResult[]
5. investigation-evaluator          -> RoundEvaluationResult
6. persistence                      -> RESEARCH/<slug>/
7. domain pack suggestion synthesis -> domain_pack_suggestions.json（尽力而为）
```

规则：

- 阶段不能跳过，也不能重排
- `NormalizedIntent` 在 Stage 1 结束后冻结
- Stage 2 只做 discovery，不做 headline 验证，也不计算 delta
- Stage 4 只能执行显式 `InvestigationContract.queries[]`
- Stage 5 不产生执行证据，它只评估已经持久化的查询结果
- Domain Pack Suggestion Synthesis 只在会话结束后运行，且不能阻塞最终答案

---

## 核心文档

- [contracts.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/deep-research/references/contracts.md)：共享 contract 的唯一事实源
- [core-methodology.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/deep-research/references/core-methodology.md)：residual 逻辑、停止策略与 conclusion state 纪律
- [intent-recognition/SKILL.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/intent-recognition/SKILL.md)：Stage 1 意图规范化
- [data-discovery/SKILL.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/data-discovery/SKILL.md)：Stage 2 环境发现
- [hypothesis-engine.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/deep-research/sub-skills/hypothesis-engine.md)：Stage 3 规划
- [investigation-evaluator.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/deep-research/sub-skills/investigation-evaluator.md)：Stage 5 评估规则
- [DOMAIN_PACK_GUIDE.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/deep-research/domain-packs/DOMAIN_PACK_GUIDE.md)：domain pack schema 与消费矩阵

如果某个 stage 文档与共享对象定义冲突，以 `contracts.md` 为准。

---

## Runtime 能力面

runtime 现在不再只是若干独立 helper，而是已经提供了正式的 contract handoff 入口。

主要入口：

- [runtime/tools.py](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/runtime/tools.py)：`execute_query_request()` 与兼容层 `execute_sql()`
- [runtime/orchestration.py](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/runtime/orchestration.py)：`execute_investigation_contract()`、`execute_round_and_persist()`、`finalize_session()`
- [runtime/evaluation.py](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/runtime/evaluation.py)：`RoundEvaluationResult` 校验与落盘
- [runtime/final_answer.py](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/runtime/final_answer.py)：`FinalAnswer` 校验与落盘
- [runtime/domain_pack_suggestions.py](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/runtime/domain_pack_suggestions.py)：domain pack suggestion 校验与落盘
- [runtime/persistence.py](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/runtime/persistence.py)：artifact I/O、execution log、round bundle、session evidence 读取
- [runtime/domain_packs.py](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/runtime/domain_packs.py)：pack registry 与确定性 target-pack 解析

runtime 当前保证：

- 只执行 LLM 已经写好的 SQL
- 在执行前做单语句安全校验
- 严格执行 `cache_policy = bypass | allow_read | require_read`
- 将执行元数据写入 `execution_log.json`
- 将每轮结果按 `{ contract, executed_queries, evaluation }` 写入 `rounds/<round_id>.json`
- 校验 `blocked_runtime` 与 `FinalAnswer.conclusion_state` 的机械一致性

runtime 当前不会做的事情：

- 推断 join、filter 或时间窗口
- 将语义 query plan 编译成 SQL
- 生成 evaluator 推理或最终结论内容

---

## 共享对象

所有共享对象统一定义在 `contracts.md`：

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

## Artifact 布局

每个 session 只落盘显式对象：

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

artifact 语义：

- `intent.json` 存 `NormalizedIntent`
- `intent_sidecar.json` 存 `pack_gaps`
- `environment_scan.json` 存 `DataContextBundle`
- `plan.json` 存 `PlanBundle`
- `rounds/<round_id>.json` 存 `{ contract, executed_queries, evaluation }`
- `execution_log.json` 存 runtime 执行元数据
- `final_answer.json` 存 `FinalAnswer`
- `domain_pack_suggestions.json` 仅在需要时存 `DomainPackSuggestions`

如果上层需要完整的显式证据上下文，统一使用 `load_session_evidence(slug)`。

---

## Domain Pack 的角色

Domain pack 是这套 skill 中唯一的公司定制化配置层。

它负责调优：

- 指标与维度词汇映射
- problem type 打分提示
- unsupported dimension 提示
- performance risk 提示
- hypothesis family prior 与 operator preference

它不会替代：

- 共享 contract
- 五层方法论
- “SQL 必须由 LLM 完整编写”这一原则

对于新公司或新业务场景，`target_pack_id` 会按文档规定的 deterministic slug 规则生成。

---

## 验证状态

仓库内已经包含 contract 级 runtime 验收测试。

已覆盖行为：

- `QueryExecutionRequest -> QueryExecutionResult`
- `cache_policy` 三态行为
- `execution_log.json` 落盘
- `rounds/<round_id>.json` 落盘
- `blocked_runtime` 机械前提校验
- `FinalAnswer` 与最新 round evaluation 的一致性
- `InvestigationContract` 执行 handoff
- deterministic domain pack suggestion target id
- schema probe 的方言安全 quoting

测试文件：

- [tests/test_runtime_contracts.py](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/tests/test_runtime_contracts.py)

---

## 不可违反的规则

1. runtime 只返回事实、校验 contract、执行显式请求，不推断缺失语义。
2. 所有可执行 SQL 都由 LLM 编写。
3. Round 1 必须 audit-first。
4. `FinalAnswer` 中每条 supported claim 都必须能追溯到具体查询证据。
5. 矛盾必须显式保留，不能被悄悄抹平。
6. `blocked_runtime` 只用于 runtime 阻断了整场会话全部可用证据的情况。

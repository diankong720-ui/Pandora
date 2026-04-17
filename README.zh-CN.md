# Deep Research Skill 文档体系

这套文档描述的是一个由 LLM 主导的业务研究工作流。设计原则很明确：

- LLM 负责语义判断、规划、SQL 编写、证据解释与结论输出。
- runtime 只负责通用工具、安全校验、执行、缓存、仓库准入和工件持久化。

文档重构后的目标，是让实现者只靠共享 contract 就能落地，不需要自行补接口。

---

## 阶段流程

串行流程不可跳过。

```text
1. intent-recognition      -> IntentRecognitionResult
2. data-discovery          -> DataContextBundle
3. hypothesis-engine       -> PlanBundle
4. execution               -> QueryExecutionResult[]
5. investigation-evaluator -> RoundEvaluationResult
6. persistence             -> RESEARCH/<slug>/
7. domain pack suggestion synthesis -> domain_pack_suggestions.json（尽力而为）
```

规则：

- 阶段不能跳过，也不能重排。
- `NormalizedIntent` 在 Stage 1 结束后冻结。
- Stage 2 只做 discovery，不做 headline 验证，也不计算 delta 证据。
- Stage 4 只能执行 `InvestigationContract.queries[]`。
- Domain Pack Suggestion Synthesis 只在会话结束后运行，且不能阻塞最终答案。

---

## 核心文档

- [skills/deep-research/references/contracts.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/deep-research/references/contracts.md)：共享 contract 的唯一事实源
- [skills/deep-research/references/core-methodology.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/deep-research/references/core-methodology.md)：领域无关的方法论、residual 规则、停止策略
- [skills/intent-recognition/SKILL.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/intent-recognition/SKILL.md)：Stage 1 意图规范化
- [skills/data-discovery/SKILL.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/data-discovery/SKILL.md)：Stage 2 环境发现
- [skills/deep-research/sub-skills/hypothesis-engine.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/deep-research/sub-skills/hypothesis-engine.md)：Stage 3 规划
- [skills/deep-research/sub-skills/investigation-evaluator.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/deep-research/sub-skills/investigation-evaluator.md)：Stage 5 评估
- [skills/deep-research/domain-packs/DOMAIN_PACK_GUIDE.md](/Users/shijidiankong/Vibe%20coding%20项目/Data%20analysis%20assistant/pure%20data%20analysis%20skill/skills/deep-research/domain-packs/DOMAIN_PACK_GUIDE.md)：domain pack schema 与消费关系

---

## 共享对象

所有跨阶段对象统一定义在 `contracts.md`：

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

如果任一 skill 文档与这些 contract 冲突，以 `contracts.md` 为准。

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
  domain_pack_suggestions.json   # 仅 Domain Pack Suggestion Synthesis 有缺口时写入
  manifest.json
```

持久化层只负责写文件，不负责补字段。

---

## Domain Pack 的角色

Domain pack 是这套 skill 中唯一的公司定制化配置层。

它可以提供：

- 业务词汇别名
- canonical problem type 提示
- unsupported dimension 提示
- performance risk 提示
- hypothesis family prior 与 operator 偏好

它不会替代共享方法论，只是调优 LLM 的使用方式。

---

## 不可违反的规则

1. runtime 只返回事实并执行显式请求，不推断缺失语义。
2. 所有可执行 SQL 都由 LLM 编写。
3. Round 1 必须 audit-first。
4. `FinalAnswer` 中每条 supported claim 都必须能追溯到具体查询证据。
5. 矛盾必须显式保留，不能被悄悄抹平。
6. `blocked_runtime` 只用于 runtime 阻断了整场会话的全部可用证据的情况。

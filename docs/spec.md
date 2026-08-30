# Skill Learning Engine V1 Specification

## 1. 定位

Skill Learning Engine 是一个通用的离线 Skill 自学习与演化系统。它在不更新
模型参数的前提下，从任务执行轨迹中沉淀持久知识，生成候选 Skill
修改，并通过独立验证集决定是否发布新版本。

项目受 WikiSkill 论文启发，但是独立的非官方工程实现。底层智能组件复用
AgentLoop 运行时；评测、版本、门禁和回滚由确定性 Python 代码控制。

## 2. V1 目标

V1 必须实现一个可测试的完整闭环：

1. 读取包含 Train、Validation、Test 的通用任务集。
2. Task Executor 使用当前 Skill 执行训练任务并保存不可变 Raw Trace。
3. Knowledge Maintainer 从成功和失败轨迹中产生结构化 Pattern。
4. Skill Proposer 每轮只对一个 Skill 提出一个原子文本补丁。
5. 候选 Skill 在隔离目录中评测，不直接修改正式版本。
6. 只有 Validation 分数严格提升时才发布；否则拒绝候选版本。
7. 无论提案是否发布，Wiki 和 Skill Impact Log 都保留历史经验。
8. 演化结束后只在 Test 集上报告最终版本效果。

## 3. 非目标

V1 不实现：

- 模型微调、梯度更新、LoRA 或强化学习。
- 生产环境中的在线自动修改。
- 多个 Skill 的同时更新或依赖图调度。
- 向量数据库、Embedding 检索或 Wiki 自动剪枝。
- 论文中所有 Benchmark 和所有模型的完整复现。
- 由 LLM 直接决定候选版本是否发布。

## 4. 系统边界

```text
Task Adapter
    │
    ▼
Task Executor ───────────────┐
    │                              │
    ▼                              │
Raw Trace                          │
    │                              │
    ▼                              │
Knowledge Maintainer              │
    │                              │
    ▼                              │
Persistent Wiki                   │
    │                              │
    ▼                              │
Skill Proposer ◀── Active Skill ─────┘
    │
    ▼
Candidate Skill
    │
    ▼
Deterministic Evaluator
    │
    ▼
Evaluation Gate ─── Accept / Reject
    │
    ▼
Skill Impact Log
```

AgentLoop 只负责 Task Executor、Knowledge Maintainer 和 Skill Proposer 的模型调用、
工具循环与上下文管理。外层 Evolution Loop 不得写入 AgentLoop 核心循环。

## 5. 三层工作区

```text
workspace/
├── state.json
├── raw/
│   └── iteration-<NNN>/
│       ├── validation-baseline/<task-id>.json
│       ├── train/<task-id>.json
│       ├── validation-candidate/<task-id>.json
│       └── test-final/<task-id>.json
├── wiki/
│   ├── index.md
│   ├── patterns/<pattern-id>.md
│   ├── logs.md
│   └── skill-impact.md
├── skills/
│   └── <skill-name>/
│       ├── SKILL.md
│       └── PURPOSE.md
├── candidates/
│   └── iteration-<NNN>/<skill-name>/...
└── versions/
    └── <skill-name>/v<NNN>/...
```

约束：

- `raw/` 文件创建后不得覆盖。
- Wiki 由结构化 Maintainer 结果增量更新，LLM 不直接写盘。
- Proposer 只写隔离 Candidate，不直接写入 `skills/`。
- 发布操作先快照正式 Skill，再原子替换文件。

## 6. 核心数据契约

### 6.1 Task

```json
{
  "id": "train-001",
  "split": "train",
  "input": "task input",
  "expected": "ground truth",
  "metadata": {}
}
```

### 6.2 Raw Trace

```json
{
  "id": "trace-...",
  "iteration": 0,
  "split": "train",
  "task_id": "train-001",
  "skill_name": "normalize",
  "skill_version": 0,
  "answer": "...",
  "score": 0.0,
  "passed": false,
  "messages": [],
  "usage": {}
}
```

### 6.3 Pattern

```json
{
  "id": "lowercase-normalization",
  "title": "Normalize case before returning",
  "observation": "Case-sensitive mismatches recur.",
  "strategy": "Trim and lowercase the payload.",
  "evidence_ids": ["trace-..."]
}
```

### 6.4 Skill Proposal

```json
{
  "skill_name": "normalize",
  "summary": "Normalize output before returning",
  "old_text": "Return the input unchanged.",
  "new_text": "Return the lowercase, trimmed input.",
  "evidence_ids": ["trace-..."],
  "pattern_ids": ["lowercase-normalization"]
}
```

`old_text` 必须在当前 `SKILL.md` 中恰好出现一次，否则提案失败并不进入评测。

## 7. 运行时契约

```python
class StructuredRuntime(Protocol):
    def run(
        self,
        *,
        role: str,
        system_prompt: str,
        user_prompt: str,
        result_schema: dict,
        workdir: Path,
    ) -> dict: ...
```

`AgentLoopRuntime` 必须：

- 为每次调用创建独立 Agent 与独立消息历史。
- 只提供 `read_file`、`glob` 和 `submit_result` 等角色所需最小工具。
- 必须通过 `submit_result` 提交结构化结果，纯文本最终回答不构成成功。
- 必须对结果执行 Schema 校验。
- 不提供 Bash、网络或直接替换正式 Skill 的工具。

## 8. 知识更新

Maintainer 每轮输入：

- 当前 Wiki 索引。
- 最多 5 条失败训练轨迹。
- 最多 3 条成功训练轨迹。

抽样使用稳定排序，不依赖随机数。Pattern ID 必须是安全的小写 slug；引用的
Evidence ID 必须真实存在于本轮 Raw Trace。

## 9. 评测与发布门禁

评测器必须对同一 Validation 任务集计算：

```text
mean_score = sum(task_score) / task_count
```

默认接受规则：

```text
candidate_mean_score > best_validation_score + epsilon
```

V1 的 `epsilon` 默认为 0。候选评测异常、任务缺失、分数非有限数、空补丁或
Schema 不合法时必须 Fail Closed。

Test 集不参与发布决策。

## 10. 迭代状态机

```text
BASELINE_EVALUATED
    → TRAIN_ROLLOUTS_STORED
    → WIKI_UPDATED
    → PROPOSAL_CREATED
    → CANDIDATE_BUILT
    → CANDIDATE_EVALUATED
    → ACCEPTED | REJECTED | FAILED
    → IMPACT_RECORDED
```

任意阶段失败都不得改变当前正式 Skill。

## 11. CLI

```text
skill-learning init --workspace <dir> --skill-name <name>
skill-learning run --workspace <dir> --tasks <jsonl> --iterations <n>
skill-learning demo --workspace <dir>
```

`demo` 使用确定性本地 Runtime 验证编排链路，不代表真实模型的 Skill 学习效果。
`run` 使用 AgentLoop 的模型配置。

## 12. V1 验收标准

1. Python 3.10+ 单元测试全部通过，且不访问网络。
2. AgentLoop MockClient 集成测试证明 `submit_result` 契约可用。
3. Demo 至少包含一次被接受的 Skill 修改。
4. 被拒绝的候选版本不得改变正式 `SKILL.md`。
5. Wiki 在 Skill 被拒绝时仍然保留本轮 Pattern 与 Impact。
6. Test 分数只在演化结束后计算。
7. 所有发布决定可从 `skill-impact.md` 和 `state.json` 重建。

## 13. 公开与表述边界

- README 必须引用 WikiSkill 论文并标注非官方实现。
- 不将通用 Agent Loop、ReAct 或 Skill 文件格式描述为原创发明。
- Demo 数据与真实模型实验必须分开报告。
- 简历量化数字只能来自可重复的真实评测。

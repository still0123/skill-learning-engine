# Skill Learning Engine V2 Specification

## 1. 目标

V2 将 V1 的“可运行演化闭环”升级为“可复现、可对照、无评测泄漏的实验系统”。
它仍然是受 WikiSkill 启发的独立工程实现，不以复现论文全部 Benchmark 或结果为目标。

V2 必须回答四个问题：

1. 同一模型在无额外 Skill、初始人工 Skill、演化后 Skill 下分别表现如何？
2. 演化后的提升来自哪些具体任务，是否伴随回退？
3. 数据、代码、Prompt、模型配置和 Skill 版本是否能够被追溯？
4. Executor、Maintainer 和 Proposer 是否只能访问各自被授权的信息？

## 2. 范围

V2 实现：

- 运行级 Manifest 和输入快照。
- No Skill、Seed Skill、Evolved Skill 三条件最终 Test 对照。
- 基于 task ID 的成对 Validation 门禁。
- 多次独立重复运行及成对 Bootstrap 置信区间。
- JSON 与 Markdown 实验报告。
- 通用结构化 JSON 任务适配器和独立示例 Benchmark。
- 角色级工具白名单和 Proposer 最小只读视图。
- 结构化 Evaluation、Impact Event 和运行用量统计。

V2 不实现：

- 模型参数训练、强化学习或在线自动修改。
- 论文全部五个 Benchmark、全部 Baseline 或跨模型迁移矩阵。
- 生产系统、真实流水线或个人飞书数据接入。
- LLM 直接读 Validation/Test 标签或自行决定发布。
- 仅凭一次模型运行宣称稳定收益或统计显著性。

## 3. 实验目录

```text
experiments/<experiment-id>/
├── manifest.json
├── inputs/
│   ├── tasks.jsonl
│   ├── seed-skill.md
│   └── prompts/*.md
├── repeat-001/workspace/...
├── repeat-002/workspace/...
├── repeat-003/workspace/...
├── summary.json
└── report.md
```

`manifest.json` 至少记录：

- UTC 开始时间、源代码 commit 和 Python 版本。
- 数据集、初始 Skill 和三个角色 Prompt 的 SHA-256。
- 每次 Repeat 实际执行的 Prompt 直接来自本次输入快照；Runtime 描述若跨 Repeat 漂移则
  实验 Fail Closed。
- 任务适配器、模型标识、迭代次数、重复次数、门禁策略和 Bootstrap 参数。
- 不包含 API Key、完整环境变量或其他凭据。

## 4. 三条件 Test 协议

演化期间只访问 Train 和 Validation。所有迭代完成后，才依次评测：

1. `no_skill`：不注入额外程序性指令。
2. `seed_skill`：评测实验开始时的初始 Skill。
3. `evolved_skill`：评测最终被门禁接受的 Skill。

三种条件必须使用同一 Test task ID 集合和同一评分器。报告以成对 task score 计算：

```text
seed_gain = seed_skill - no_skill
evolution_gain = evolved_skill - seed_skill
total_gain = evolved_skill - no_skill
```

Test 结果不得写回 Wiki、不得影响候选接受，也不得提供给 Proposer。

## 5. 评分契约

```python
@dataclass(frozen=True)
class Score:
    value: float
    metrics: dict[str, float]
    feedback: str
```

- `value` 与每个 metric 均必须是 `[0, 1]` 内有限数。
- Trace 同时保存总分、分项指标和评分反馈。
- Adapter 必须暴露稳定名称和数据集指纹。
- V2 内置 Exact Match 与 JSON Value 两种 Adapter。

## 6. 成对 Validation 门禁

Candidate 与当前最佳版本必须在相同 Validation task ID 上比较。门禁记录：

- 平均分差。
- 改善、持平、回退的 task ID。
- 每个公共 metric 的平均差。
- 拒绝原因。

默认规则保持与论文一致：Candidate 平均分必须严格大于 Best 加 `epsilon`。
工程使用者可额外配置 `min_improved_tasks` 和 `max_regressed_tasks`；这些属于本项目的
保守扩展，不表述为论文默认算法。task ID 不一致时 Fail Closed。

## 7. 角色隔离

### Task Executor

- 默认只有 `submit_result`，不能使用 `read_file` 或 `glob`。
- 输入只包含当前任务、当前 Skill 和非标签 metadata。
- 不能读取 Raw、Wiki、Validation/Test 文件或其他任务答案。

### Knowledge Maintainer

- 默认只有 `submit_result`。
- 输入最多包含 5 条失败 Train Trace 和 3 条成功 Train Trace。
- 单条 Trace 注入前最多保留 15,000 字符。

### Skill Proposer

- 可使用 `read_file`、`glob`、`submit_result`。
- 工作目录是每轮生成的最小只读视图，只包含 Wiki、Impact、当前 Skill 和本轮 Train Trace。
- Prompt 只提供 outcome 摘要；详细 Trace 必须按需读取。
- 若本轮至少有 4 条 Train Trace，提交前必须读取至少 4 条不同 Trace；不足 4 条时读取全部。
- 视图中不存在 Validation/Test Trace。

## 8. 可复现统计

一次 Experiment 默认运行 3 次完整独立演化。每次使用全新的 Workspace，并保留该次
所有 Raw Trace、Wiki、候选、版本和 Test 条件结果。

报告对成对 task score difference 执行确定性 Bootstrap：

- 默认 1,000 次重采样。
- 固定 seed。
- 先对每个 task 的重复运行分数取均值，再按唯一 task ID 重采样，避免把同一任务的
  多次运行错误当成独立样本。
- 输出 observed mean delta 和 95% percentile CI；p-value 单独使用零效应假设下的
  双侧 paired sign-flip randomization test 计算，不从普通 Bootstrap 分布推导。
- 默认少于 10 个唯一 Test task 时标记样本不足，不得输出“显著提升”结论。

Bootstrap 结果只用于最终报告，不参与 Skill 发布门禁。

## 9. 机器可读事件

除 Markdown 展示文件外，Workspace 还必须保存：

```text
events/
├── evaluations.jsonl
└── skill-impact.jsonl
```

Evaluation Event 记录 phase、iteration、Skill 版本/哈希、均分、逐 task 分数和用量。
Impact Event 记录 Proposal、统一 Diff、Best/Candidate 分数、成对变化、接受结果和版本变化。

## 10. CLI

```text
skill-learning experiment \
  --output <dir> \
  --tasks <jsonl> \
  --adapter exact|json \
  --skill-name <name> \
  --skill-file <SKILL.md> \
  --iterations <n> \
  --repeats <n> \
  --bootstrap-samples <n>
```

真实模型实验产生 API 成本，CLI 不自动猜测模型；必须由使用者显式配置
`AGENTLOOP_MODEL` 及对应凭据。

## 11. 验收标准

1. V1 测试继续通过。
2. JSON Adapter 能区分非法 JSON 与语义匹配。
3. Gate 在 task ID 不一致时拒绝，并正确报告改善/回退任务。
4. Executor 看不到文件工具；Proposer 不能读取 Validation/Test。
5. Test 仅在演化结束后运行，并输出三条件成对结果。
6. 三次确定性重复运行生成一致的 Manifest 哈希和统计结果。
7. Bootstrap 使用固定 seed 可复现。
8. 报告明确区分确定性 Demo、真实模型数据和论文原始结论。
9. 干净虚拟环境安装、全部单测和 GitHub CI 通过。

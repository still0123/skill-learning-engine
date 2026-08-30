# Record Operations Benchmark

This is a small, self-contained benchmark for learning and evaluating a general structured-data transformation Skill. It is deliberately unrelated to pipeline diagnosis or any operational domain.

`tasks.jsonl` contains 28 JSONL tasks:

| Split | Count | Role |
| --- | ---: | --- |
| `train` | 10 | Generates execution traces and persistent patterns |
| `validation` | 6 | Chooses whether a candidate Skill may be promoted |
| `test` | 12 | Final held-out evaluation only |

Each task has four fields:

- `id`: unique task identifier.
- `split`: `train`, `validation`, or `test`.
- `input`: a JSON-encoded request with `records` and an ordered `operations` list.
- `expected`: the ground-truth JSON value, retained as a JSON array or object rather than a natural-language answer.
- `metadata.category`: the primary capability under test.

The benchmark covers filtering, multi-key sorting, projection, first/last de-duplication, sum/average/count aggregation, missing-value filling, JSON type preservation, and order-sensitive operation chains. Records and operation combinations are distinct across splits.

The seed Skill at `skills/record-ops/SKILL.md` supplies the execution contract but intentionally does not include task answers. A learner should produce exactly one valid JSON value and use validation improvement, not training performance alone, to decide whether to publish an evolved Skill.

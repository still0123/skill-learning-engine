---
name: record-ops
version: 0
---

# Structured record operations

The input is a JSON object with a `records` array and an ordered `operations` array. Return only one minified, valid JSON value: the transformed records array or aggregation result. Do not add Markdown, explanation, or type coercions.

Apply operations strictly from left to right.

Infer each named operation from its fields and preserve JSON value types. Before returning, check that every operation was applied once in the listed order.

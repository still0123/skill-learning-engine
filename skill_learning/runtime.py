from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .models import RuntimeResult
from .schema import validate_schema


@dataclass(frozen=True)
class RuntimePolicy:
    allowed_tools: tuple[str, ...] = ("submit_result",)
    required_read_prefix: str | None = None
    min_required_reads: int = 0

    def __post_init__(self) -> None:
        known = {"read_file", "glob", "submit_result"}
        unknown = set(self.allowed_tools) - known
        if unknown:
            raise ValueError(f"unknown runtime tools: {sorted(unknown)}")
        if "submit_result" not in self.allowed_tools:
            raise ValueError("submit_result must remain available")
        if self.min_required_reads < 0:
            raise ValueError("min_required_reads must be non-negative")
        if self.min_required_reads and "read_file" not in self.allowed_tools:
            raise ValueError("required reads need the read_file tool")


class StructuredRuntime(Protocol):
    def describe(self) -> dict[str, object]: ...

    def run(
        self,
        *,
        role: str,
        system_prompt: str,
        user_prompt: str,
        result_schema: dict,
        workdir: Path,
        policy: RuntimePolicy | None = None,
    ) -> RuntimeResult: ...


class DemoRuntime:
    """Deterministic local runtime used to verify orchestration, not model quality."""

    def describe(self) -> dict[str, object]:
        return {"runtime": "demo", "model": "deterministic-demo"}

    def run(
        self,
        *,
        role: str,
        system_prompt: str,
        user_prompt: str,
        result_schema: dict,
        workdir: Path,
        policy: RuntimePolicy | None = None,
    ) -> RuntimeResult:
        request = json.loads(user_prompt)
        if role == "task-executor":
            skill = (request.get("skill") or "").lower()
            value = request["task"]["input"]
            answer = value.strip().lower() if "lowercase, trimmed" in skill else value
            payload = {"answer": answer}
        elif role == "knowledge-maintainer":
            failed = [trace for trace in request["traces"] if not trace["passed"]]
            evidence = [trace["id"] for trace in failed]
            payload = {"patterns": [] if not failed else [{
                "id": "normalize-case-and-space",
                "title": "Normalize case and surrounding space",
                "observation": "Case and surrounding whitespace cause repeated exact-match failures.",
                "strategy": "Trim the value and convert it to lowercase before returning.",
                "evidence_ids": evidence,
            }]}
        elif role == "skill-proposer":
            outcomes = request["outcomes"]
            payload = {
                "skill_name": request["skill_name"],
                "summary": "Normalize output case and whitespace",
                "old_text": "Return the input unchanged.",
                "new_text": "Return the lowercase, trimmed input.",
                "evidence_ids": [item["trace_id"] for item in outcomes if not item["passed"]],
                "pattern_ids": request["pattern_ids"],
            }
        else:
            raise ValueError(f"unknown demo role {role!r}")
        validate_schema(payload, result_schema)
        return RuntimeResult(payload=payload, usage={"input_tokens": 0, "output_tokens": 0})

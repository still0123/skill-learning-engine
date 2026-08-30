from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .models import RuntimeResult
from .schema import validate_schema


class StructuredRuntime(Protocol):
    def run(
        self,
        *,
        role: str,
        system_prompt: str,
        user_prompt: str,
        result_schema: dict,
        workdir: Path,
    ) -> RuntimeResult: ...


class DemoRuntime:
    """Deterministic local runtime used to verify orchestration, not model quality."""

    def run(
        self,
        *,
        role: str,
        system_prompt: str,
        user_prompt: str,
        result_schema: dict,
        workdir: Path,
    ) -> RuntimeResult:
        request = json.loads(user_prompt)
        if role == "task-executor":
            skill = request["skill"].lower()
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
            traces = request["traces"]
            patterns = request["patterns"]
            payload = {
                "skill_name": request["skill_name"],
                "summary": "Normalize output case and whitespace",
                "old_text": "Return the input unchanged.",
                "new_text": "Return the lowercase, trimmed input.",
                "evidence_ids": [trace["id"] for trace in traces if not trace["passed"]],
                "pattern_ids": [pattern["id"] for pattern in patterns],
            }
        else:
            raise ValueError(f"unknown demo role {role!r}")
        validate_schema(payload, result_schema)
        return RuntimeResult(payload=payload, usage={"input_tokens": 0, "output_tokens": 0})

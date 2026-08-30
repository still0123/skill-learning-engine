from __future__ import annotations

import json
import math
import re
from importlib import resources
from pathlib import Path

from .models import Evaluation, Pattern, SkillProposal, Task, Trace
from .runtime import StructuredRuntime
from .tasks import TaskAdapter


EXECUTOR_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}

MAINTAINER_SCHEMA = {
    "type": "object",
    "properties": {
        "patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "observation": {"type": "string"},
                    "strategy": {"type": "string"},
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["id", "title", "observation", "strategy", "evidence_ids"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["patterns"],
    "additionalProperties": False,
}

PROPOSER_SCHEMA = {
    "type": "object",
    "properties": {
        "skill_name": {"type": "string"},
        "summary": {"type": "string"},
        "old_text": {"type": "string"},
        "new_text": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "pattern_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "skill_name",
        "summary",
        "old_text",
        "new_text",
        "evidence_ids",
        "pattern_ids",
    ],
    "additionalProperties": False,
}

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def load_prompt(name: str) -> str:
    return resources.files("skill_learning").joinpath("prompts", name).read_text(encoding="utf-8")


class TaskExecutor:
    def __init__(self, runtime: StructuredRuntime, adapter: TaskAdapter) -> None:
        self.runtime = runtime
        self.adapter = adapter

    def evaluate(
        self,
        *,
        tasks: list[Task],
        skill_name: str,
        skill_version: int,
        skill_text: str,
        iteration: int,
        phase: str,
        workdir: Path,
    ) -> Evaluation:
        traces: list[Trace] = []
        for task in tasks:
            prompt = json.dumps(
                {
                    "task": {
                        "id": task.id,
                        "input": self.adapter.render(task),
                        "metadata": task.metadata,
                    },
                    "skill_name": skill_name,
                    "skill_version": skill_version,
                    "skill": skill_text,
                },
                ensure_ascii=False,
            )
            result = self.runtime.run(
                role="task-executor",
                system_prompt=load_prompt("executor.md"),
                user_prompt=prompt,
                result_schema=EXECUTOR_SCHEMA,
                workdir=workdir,
            )
            answer = result.payload["answer"]
            score = float(self.adapter.score(task, answer))
            if not math.isfinite(score) or not 0.0 <= score <= 1.0:
                raise ValueError(f"adapter returned invalid score {score!r} for task {task.id}")
            traces.append(Trace(
                id=f"trace-{iteration:03d}-{phase}-{task.id}",
                iteration=iteration,
                phase=phase,
                split=task.split,
                task_id=task.id,
                skill_name=skill_name,
                skill_version=skill_version,
                task_input=task.input,
                expected=task.expected,
                answer=answer,
                score=score,
                passed=score >= 1.0,
                messages=result.messages,
                usage=result.usage,
            ))
        if not traces:
            raise ValueError(f"cannot evaluate an empty {phase} task set")
        mean = sum(trace.score for trace in traces) / len(traces)
        return Evaluation(split=tasks[0].split, phase=phase, mean_score=mean, traces=traces)


class KnowledgeMaintainer:
    def __init__(self, runtime: StructuredRuntime) -> None:
        self.runtime = runtime

    def update(
        self,
        *,
        wiki_index: str,
        traces: list[Trace],
        workdir: Path,
    ) -> list[Pattern]:
        failed = sorted((trace for trace in traces if not trace.passed), key=lambda item: item.id)[:5]
        passed = sorted((trace for trace in traces if trace.passed), key=lambda item: item.id)[:3]
        selected = [*failed, *passed]
        result = self.runtime.run(
            role="knowledge-maintainer",
            system_prompt=load_prompt("maintainer.md"),
            user_prompt=json.dumps(
                {
                    "wiki_index": wiki_index,
                    "traces": [trace.to_dict() for trace in selected],
                },
                ensure_ascii=False,
            ),
            result_schema=MAINTAINER_SCHEMA,
            workdir=workdir,
        )
        allowed_evidence = {trace.id for trace in selected}
        patterns: list[Pattern] = []
        seen: set[str] = set()
        for item in result.payload["patterns"]:
            pattern_id = item["id"].strip()
            if not _SLUG.fullmatch(pattern_id) or pattern_id in seen:
                raise ValueError(f"invalid or duplicate pattern id {pattern_id!r}")
            evidence = tuple(item["evidence_ids"])
            if not evidence or any(item_id not in allowed_evidence for item_id in evidence):
                raise ValueError(f"pattern {pattern_id!r} cites unknown evidence")
            for field in ("title", "observation", "strategy"):
                if not item[field].strip():
                    raise ValueError(f"pattern {pattern_id!r} has empty {field}")
            seen.add(pattern_id)
            patterns.append(Pattern(
                id=pattern_id,
                title=item["title"].strip(),
                observation=item["observation"].strip(),
                strategy=item["strategy"].strip(),
                evidence_ids=evidence,
            ))
        if failed and not patterns:
            raise ValueError("maintainer returned no patterns for failing traces")
        return patterns


class SkillProposer:
    def __init__(self, runtime: StructuredRuntime) -> None:
        self.runtime = runtime

    def propose(
        self,
        *,
        skill_name: str,
        skill_text: str,
        patterns: list[Pattern],
        traces: list[Trace],
        impact_log: str,
        workdir: Path,
    ) -> SkillProposal:
        result = self.runtime.run(
            role="skill-proposer",
            system_prompt=load_prompt("proposer.md"),
            user_prompt=json.dumps(
                {
                    "skill_name": skill_name,
                    "current_skill": skill_text,
                    "patterns": [pattern.to_dict() for pattern in patterns],
                    "traces": [trace.to_dict() for trace in traces],
                    "skill_impact_log": impact_log,
                },
                ensure_ascii=False,
            ),
            result_schema=PROPOSER_SCHEMA,
            workdir=workdir,
        )
        item = result.payload
        if item["skill_name"] != skill_name:
            raise ValueError("proposer targeted a different skill")
        if not item["summary"].strip():
            raise ValueError("proposal summary is empty")
        if not item["old_text"] or not item["new_text"] or item["old_text"] == item["new_text"]:
            raise ValueError("proposal must contain a non-empty atomic text replacement")
        allowed_evidence = {trace.id for trace in traces}
        evidence_ids = tuple(item["evidence_ids"])
        if not evidence_ids or any(value not in allowed_evidence for value in evidence_ids):
            raise ValueError("proposal cites unknown evidence")
        allowed_patterns = {pattern.id for pattern in patterns}
        pattern_ids = tuple(item["pattern_ids"])
        if not pattern_ids or any(value not in allowed_patterns for value in pattern_ids):
            raise ValueError("proposal cites unknown patterns")
        return SkillProposal(
            skill_name=skill_name,
            summary=item["summary"].strip(),
            old_text=item["old_text"],
            new_text=item["new_text"],
            evidence_ids=evidence_ids,
            pattern_ids=pattern_ids,
        )

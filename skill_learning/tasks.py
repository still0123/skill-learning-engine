from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import Protocol

from .models import Score, Task


ALLOWED_SPLITS = {"train", "validation", "test"}


class TaskAdapter(Protocol):
    @property
    def name(self) -> str: ...

    def tasks(self, split: str) -> list[Task]: ...

    def render(self, task: Task) -> str: ...

    def score(self, task: Task, answer: str) -> Score: ...

    def dataset_fingerprint(self) -> str: ...


class ExactMatchJSONLAdapter:
    """Small public adapter for text tasks with exact-match ground truth."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._tasks = self._load()

    @property
    def name(self) -> str:
        return "exact"

    def _load(self) -> list[Task]:
        items: list[Task] = []
        seen: set[str] = set()
        for line_no, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{self.path}:{line_no}: invalid JSON: {exc}") from exc
            task_id = str(item.get("id", "")).strip()
            split = str(item.get("split", "")).strip()
            if not task_id or task_id in seen:
                raise ValueError(f"{self.path}:{line_no}: missing or duplicate task id {task_id!r}")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", task_id):
                raise ValueError(f"{self.path}:{line_no}: unsafe task id {task_id!r}")
            if split not in ALLOWED_SPLITS:
                raise ValueError(f"{self.path}:{line_no}: invalid split {split!r}")
            if "input" not in item or "expected" not in item:
                raise ValueError(f"{self.path}:{line_no}: input and expected are required")
            seen.add(task_id)
            items.append(Task(
                id=task_id,
                split=split,
                input=str(item["input"]),
                expected=item["expected"],
                metadata=dict(item.get("metadata") or {}),
            ))
        for split in ALLOWED_SPLITS:
            if not any(task.split == split for task in items):
                raise ValueError(f"{self.path}: split {split!r} is empty")
        return items

    def tasks(self, split: str) -> list[Task]:
        if split not in ALLOWED_SPLITS:
            raise ValueError(f"invalid split {split!r}")
        return [task for task in self._tasks if task.split == split]

    def render(self, task: Task) -> str:
        return task.input

    def score(self, task: Task, answer: str) -> Score:
        matched = answer.strip() == str(task.expected).strip()
        return Score(
            value=1.0 if matched else 0.0,
            metrics={"exact_match": 1.0 if matched else 0.0},
            feedback="exact match" if matched else "answer does not exactly match expected output",
        )

    def dataset_fingerprint(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


class JSONValueJSONLAdapter(ExactMatchJSONLAdapter):
    """Scores JSON values semantically while preserving JSON type distinctions."""

    @property
    def name(self) -> str:
        return "json"

    def score(self, task: Task, answer: str) -> Score:
        candidate = _extract_answer(answer)
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            return Score(
                value=0.0,
                metrics={"valid_json": 0.0, "exact_match": 0.0},
                feedback="answer is not valid JSON",
            )
        try:
            actual = _canonical_json(parsed)
            expected = _canonical_json(task.expected)
        except (TypeError, ValueError):
            return Score(
                value=0.0,
                metrics={"valid_json": 0.0, "exact_match": 0.0},
                feedback="answer contains a non-standard JSON value",
            )
        matched = actual == expected
        return Score(
            value=1.0 if matched else 0.0,
            metrics={"valid_json": 1.0, "exact_match": 1.0 if matched else 0.0},
            feedback="semantic JSON match" if matched else "valid JSON with a different value",
        )


def build_adapter(name: str, path: str | Path) -> TaskAdapter:
    adapters = {
        "exact": ExactMatchJSONLAdapter,
        "json": JSONValueJSONLAdapter,
    }
    try:
        adapter_type = adapters[name]
    except KeyError as exc:
        raise ValueError(f"unknown adapter {name!r}; choose one of {sorted(adapters)}") from exc
    return adapter_type(path)


def _extract_answer(answer: str) -> str:
    text = answer.strip()
    tagged = re.search(r"<answer>\s*(.*?)\s*</answer>", text, flags=re.DOTALL | re.IGNORECASE)
    if tagged:
        text = tagged.group(1).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    return fenced.group(1).strip() if fenced else text


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )

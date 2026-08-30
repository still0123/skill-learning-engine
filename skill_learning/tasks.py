from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .models import Task


ALLOWED_SPLITS = {"train", "validation", "test"}


class TaskAdapter(Protocol):
    def tasks(self, split: str) -> list[Task]: ...

    def render(self, task: Task) -> str: ...

    def score(self, task: Task, answer: str) -> float: ...


class ExactMatchJSONLAdapter:
    """Small public adapter for text tasks with exact-match ground truth."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._tasks = self._load()

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

    def score(self, task: Task, answer: str) -> float:
        return 1.0 if answer.strip() == str(task.expected).strip() else 0.0

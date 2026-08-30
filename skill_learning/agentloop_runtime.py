from __future__ import annotations

import glob as globlib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .models import RuntimeResult
from .runtime import RuntimePolicy
from .schema import validate_schema


class AgentLoopRuntime:
    """Structured, least-privilege adapter around the user's AgentLoop runtime."""

    def __init__(self, client: Any, *, max_turns: int = 20) -> None:
        self.client = client
        self.max_turns = max_turns

    def describe(self) -> dict[str, object]:
        model = getattr(self.client, "model", None)
        adapter = getattr(self.client, "adapter", None)
        description: dict[str, object] = {
            "runtime": "agentloop",
            "client": type(self.client).__name__,
            "model": model or "unknown",
            "adapter": adapter or "unknown",
            "max_turns": self.max_turns,
        }
        for attribute in ("base_url", "max_tokens", "timeout", "retries"):
            value = getattr(self.client, attribute, None)
            if isinstance(value, (str, int, float, bool)):
                description[attribute] = _safe_url(value) if attribute == "base_url" else value
        clients = getattr(self.client, "clients", None)
        if isinstance(clients, list):
            description["fallback_models"] = [
                str(getattr(client, "model", "unknown")) for client in clients
            ]
        return description

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
        try:
            from agentloop.agent import Agent
            from agentloop.compact import Compactor
            from agentloop.hooks import HookRegistry
            from agentloop.tools import Toolbox, safe_path
        except ImportError as exc:
            raise RuntimeError(
                "AgentLoop is required. Install the pinned project dependency first."
            ) from exc

        root = Path(workdir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        policy = policy or RuntimePolicy()
        submissions: list[dict[str, Any]] = []
        duplicate_submission = False
        successful_reads: set[str] = set()
        box = Toolbox()

        def read_file(path: str, limit: int = 50_000) -> str:
            target = safe_path(root, path)
            text = target.read_text(encoding="utf-8")
            relative = target.relative_to(root).as_posix()
            if (
                policy.required_read_prefix is None
                or relative == policy.required_read_prefix.rstrip("/")
                or relative.startswith(policy.required_read_prefix.rstrip("/") + "/")
            ):
                successful_reads.add(relative)
            return text[: max(0, min(limit, 200_000))]

        def glob_files(pattern: str) -> str:
            if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
                raise ValueError(f"glob escapes workspace: {pattern}")
            matches = sorted(globlib.glob(pattern, root_dir=str(root), recursive=True))
            return "\n".join(matches[:500]) if matches else "(no matches)"

        def submit_result(**payload: Any) -> str:
            nonlocal duplicate_submission
            if submissions:
                duplicate_submission = True
                raise ValueError("submit_result may be called exactly once")
            if len(successful_reads) < policy.min_required_reads:
                raise ValueError(
                    f"read at least {policy.min_required_reads} distinct files under "
                    f"{policy.required_read_prefix!r} before submitting; read {len(successful_reads)}"
                )
            validate_schema(payload, result_schema)
            submissions.append(payload)
            return "Structured result accepted. End the task now."

        if "read_file" in policy.allowed_tools:
            box.add(
                "read_file",
                "Read a UTF-8 file inside the assigned workspace.",
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["path"],
                },
                read_file,
            )
        if "glob" in policy.allowed_tools:
            box.add(
                "glob",
                "List files inside the assigned workspace using a glob pattern.",
                {
                    "type": "object",
                    "properties": {"pattern": {"type": "string"}},
                    "required": ["pattern"],
                },
                glob_files,
            )
        box.add(
            "submit_result",
            "Submit the final machine-readable result exactly once.",
            result_schema,
            submit_result,
        )

        hooks = HookRegistry()

        def require_submission(_messages: list[dict[str, Any]]) -> str | None:
            if not submissions:
                return "You must call submit_result exactly once before finishing."
            return None

        hooks.register("Stop", require_submission)
        compactor = Compactor(root, client=self.client, char_limit=200_000)
        agent = Agent(
            client=self.client,
            toolbox=box,
            hooks=hooks,
            compactor=compactor,
            system_prompt=f"Role: {role}\n\n{system_prompt}",
            max_turns=self.max_turns,
        )
        result = agent.run(user_prompt)
        if result.stopped_reason == "max_turns":
            raise RuntimeError(f"{role} reached max_turns without completing")
        if duplicate_submission or len(submissions) != 1:
            raise RuntimeError(f"{role} must submit exactly one structured result")
        validate_schema(submissions[0], result_schema)
        return RuntimeResult(
            payload=submissions[0],
            messages=result.messages,
            usage=dict(result.usage),
        )


def _safe_url(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
